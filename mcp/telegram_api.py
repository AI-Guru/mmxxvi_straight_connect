"""REST API for Telegram operations."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from telegram_service import TelegramService
from telegram import TelegramConfig


class SendMessageRequest(BaseModel):
    text: str
    parse_mode: Optional[str] = None


class ForwardMessageRequest(BaseModel):
    from_chat_id: str
    message_id: int


class EditMessageRequest(BaseModel):
    message_id: int
    text: str
    parse_mode: Optional[str] = None


class DeleteMessageRequest(BaseModel):
    message_id: int


class SendPhotoRequest(BaseModel):
    photo: str
    caption: Optional[str] = None
    parse_mode: Optional[str] = None


class SendDocumentRequest(BaseModel):
    document: str
    caption: Optional[str] = None
    parse_mode: Optional[str] = None


class SendLocationRequest(BaseModel):
    latitude: float
    longitude: float


class SendPollRequest(BaseModel):
    question: str
    options: list[str]
    is_anonymous: bool = True


class PinMessageRequest(BaseModel):
    message_id: int
    disable_notification: bool = False


class UnpinMessageRequest(BaseModel):
    message_id: Optional[int] = None


class SendAudioRequest(BaseModel):
    audio: str
    caption: Optional[str] = None
    parse_mode: Optional[str] = None


class SendVideoRequest(BaseModel):
    video: str
    caption: Optional[str] = None
    parse_mode: Optional[str] = None


class SendVoiceRequest(BaseModel):
    voice: str
    caption: Optional[str] = None
    parse_mode: Optional[str] = None


class SendStickerRequest(BaseModel):
    sticker: str


class CopyMessageRequest(BaseModel):
    from_chat_id: str
    message_id: int


class SetReactionRequest(BaseModel):
    message_id: int
    reaction: Optional[str] = None


class SendContactRequest(BaseModel):
    phone_number: str
    first_name: str
    last_name: Optional[str] = None


class SendVenueRequest(BaseModel):
    latitude: float
    longitude: float
    title: str
    address: str


def create_telegram_router(config: TelegramConfig) -> APIRouter:
    """Create a FastAPI router with Telegram endpoints."""

    router = APIRouter(prefix="/api/telegram", tags=["telegram"])

    def get_service(account: str) -> TelegramService:
        """Get TelegramService for an account or raise 404."""
        token = config.get_token(account)
        if not token:
            raise HTTPException(status_code=404, detail=f"Unknown account: {account}")
        return TelegramService(token)

    def check_level(account: str, required: str) -> None:
        """Check if account has required level or raise 403."""
        level = config.get_level(account)
        level_order = {"basic": 0, "standard": 1, "advanced": 2, "full": 3}
        if level_order.get(level, 0) < level_order.get(required, 0):
            raise HTTPException(
                status_code=403,
                detail=f"This endpoint requires '{required}' level or higher."
            )

    def check_chat(account: str, chat_id: str) -> None:
        """Check if chat is allowed for account or raise 403."""
        allowed = config.get_allowed_chats(account)
        if allowed is not None and str(chat_id) not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Chat {chat_id} is not in the allowed list for this account."
            )

    # --- Basic endpoints ---

    @router.get("/{account}/me")
    async def get_me(account: str):
        """Get information about this Telegram bot account."""
        service = get_service(account)
        result = await service.get_me()
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/messages")
    async def send_message(account: str, chat_id: str, request: SendMessageRequest):
        """Send a text message to a chat."""
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_message(chat_id, request.text, request.parse_mode)
        return result.to_dict()

    @router.get("/{account}/updates")
    async def get_updates(account: str, limit: int = 10, auto_acknowledge: bool = True):
        """Get recent incoming updates (messages, etc.) for this Telegram bot."""
        service = get_service(account)
        filter_uids = config.get_allowed_user_ids(account)
        if auto_acknowledge:
            result = await service.get_updates_with_auto_ack(limit=limit, filter_user_ids=filter_uids)
        else:
            result = await service.get_updates(limit=limit)
            # Still apply user filter even without auto-ack
            if filter_uids is not None and result.ok:
                updates = result.data.get("result", [])
                from telegram_service import _update_user_id
                result.data["result"] = [u for u in updates if _update_user_id(u) in filter_uids]
        return result.to_dict()

    # --- Standard endpoints ---

    @router.post("/{account}/chats/{chat_id}/forward")
    async def forward_message(account: str, chat_id: str, request: ForwardMessageRequest):
        """Forward a message from one chat to another."""
        check_level(account, "standard")
        service = get_service(account)
        check_chat(account, chat_id)
        check_chat(account, request.from_chat_id)
        result = await service.forward_message(chat_id, request.from_chat_id, request.message_id)
        return result.to_dict()

    @router.put("/{account}/chats/{chat_id}/messages")
    async def edit_message(account: str, chat_id: str, request: EditMessageRequest):
        """Edit the text of a previously sent message."""
        check_level(account, "standard")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.edit_message_text(chat_id, request.message_id, request.text, request.parse_mode)
        return result.to_dict()

    @router.delete("/{account}/chats/{chat_id}/messages/{message_id}")
    async def delete_message(account: str, chat_id: str, message_id: int):
        """Delete a message."""
        check_level(account, "standard")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.delete_message(chat_id, message_id)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/photos")
    async def send_photo(account: str, chat_id: str, request: SendPhotoRequest):
        """Send a photo to a chat."""
        check_level(account, "standard")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_photo(chat_id, request.photo, request.caption, request.parse_mode)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/documents")
    async def send_document(account: str, chat_id: str, request: SendDocumentRequest):
        """Send a document to a chat."""
        check_level(account, "standard")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_document(chat_id, request.document, request.caption, request.parse_mode)
        return result.to_dict()

    # --- Advanced endpoints ---

    @router.get("/{account}/chats/{chat_id}")
    async def get_chat(account: str, chat_id: str):
        """Get detailed information about a chat."""
        check_level(account, "advanced")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.get_chat(chat_id)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/location")
    async def send_location(account: str, chat_id: str, request: SendLocationRequest):
        """Send a location to a chat."""
        check_level(account, "advanced")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_location(chat_id, request.latitude, request.longitude)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/polls")
    async def send_poll(account: str, chat_id: str, request: SendPollRequest):
        """Send a poll to a chat."""
        check_level(account, "advanced")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_poll(chat_id, request.question, request.options, request.is_anonymous)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/pin")
    async def pin_message(account: str, chat_id: str, request: PinMessageRequest):
        """Pin a message in a chat."""
        check_level(account, "advanced")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.pin_chat_message(chat_id, request.message_id, request.disable_notification)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/unpin")
    async def unpin_message(account: str, chat_id: str, request: UnpinMessageRequest):
        """Unpin a message in a chat."""
        check_level(account, "advanced")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.unpin_chat_message(chat_id, request.message_id)
        return result.to_dict()

    @router.get("/{account}/chats/{chat_id}/member-count")
    async def get_chat_member_count(account: str, chat_id: str):
        """Get the number of members in a chat."""
        check_level(account, "advanced")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.get_chat_member_count(chat_id)
        return result.to_dict()

    @router.get("/{account}/chats/{chat_id}/members/{user_id}")
    async def get_chat_member(account: str, chat_id: str, user_id: int):
        """Get information about a member of a chat."""
        check_level(account, "advanced")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.get_chat_member(chat_id, user_id)
        return result.to_dict()

    # --- Full endpoints ---

    @router.post("/{account}/chats/{chat_id}/audio")
    async def send_audio(account: str, chat_id: str, request: SendAudioRequest):
        """Send an audio file to a chat."""
        check_level(account, "full")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_audio(chat_id, request.audio, request.caption, request.parse_mode)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/video")
    async def send_video(account: str, chat_id: str, request: SendVideoRequest):
        """Send a video to a chat."""
        check_level(account, "full")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_video(chat_id, request.video, request.caption, request.parse_mode)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/voice")
    async def send_voice(account: str, chat_id: str, request: SendVoiceRequest):
        """Send a voice message to a chat."""
        check_level(account, "full")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_voice(chat_id, request.voice, request.caption, request.parse_mode)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/stickers")
    async def send_sticker(account: str, chat_id: str, request: SendStickerRequest):
        """Send a sticker to a chat."""
        check_level(account, "full")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_sticker(chat_id, request.sticker)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/copy")
    async def copy_message(account: str, chat_id: str, request: CopyMessageRequest):
        """Copy a message from one chat to another."""
        check_level(account, "full")
        service = get_service(account)
        check_chat(account, chat_id)
        check_chat(account, request.from_chat_id)
        result = await service.copy_message(chat_id, request.from_chat_id, request.message_id)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/reactions")
    async def set_reaction(account: str, chat_id: str, request: SetReactionRequest):
        """Set a reaction on a message."""
        check_level(account, "full")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.set_message_reaction(chat_id, request.message_id, request.reaction)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/leave")
    async def leave_chat(account: str, chat_id: str):
        """Leave a group, supergroup, or channel."""
        check_level(account, "full")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.leave_chat(chat_id)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/contacts")
    async def send_contact(account: str, chat_id: str, request: SendContactRequest):
        """Send a phone contact to a chat."""
        check_level(account, "full")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_contact(chat_id, request.phone_number, request.first_name, request.last_name)
        return result.to_dict()

    @router.post("/{account}/chats/{chat_id}/venues")
    async def send_venue(account: str, chat_id: str, request: SendVenueRequest):
        """Send a venue to a chat."""
        check_level(account, "full")
        service = get_service(account)
        check_chat(account, chat_id)
        result = await service.send_venue(chat_id, request.latitude, request.longitude, request.title, request.address)
        return result.to_dict()

    return router
