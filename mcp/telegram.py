import contextvars
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("connect.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org"

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


def _level_at_least(required: str, actual: str) -> bool:
    """Check if actual level meets the required minimum."""
    return LEVEL_ORDER.get(actual, 0) >= LEVEL_ORDER.get(required, 0)


async def telegram_api_call(
    token: str, method: str, params: dict | None = None
) -> dict:
    """Make a call to the Telegram Bot API."""
    url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        if params:
            response = await client.post(url, json=params)
        else:
            response = await client.get(url)
        response.raise_for_status()
        return response.json()


def _update_user_id(update: dict) -> int | None:
    """Extract the user ID from a Telegram update object."""
    for key in ("message", "edited_message", "channel_post", "edited_channel_post",
                "callback_query", "inline_query"):
        obj = update.get(key)
        if obj and "from" in obj:
            return obj["from"].get("id")
    return None


async def _call(config: TelegramConfig, method: str, params: dict | None = None,
                *, min_level: str = "basic", check_chats: tuple[str, ...] = ()) -> dict:
    """Resolve account, enforce level/chat restrictions, and call the Telegram API."""
    account = account_override.get()
    if account is None:
        return {"error": "No account specified in URL path."}
    token = config.get_token(account)
    if not token:
        return {"error": f"Unknown account: {account}."}
    if min_level != "basic":
        level = config.get_level(account)
        if not _level_at_least(min_level, level):
            return {"error": f"This tool requires '{min_level}' level or higher."}
    if check_chats:
        allowed = config.get_allowed_chats(account)
        if allowed is not None:
            for cid in check_chats:
                if str(cid) not in allowed:
                    return {"error": f"Chat {cid} is not in the allowed list for this account."}
    try:
        return await telegram_api_call(token, method, params)
    except httpx.HTTPStatusError as e:
        return {"error": f"Telegram API error: {e.response.status_code}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}


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
        return await _call(config, "getMe")

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
        params = {"chat_id": chat_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        return await _call(config, "sendMessage", params, check_chats=(chat_id,))

    @mcp.tool()
    async def telegram_get_updates(
        limit: int = 10,
        offset: Optional[int] = None,
    ) -> dict:
        """Get recent incoming updates (messages, etc.) for this Telegram bot.

        Args:
            limit: Maximum number of updates to retrieve (1-100, default 10).
            offset: Update ID offset. Pass the highest update_id + 1 from previous results to acknowledge older updates.
        """
        params: dict = {"limit": min(max(limit, 1), 100), "timeout": 0}
        if offset is not None:
            params["offset"] = offset
        result = await _call(config, "getUpdates", params)
        if "error" in result:
            return result
        account = account_override.get()
        allowed_uids = config.get_allowed_user_ids(account) if account else None
        if allowed_uids is not None and result.get("ok") and result.get("result"):
            before = len(result["result"])
            result["result"] = [
                u for u in result["result"]
                if _update_user_id(u) in allowed_uids
            ]
            filtered = before - len(result["result"])
            if filtered:
                logger.info("Filtered %d update(s) from non-allowed users for '%s'", filtered, account)
        return result

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
            params = {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
            }
            return await _call(config, "forwardMessage", params,
                               min_level="standard", check_chats=(chat_id, from_chat_id))

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
            params = {"chat_id": chat_id, "message_id": message_id, "text": text}
            if parse_mode:
                params["parse_mode"] = parse_mode
            return await _call(config, "editMessageText", params,
                               min_level="standard", check_chats=(chat_id,))

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
            params = {"chat_id": chat_id, "message_id": message_id}
            return await _call(config, "deleteMessage", params,
                               min_level="standard", check_chats=(chat_id,))

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
            params = {"chat_id": chat_id, "photo": photo}
            if caption:
                params["caption"] = caption
            if parse_mode:
                params["parse_mode"] = parse_mode
            return await _call(config, "sendPhoto", params,
                               min_level="standard", check_chats=(chat_id,))

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
            params = {"chat_id": chat_id, "document": document}
            if caption:
                params["caption"] = caption
            if parse_mode:
                params["parse_mode"] = parse_mode
            return await _call(config, "sendDocument", params,
                               min_level="standard", check_chats=(chat_id,))

    # --- advanced level tools ---

    if _level_at_least("advanced", max_level):

        @mcp.tool()
        async def telegram_get_chat(chat_id: str) -> dict:
            """Get detailed information about a chat (group, channel, or private).

            Args:
                chat_id: Chat ID or @channel_username.
            """
            return await _call(config, "getChat", {"chat_id": chat_id},
                               min_level="advanced", check_chats=(chat_id,))

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
            params = {
                "chat_id": chat_id,
                "latitude": latitude,
                "longitude": longitude,
            }
            return await _call(config, "sendLocation", params,
                               min_level="advanced", check_chats=(chat_id,))

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
            params = {
                "chat_id": chat_id,
                "question": question,
                "options": [{"text": opt} for opt in options],
                "is_anonymous": is_anonymous,
            }
            return await _call(config, "sendPoll", params,
                               min_level="advanced", check_chats=(chat_id,))

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
            params = {
                "chat_id": chat_id,
                "message_id": message_id,
                "disable_notification": disable_notification,
            }
            return await _call(config, "pinChatMessage", params,
                               min_level="advanced", check_chats=(chat_id,))

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
            params: dict = {"chat_id": chat_id}
            if message_id is not None:
                params["message_id"] = message_id
            return await _call(config, "unpinChatMessage", params,
                               min_level="advanced", check_chats=(chat_id,))

        @mcp.tool()
        async def telegram_get_chat_member_count(chat_id: str) -> dict:
            """Get the number of members in a chat.

            Args:
                chat_id: Chat ID or @channel_username.
            """
            return await _call(config, "getChatMemberCount", {"chat_id": chat_id},
                               min_level="advanced", check_chats=(chat_id,))

        @mcp.tool()
        async def telegram_get_chat_member(
            chat_id: str, user_id: int
        ) -> dict:
            """Get information about a member of a chat.

            Args:
                chat_id: Chat ID or @channel_username.
                user_id: Unique identifier of the target user.
            """
            return await _call(config, "getChatMember",
                               {"chat_id": chat_id, "user_id": user_id},
                               min_level="advanced", check_chats=(chat_id,))

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
            params = {"chat_id": chat_id, "audio": audio}
            if caption:
                params["caption"] = caption
            if parse_mode:
                params["parse_mode"] = parse_mode
            return await _call(config, "sendAudio", params,
                               min_level="full", check_chats=(chat_id,))

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
            params = {"chat_id": chat_id, "video": video}
            if caption:
                params["caption"] = caption
            if parse_mode:
                params["parse_mode"] = parse_mode
            return await _call(config, "sendVideo", params,
                               min_level="full", check_chats=(chat_id,))

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
            params = {"chat_id": chat_id, "voice": voice}
            if caption:
                params["caption"] = caption
            if parse_mode:
                params["parse_mode"] = parse_mode
            return await _call(config, "sendVoice", params,
                               min_level="full", check_chats=(chat_id,))

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
            return await _call(config, "sendSticker",
                               {"chat_id": chat_id, "sticker": sticker},
                               min_level="full", check_chats=(chat_id,))

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
            params = {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": message_id,
            }
            return await _call(config, "copyMessage", params,
                               min_level="full", check_chats=(chat_id, from_chat_id))

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
            params: dict = {"chat_id": chat_id, "message_id": message_id}
            if reaction:
                params["reaction"] = [{"type": "emoji", "emoji": reaction}]
            else:
                params["reaction"] = []
            return await _call(config, "setMessageReaction", params,
                               min_level="full", check_chats=(chat_id,))

        @mcp.tool()
        async def telegram_leave_chat(chat_id: str) -> dict:
            """Leave a group, supergroup, or channel.

            Args:
                chat_id: Chat ID to leave.
            """
            return await _call(config, "leaveChat", {"chat_id": chat_id},
                               min_level="full", check_chats=(chat_id,))

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
            params = {
                "chat_id": chat_id,
                "phone_number": phone_number,
                "first_name": first_name,
            }
            if last_name:
                params["last_name"] = last_name
            return await _call(config, "sendContact", params,
                               min_level="full", check_chats=(chat_id,))

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
            params = {
                "chat_id": chat_id,
                "latitude": latitude,
                "longitude": longitude,
                "title": title,
                "address": address,
            }
            return await _call(config, "sendVenue", params,
                               min_level="full", check_chats=(chat_id,))
