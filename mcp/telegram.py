import contextvars
import logging
import os
from typing import Optional

from telegram_service import TelegramService

logger = logging.getLogger("connect.telegram")

VALID_LEVELS = ("basic", "standard", "advanced", "full")
LEVEL_ORDER = {level: i for i, level in enumerate(VALID_LEVELS)}

# Set by middleware from the URL path /mcp/telegram/<account>
account_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "account_override", default=None
)


class TelegramConfig:
    """Parse TELEGRAM_ACCOUNTS, tokens, tool levels, allowed chats, and allowed user IDs from environment."""

    def __init__(self):
        self.accounts: dict[str, str] = {}
        self.levels: dict[str, str] = {}
        self.allowed_chats: dict[str, set[str] | None] = {}
        self.allowed_user_ids: dict[str, set[int] | None] = {}
        default_level = os.environ.get("TELEGRAM_LEVEL", "basic").lower()
        if default_level not in VALID_LEVELS:
            default_level = "basic"

        accounts_raw = os.environ.get("TELEGRAM_ACCOUNTS", "")
        if not accounts_raw.strip():
            return
        for label in accounts_raw.split(","):
            label = label.strip()
            if not label:
                continue
            env_key = f"TELEGRAM_{label.upper()}_BOT_TOKEN"
            token = os.environ.get(env_key, "")
            if token:
                key = label.lower()
                self.accounts[key] = token
                level = os.environ.get(
                    f"TELEGRAM_{label.upper()}_LEVEL", default_level
                ).lower()
                if level not in VALID_LEVELS:
                    level = default_level
                self.levels[key] = level
                chats_raw = os.environ.get(
                    f"TELEGRAM_{label.upper()}_ALLOWED_CHATS", ""
                )
                if chats_raw.strip():
                    self.allowed_chats[key] = {
                        c.strip() for c in chats_raw.split(",") if c.strip()
                    }
                else:
                    self.allowed_chats[key] = None
                uids_raw = os.environ.get(
                    f"TELEGRAM_{label.upper()}_ALLOWED_USER_IDS", ""
                )
                if uids_raw.strip():
                    self.allowed_user_ids[key] = {
                        int(u.strip())
                        for u in uids_raw.split(",")
                        if u.strip()
                    }
                else:
                    self.allowed_user_ids[key] = None

    @property
    def is_configured(self) -> bool:
        return len(self.accounts) > 0

    def get_token(self, account: str) -> str | None:
        return self.accounts.get(account.lower())

    def get_level(self, account: str) -> str:
        return self.levels.get(account.lower(), "basic")

    def get_allowed_chats(self, account: str) -> set[str] | None:
        return self.allowed_chats.get(account.lower())

    def get_allowed_user_ids(self, account: str) -> set[int] | None:
        return self.allowed_user_ids.get(account.lower())

    def list_accounts(self) -> list[str]:
        return list(self.accounts.keys())

    def get_service(self, account: str) -> TelegramService | None:
        """Get a TelegramService instance for the given account."""
        token = self.get_token(account)
        if token:
            return TelegramService(token)
        return None


def _level_at_least(required: str, actual: str) -> bool:
    """Check if actual level meets the required minimum."""
    return LEVEL_ORDER.get(actual, 0) >= LEVEL_ORDER.get(required, 0)


def _get_service_and_account(config: TelegramConfig) -> tuple[TelegramService | None, str | None, dict | None]:
    """Get service and account from context, or return error dict."""
    account = account_override.get()
    if account is None:
        return None, None, {"error": "No account specified in URL path."}
    service = config.get_service(account)
    if service is None:
        return None, None, {"error": f"Unknown account: {account}."}
    return service, account, None


def _check_level(config: TelegramConfig, account: str, required: str) -> dict | None:
    """Check if account has required level, return error dict if not."""
    level = config.get_level(account)
    if not _level_at_least(required, level):
        return {"error": f"This tool requires '{required}' level or higher."}
    return None


def _check_chats(config: TelegramConfig, account: str, chat_ids: tuple[str, ...]) -> dict | None:
    """Check if chats are allowed, return error dict if not."""
    allowed = config.get_allowed_chats(account)
    if allowed is not None:
        for cid in chat_ids:
            if str(cid) not in allowed:
                return {"error": f"Chat {cid} is not in the allowed list for this account."}
    return None


