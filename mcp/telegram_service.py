"""Shared Telegram service layer used by both MCP tools and REST API."""

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("connect.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org"


@dataclass
class ServiceResult:
    """Result from a service operation."""
    ok: bool
    data: dict
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for JSON responses."""
        if self.ok:
            return self.data
        return {"error": self.error}


class TelegramService:
    """Telegram Bot API service layer."""

    def __init__(self, token: str):
        self.token = token

    async def _api_call(self, method: str, params: dict | None = None) -> ServiceResult:
        """Make a call to the Telegram Bot API."""
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/{method}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if params:
                    response = await client.post(url, json=params)
                else:
                    response = await client.get(url)
                response.raise_for_status()
                return ServiceResult(ok=True, data=response.json())
        except httpx.HTTPStatusError as e:
            return ServiceResult(ok=False, data={}, error=f"Telegram API error: {e.response.status_code}")
        except httpx.RequestError as e:
            return ServiceResult(ok=False, data={}, error=f"Request failed: {str(e)}")

    # --- Basic operations ---

    async def get_me(self) -> ServiceResult:
        """Get information about this Telegram bot account."""
        return await self._api_call("getMe")

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> ServiceResult:
        """Send a text message."""
        params = {"chat_id": chat_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        return await self._api_call("sendMessage", params)

    async def get_updates(
        self,
        limit: int = 10,
        offset: Optional[int] = None,
        timeout: int = 0,
    ) -> ServiceResult:
        """Get incoming updates."""
        params: dict = {"limit": min(max(limit, 1), 100), "timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        return await self._api_call("getUpdates", params)

    async def get_updates_with_auto_ack(
        self,
        limit: int = 10,
        filter_user_ids: Optional[set[int]] = None,
    ) -> ServiceResult:
        """Get incoming updates and auto-acknowledge them.

        Args:
            limit: Maximum number of updates to retrieve.
            filter_user_ids: If provided, only return updates from these user IDs.

        Returns:
            ServiceResult with filtered (if applicable) and acknowledged updates.
        """
        result = await self.get_updates(limit=limit)
        if not result.ok:
            return result

        updates = result.data.get("result", [])

        # Filter by user IDs if specified
        if filter_user_ids is not None and updates:
            before = len(updates)
            updates = [u for u in updates if _update_user_id(u) in filter_user_ids]
            filtered = before - len(updates)
            if filtered:
                logger.info("Filtered %d update(s) from non-allowed users", filtered)
            result.data["result"] = updates

        # Auto-acknowledge
        if updates:
            max_update_id = max(u["update_id"] for u in updates)
            await self.get_updates(limit=1, offset=max_update_id + 1)

        return result

    # --- Standard operations ---

    async def forward_message(
        self,
        chat_id: str,
        from_chat_id: str,
        message_id: int,
    ) -> ServiceResult:
        """Forward a message from one chat to another."""
        params = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
        }
        return await self._api_call("forwardMessage", params)

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> ServiceResult:
        """Edit the text of a previously sent message."""
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        return await self._api_call("editMessageText", params)

    async def delete_message(self, chat_id: str, message_id: int) -> ServiceResult:
        """Delete a message."""
        return await self._api_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    async def send_photo(
        self,
        chat_id: str,
        photo: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> ServiceResult:
        """Send a photo."""
        params = {"chat_id": chat_id, "photo": photo}
        if caption:
            params["caption"] = caption
        if parse_mode:
            params["parse_mode"] = parse_mode
        return await self._api_call("sendPhoto", params)

    async def send_document(
        self,
        chat_id: str,
        document: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> ServiceResult:
        """Send a document/file."""
        params = {"chat_id": chat_id, "document": document}
        if caption:
            params["caption"] = caption
        if parse_mode:
            params["parse_mode"] = parse_mode
        return await self._api_call("sendDocument", params)

    # --- Advanced operations ---

    async def get_chat(self, chat_id: str) -> ServiceResult:
        """Get detailed information about a chat."""
        return await self._api_call("getChat", {"chat_id": chat_id})

    async def send_location(
        self,
        chat_id: str,
        latitude: float,
        longitude: float,
    ) -> ServiceResult:
        """Send a location."""
        params = {"chat_id": chat_id, "latitude": latitude, "longitude": longitude}
        return await self._api_call("sendLocation", params)

    async def send_poll(
        self,
        chat_id: str,
        question: str,
        options: list[str],
        is_anonymous: bool = True,
    ) -> ServiceResult:
        """Send a poll."""
        params = {
            "chat_id": chat_id,
            "question": question,
            "options": [{"text": opt} for opt in options],
            "is_anonymous": is_anonymous,
        }
        return await self._api_call("sendPoll", params)

    async def pin_chat_message(
        self,
        chat_id: str,
        message_id: int,
        disable_notification: bool = False,
    ) -> ServiceResult:
        """Pin a message in a chat."""
        params = {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": disable_notification,
        }
        return await self._api_call("pinChatMessage", params)

    async def unpin_chat_message(
        self,
        chat_id: str,
        message_id: Optional[int] = None,
    ) -> ServiceResult:
        """Unpin a message in a chat."""
        params: dict = {"chat_id": chat_id}
        if message_id is not None:
            params["message_id"] = message_id
        return await self._api_call("unpinChatMessage", params)

    async def get_chat_member_count(self, chat_id: str) -> ServiceResult:
        """Get the number of members in a chat."""
        return await self._api_call("getChatMemberCount", {"chat_id": chat_id})

    async def get_chat_member(self, chat_id: str, user_id: int) -> ServiceResult:
        """Get information about a member of a chat."""
        return await self._api_call("getChatMember", {"chat_id": chat_id, "user_id": user_id})

    # --- Full operations ---

    async def send_audio(
        self,
        chat_id: str,
        audio: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> ServiceResult:
        """Send an audio file."""
        params = {"chat_id": chat_id, "audio": audio}
        if caption:
            params["caption"] = caption
        if parse_mode:
            params["parse_mode"] = parse_mode
        return await self._api_call("sendAudio", params)

    async def send_video(
        self,
        chat_id: str,
        video: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> ServiceResult:
        """Send a video file."""
        params = {"chat_id": chat_id, "video": video}
        if caption:
            params["caption"] = caption
        if parse_mode:
            params["parse_mode"] = parse_mode
        return await self._api_call("sendVideo", params)

    async def send_voice(
        self,
        chat_id: str,
        voice: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> ServiceResult:
        """Send a voice message."""
        params = {"chat_id": chat_id, "voice": voice}
        if caption:
            params["caption"] = caption
        if parse_mode:
            params["parse_mode"] = parse_mode
        return await self._api_call("sendVoice", params)

    async def send_sticker(self, chat_id: str, sticker: str) -> ServiceResult:
        """Send a sticker."""
        return await self._api_call("sendSticker", {"chat_id": chat_id, "sticker": sticker})

    async def copy_message(
        self,
        chat_id: str,
        from_chat_id: str,
        message_id: int,
    ) -> ServiceResult:
        """Copy a message from one chat to another."""
        params = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
        }
        return await self._api_call("copyMessage", params)

    async def set_message_reaction(
        self,
        chat_id: str,
        message_id: int,
        reaction: Optional[str] = None,
    ) -> ServiceResult:
        """Set a reaction on a message."""
        params: dict = {"chat_id": chat_id, "message_id": message_id}
        if reaction:
            params["reaction"] = [{"type": "emoji", "emoji": reaction}]
        else:
            params["reaction"] = []
        return await self._api_call("setMessageReaction", params)

    async def leave_chat(self, chat_id: str) -> ServiceResult:
        """Leave a group, supergroup, or channel."""
        return await self._api_call("leaveChat", {"chat_id": chat_id})

    async def send_contact(
        self,
        chat_id: str,
        phone_number: str,
        first_name: str,
        last_name: Optional[str] = None,
    ) -> ServiceResult:
        """Send a phone contact."""
        params = {
            "chat_id": chat_id,
            "phone_number": phone_number,
            "first_name": first_name,
        }
        if last_name:
            params["last_name"] = last_name
        return await self._api_call("sendContact", params)

    async def send_venue(
        self,
        chat_id: str,
        latitude: float,
        longitude: float,
        title: str,
        address: str,
    ) -> ServiceResult:
        """Send a venue."""
        params = {
            "chat_id": chat_id,
            "latitude": latitude,
            "longitude": longitude,
            "title": title,
            "address": address,
        }
        return await self._api_call("sendVenue", params)


def _update_user_id(update: dict) -> int | None:
    """Extract the user ID from a Telegram update object."""
    for key in ("message", "edited_message", "channel_post", "edited_channel_post",
                "callback_query", "inline_query"):
        obj = update.get(key)
        if obj and "from" in obj:
            return obj["from"].get("id")
    return None