def register_telegram_tools(mcp, config: TelegramConfig):
    """Register Telegram MCP tools based on configured level."""

    # Determine the maximum level across all accounts so we know which tools
    # to register. The level check at call time will reject calls that exceed
    # the per-account level.
    max_level = "basic"
    for account in config.list_accounts():
        level = config.get_level(account)
        if LEVEL_ORDER[level] > LEVEL_ORDER[max_level]:
            max_level = level

    # --- basic level tools ---

    @mcp.tool()
    async def telegram_get_me() -> dict:
        """Get information about this Telegram bot account."""
        service, account, err = _get_service_and_account(config)
        if err:
            return err
        result = await service.get_me()
        return result.to_dict()

    @mcp.tool()
    async def telegram_send_message(
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> dict:
        """Send a text message via this Telegram bot.

        Args:
            chat_id: Target chat ID (user ID, group ID, or @channel_username).
            text: Message text to send (max 4096 characters).
            parse_mode: Optional formatting: "HTML", "Markdown", or "MarkdownV2".
        """
        service, account, err = _get_service_and_account(config)
        if err:
            return err
        if err := _check_chats(config, account, (chat_id,)):
            return err
        result = await service.send_message(chat_id, text, parse_mode)
        return result.to_dict()

    @mcp.tool()
    async def telegram_get_updates(
        limit: int = 10,
        auto_acknowledge: bool = True,
    ) -> dict:
        """Get recent incoming updates (messages, etc.) for this Telegram bot.

        Args:
            limit: Maximum number of updates to retrieve (1-100, default 10).
            auto_acknowledge: If True (default), automatically acknowledge updates so they won't be returned again on subsequent calls.
        """
        service, account, err = _get_service_and_account(config)
        if err:
            return err
        filter_uids = config.get_allowed_user_ids(account)
        if auto_acknowledge:
            result = await service.get_updates_with_auto_ack(limit=limit, filter_user_ids=filter_uids)
        else:
            result = await service.get_updates(limit=limit)
            # Still apply user filter even without auto-ack
            if filter_uids is not None and result.ok:
                from telegram_service import _update_user_id
                updates = result.data.get("result", [])
                result.data["result"] = [u for u in updates if _update_user_id(u) in filter_uids]
        return result.to_dict()

    # --- standard level tools ---

    if _level_at_least("standard", max_level):

        @mcp.tool()
        async def telegram_forward_message(
            chat_id: str,
            from_chat_id: str,
            message_id: int,
        ) -> dict:
            """Forward a message from one chat to another.

            Args:
                chat_id: Target chat ID to forward the message to.
                from_chat_id: Chat ID where the original message was sent.
                message_id: Message ID of the message to forward.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "standard"):
                return err
            if err := _check_chats(config, account, (chat_id, from_chat_id)):
                return err
            result = await service.forward_message(chat_id, from_chat_id, message_id)
            return result.to_dict()

        @mcp.tool()
        async def telegram_edit_message_text(
            chat_id: str,
            message_id: int,
            text: str,
            parse_mode: Optional[str] = None,
        ) -> dict:
            """Edit the text of a previously sent message.

            Args:
                chat_id: Chat ID where the message was sent.
                message_id: ID of the message to edit.
                text: New text for the message.
                parse_mode: Optional formatting: "HTML", "Markdown", or "MarkdownV2".
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "standard"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.edit_message_text(chat_id, message_id, text, parse_mode)
            return result.to_dict()

        @mcp.tool()
        async def telegram_delete_message(
            chat_id: str,
            message_id: int,
        ) -> dict:
            """Delete a message sent by the bot or in a group where the bot is admin.

            Args:
                chat_id: Chat ID where the message was sent.
                message_id: ID of the message to delete.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "standard"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.delete_message(chat_id, message_id)
            return result.to_dict()

        @mcp.tool()
        async def telegram_send_photo(
            chat_id: str,
            photo: str,
            caption: Optional[str] = None,
            parse_mode: Optional[str] = None,
        ) -> dict:
            """Send a photo via this Telegram bot.

            Args:
                chat_id: Target chat ID.
                photo: Photo URL or file_id from a previous upload.
                caption: Optional caption for the photo (max 1024 characters).
                parse_mode: Optional formatting for caption: "HTML", "Markdown", or "MarkdownV2".
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "standard"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_photo(chat_id, photo, caption, parse_mode)
            return result.to_dict()

        @mcp.tool()
        async def telegram_send_document(
            chat_id: str,
            document: str,
            caption: Optional[str] = None,
            parse_mode: Optional[str] = None,
        ) -> dict:
            """Send a document/file via this Telegram bot.

            Args:
                chat_id: Target chat ID.
                document: Document URL or file_id from a previous upload.
                caption: Optional caption for the document (max 1024 characters).
                parse_mode: Optional formatting for caption: "HTML", "Markdown", or "MarkdownV2".
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "standard"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_document(chat_id, document, caption, parse_mode)
            return result.to_dict()

    # --- advanced level tools ---

    if _level_at_least("advanced", max_level):

        @mcp.tool()
        async def telegram_get_chat(chat_id: str) -> dict:
            """Get detailed information about a chat (group, channel, or private).

            Args:
                chat_id: Chat ID or @channel_username.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "advanced"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.get_chat(chat_id)
            return result.to_dict()

        @mcp.tool()
        async def telegram_send_location(
            chat_id: str,
            latitude: float,
            longitude: float,
        ) -> dict:
            """Send a location point on the map.

            Args:
                chat_id: Target chat ID.
                latitude: Latitude of the location (-90 to 90).
                longitude: Longitude of the location (-180 to 180).
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "advanced"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_location(chat_id, latitude, longitude)
            return result.to_dict()

        @mcp.tool()
        async def telegram_send_poll(
            chat_id: str,
            question: str,
            options: list[str],
            is_anonymous: bool = True,
        ) -> dict:
            """Send a poll to a chat.

            Args:
                chat_id: Target chat ID.
                question: Poll question (1-300 characters).
                options: List of answer options (2-10 strings, each 1-100 characters).
                is_anonymous: Whether the poll is anonymous (default True).
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "advanced"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_poll(chat_id, question, options, is_anonymous)
            return result.to_dict()

        @mcp.tool()
        async def telegram_pin_chat_message(
            chat_id: str,
            message_id: int,
            disable_notification: bool = False,
        ) -> dict:
            """Pin a message in a chat. The bot must be an admin with pin_messages rights.

            Args:
                chat_id: Chat ID where the message is.
                message_id: ID of the message to pin.
                disable_notification: If True, no notification is sent to chat members.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "advanced"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.pin_chat_message(chat_id, message_id, disable_notification)
            return result.to_dict()

        @mcp.tool()
        async def telegram_unpin_chat_message(
            chat_id: str,
            message_id: Optional[int] = None,
        ) -> dict:
            """Unpin a message in a chat. The bot must be an admin with pin_messages rights.

            Args:
                chat_id: Chat ID where the message is pinned.
                message_id: ID of the message to unpin. If not specified, unpins the most recent pinned message.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "advanced"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.unpin_chat_message(chat_id, message_id)
            return result.to_dict()

        @mcp.tool()
        async def telegram_get_chat_member_count(chat_id: str) -> dict:
            """Get the number of members in a chat.

            Args:
                chat_id: Chat ID or @channel_username.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "advanced"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.get_chat_member_count(chat_id)
            return result.to_dict()

        @mcp.tool()
        async def telegram_get_chat_member(
            chat_id: str, user_id: int
        ) -> dict:
            """Get information about a member of a chat.

            Args:
                chat_id: Chat ID or @channel_username.
                user_id: Unique identifier of the target user.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "advanced"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.get_chat_member(chat_id, user_id)
            return result.to_dict()

    # --- full level tools ---

    if _level_at_least("full", max_level):

        @mcp.tool()
        async def telegram_send_audio(
            chat_id: str,
            audio: str,
            caption: Optional[str] = None,
            parse_mode: Optional[str] = None,
        ) -> dict:
            """Send an audio file (mp3, etc.) via this Telegram bot.

            Args:
                chat_id: Target chat ID.
                audio: Audio URL or file_id from a previous upload.
                caption: Optional caption (max 1024 characters).
                parse_mode: Optional formatting for caption.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "full"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_audio(chat_id, audio, caption, parse_mode)
            return result.to_dict()

        @mcp.tool()
        async def telegram_send_video(
            chat_id: str,
            video: str,
            caption: Optional[str] = None,
            parse_mode: Optional[str] = None,
        ) -> dict:
            """Send a video file via this Telegram bot.

            Args:
                chat_id: Target chat ID.
                video: Video URL or file_id from a previous upload.
                caption: Optional caption (max 1024 characters).
                parse_mode: Optional formatting for caption.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "full"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_video(chat_id, video, caption, parse_mode)
            return result.to_dict()

        @mcp.tool()
        async def telegram_send_voice(
            chat_id: str,
            voice: str,
            caption: Optional[str] = None,
            parse_mode: Optional[str] = None,
        ) -> dict:
            """Send a voice message (OGG/OPUS) via this Telegram bot.

            Args:
                chat_id: Target chat ID.
                voice: Voice message URL or file_id from a previous upload.
                caption: Optional caption (max 1024 characters).
                parse_mode: Optional formatting for caption.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "full"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_voice(chat_id, voice, caption, parse_mode)
            return result.to_dict()

        @mcp.tool()
        async def telegram_send_sticker(
            chat_id: str,
            sticker: str,
        ) -> dict:
            """Send a sticker via this Telegram bot.

            Args:
                chat_id: Target chat ID.
                sticker: Sticker URL, file_id, or sticker set name.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "full"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_sticker(chat_id, sticker)
            return result.to_dict()

        @mcp.tool()
        async def telegram_copy_message(
            chat_id: str,
            from_chat_id: str,
            message_id: int,
        ) -> dict:
            """Copy a message from one chat to another (without "Forwarded from" header).

            Args:
                chat_id: Target chat ID.
                from_chat_id: Chat ID where the original message was sent.
                message_id: Message ID of the message to copy.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "full"):
                return err
            if err := _check_chats(config, account, (chat_id, from_chat_id)):
                return err
            result = await service.copy_message(chat_id, from_chat_id, message_id)
            return result.to_dict()

        @mcp.tool()
        async def telegram_set_message_reaction(
            chat_id: str,
            message_id: int,
            reaction: Optional[str] = None,
        ) -> dict:
            """Set a reaction on a message. Pass no reaction to remove.

            Args:
                chat_id: Chat ID where the message is.
                message_id: ID of the message to react to.
                reaction: Emoji reaction (e.g. "👍", "❤", "🔥"). Omit to remove reaction.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "full"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.set_message_reaction(chat_id, message_id, reaction)
            return result.to_dict()

        @mcp.tool()
        async def telegram_leave_chat(chat_id: str) -> dict:
            """Leave a group, supergroup, or channel.

            Args:
                chat_id: Chat ID to leave.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "full"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.leave_chat(chat_id)
            return result.to_dict()

        @mcp.tool()
        async def telegram_send_contact(
            chat_id: str,
            phone_number: str,
            first_name: str,
            last_name: Optional[str] = None,
        ) -> dict:
            """Send a phone contact.

            Args:
                chat_id: Target chat ID.
                phone_number: Contact's phone number.
                first_name: Contact's first name.
                last_name: Optional contact's last name.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "full"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_contact(chat_id, phone_number, first_name, last_name)
            return result.to_dict()

        @mcp.tool()
        async def telegram_send_venue(
            chat_id: str,
            latitude: float,
            longitude: float,
            title: str,
            address: str,
        ) -> dict:
            """Send a venue (location with name and address).

            Args:
                chat_id: Target chat ID.
                latitude: Latitude of the venue.
                longitude: Longitude of the venue.
                title: Name of the venue.
                address: Address of the venue.
            """
            service, account, err = _get_service_and_account(config)
            if err:
                return err
            if err := _check_level(config, account, "full"):
                return err
            if err := _check_chats(config, account, (chat_id,)):
                return err
            result = await service.send_venue(chat_id, latitude, longitude, title, address)
            return result.to_dict()
