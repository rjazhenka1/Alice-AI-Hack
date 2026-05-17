import base64
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.alice import SpeechKitClient
from ..agent.router import handle_command
from ..database import get_db
from ..models import KnowledgeBaseLink, Message, Staff, Ticket, Visibility
from ..notifier import enqueue_notification
from ..rag import index_document_chunks
from .common import ticket_visibility_filter

router = APIRouter(prefix="/integrations", tags=["integrations"])
TELEGRAM_API_URL = "https://api.telegram.org"
TELEGRAM_FILE_URL = "https://api.telegram.org/file"
logger = logging.getLogger(__name__)


def _check_webhook_secret(secret: str | None) -> None:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if expected and secret != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )


async def _find_staff_by_telegram(db: AsyncSession, telegram_id: str) -> Staff | None:
    return await db.scalar(select(Staff).where(Staff.telegram_id == telegram_id))


async def _store_incoming_message(db: AsyncSession, staff: Staff, text: str) -> Message:
    message = Message(
        event_id=staff.event_id,
        from_staff_id=staff.id,
        content=text,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


def _telegram_token() -> str | None:
    return os.getenv("TELEGRAM_BOT_TOKEN")


def _voice_storage_dir() -> Path:
    return Path(os.getenv("TELEGRAM_VOICE_DIR", "storage/telegram_voice"))


def _document_storage_dir() -> Path:
    return Path("storage/documents")


def _extension_from_file_path(file_path: str | None) -> str:
    if not file_path:
        return ".oga"
    return Path(file_path).suffix or ".oga"


def _safe_filename_part(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", str(value))


def _extract_ticket_id(caption: str | None) -> int | None:
    if not caption:
        return None
    match = re.search(r"(?:ticket|тикет|задач[аеиу]?|#)\s*#?(\d+)", caption, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _is_kb_caption(caption: str | None) -> bool:
    normalized = (caption or "").lower()
    return any(marker in normalized for marker in ("kb", "knowledge", "база знаний", "бз"))


def _caption_title(caption: str | None, fallback: str) -> str:
    if not caption:
        return fallback
    cleaned = re.sub(r"(?:ticket|тикет|задач[аеиу]?|#)\s*#?\d+", "", caption, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:kb|knowledge|база знаний|бз)\b", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()) or fallback


async def _get_telegram_file_path(
    client: httpx.AsyncClient,
    token: str,
    file_id: str,
) -> str:
    response = await client.post(
        f"{TELEGRAM_API_URL}/bot{token}/getFile",
        json={"file_id": file_id},
    )
    response.raise_for_status()
    body = response.json()
    if body.get("ok") is not True:
        raise RuntimeError(body)

    file_path = (body.get("result") or {}).get("file_path")
    if not file_path:
        raise RuntimeError("Telegram getFile response did not include file_path")
    return file_path


async def _download_telegram_file(
    client: httpx.AsyncClient,
    token: str,
    file_path: str,
    destination: Path,
) -> None:
    response = await client.get(f"{TELEGRAM_FILE_URL}/bot{token}/{file_path}")
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)


async def _download_telegram_file_bytes(
    client: httpx.AsyncClient,
    token: str,
    file_path: str,
) -> bytes:
    response = await client.get(f"{TELEGRAM_FILE_URL}/bot{token}/{file_path}")
    response.raise_for_status()
    return response.content


async def _save_telegram_voice(
    voice: dict[str, Any],
    staff: Staff,
    telegram_message: dict[str, Any],
) -> Path:
    token = _telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    file_id = voice.get("file_id")
    if not file_id:
        raise RuntimeError("Telegram voice payload did not include file_id")

    async with httpx.AsyncClient(timeout=30) as client:
        file_path = await _get_telegram_file_path(client, token, file_id)
        extension = _extension_from_file_path(file_path)
        message_id = _safe_filename_part(telegram_message.get("message_id", "unknown"))
        unique_id = _safe_filename_part(voice.get("file_unique_id", file_id))
        destination = _voice_storage_dir() / str(staff.event_id) / f"{staff.id}_{message_id}_{unique_id}{extension}"
        await _download_telegram_file(client, token, file_path, destination)
        logger.info(
            "Telegram voice saved: staff_id=%s telegram_file_path=%s local_path=%s",
            staff.id,
            file_path,
            destination,
        )
        return destination


async def _download_telegram_document_payload(
    payload: dict[str, Any],
    staff: Staff,
    telegram_message: dict[str, Any],
    *,
    default_filename: str,
) -> tuple[Path, bytes, str, str | None]:
    token = _telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    file_id = payload.get("file_id")
    if not file_id:
        raise RuntimeError("Telegram document/photo payload did not include file_id")

    async with httpx.AsyncClient(timeout=30) as client:
        file_path = await _get_telegram_file_path(client, token, file_id)
        content = await _download_telegram_file_bytes(client, token, file_path)

    filename = _safe_filename_part(payload.get("file_name") or Path(file_path).name or default_filename)
    message_id = _safe_filename_part(telegram_message.get("message_id", "unknown"))
    destination = _document_storage_dir() / str(staff.event_id) / "telegram" / f"{staff.id}_{message_id}_{filename}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination, content, filename, payload.get("mime_type")


async def _load_visible_ticket_for_staff(db: AsyncSession, staff: Staff, ticket_id: int) -> Ticket | None:
    visible_clause = await ticket_visibility_filter(db, staff)
    return await db.scalar(
        select(Ticket)
        .where(Ticket.event_id == staff.event_id, Ticket.id == ticket_id)
        .where(visible_clause)
    )


async def _attach_telegram_document_to_ticket(
    db: AsyncSession,
    *,
    staff: Staff,
    ticket_id: int,
    title: str,
    filename: str,
    content_type: str | None,
    path: Path,
    content: bytes,
) -> str:
    ticket = await _load_visible_ticket_for_staff(db, staff, ticket_id)
    if ticket is None:
        return f"Не нашла доступный тикет #{ticket_id}. Проверь номер задачи."

    document_id = uuid4().hex
    document = {
        "id": document_id,
        "title": title,
        "filename": filename,
        "content_type": content_type,
        "size": len(content),
        "path": str(path),
        "uploaded_by_id": staff.id,
        "created_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }
    ticket.documents = [*ticket.documents, document]
    await index_document_chunks(
        db,
        event_id=staff.event_id,
        content=content,
        source_title=title,
        source_url=str(path),
        ticket_id=ticket.id,
        metadata={"filename": filename, "content_type": content_type, "source": "telegram"},
    )
    await db.commit()
    return f"Прикрепила документ к задаче #{ticket.id}: {title}"


async def _upload_telegram_document_to_kb(
    db: AsyncSession,
    *,
    staff: Staff,
    title: str,
    filename: str,
    content_type: str | None,
    path: Path,
    content: bytes,
) -> str:
    if not staff.is_admin:
        return "Загружать документы в базу знаний может только организатор."

    link = KnowledgeBaseLink(
        event_id=staff.event_id,
        title=title,
        url=str(path),
        description=f"Telegram upload: {filename}",
        tags=["telegram"],
        is_active=True,
        visibility=Visibility.public,
    )
    db.add(link)
    await db.flush()
    chunks = await index_document_chunks(
        db,
        event_id=staff.event_id,
        content=content,
        source_title=link.title,
        source_url=link.url,
        knowledge_base_link_id=link.id,
        metadata={"filename": filename, "content_type": content_type, "source": "telegram"},
    )
    await db.commit()
    return f"Загрузила документ в базу знаний: {title}. Чанков: {chunks}."


def _largest_photo(photos: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not photos:
        return None
    return max(photos, key=lambda item: int(item.get("file_size") or 0))


async def _handle_telegram_document(
    db: AsyncSession,
    *,
    staff: Staff,
    telegram_message: dict[str, Any],
) -> str:
    caption = telegram_message.get("caption")
    document = telegram_message.get("document")
    photos = telegram_message.get("photo") or []
    photo = _largest_photo(photos) if isinstance(photos, list) else None
    payload = document or photo
    if not payload:
        return "Не нашла файл в сообщении."

    default_filename = "photo.jpg" if photo else "document"
    path, content, filename, content_type = await _download_telegram_document_payload(
        payload,
        staff,
        telegram_message,
        default_filename=default_filename,
    )
    title = _caption_title(caption, filename)

    ticket_id = _extract_ticket_id(caption)
    if ticket_id is not None:
        return await _attach_telegram_document_to_ticket(
            db,
            staff=staff,
            ticket_id=ticket_id,
            title=title,
            filename=filename,
            content_type=content_type,
            path=path,
            content=content,
        )

    if _is_kb_caption(caption):
        return await _upload_telegram_document_to_kb(
            db,
            staff=staff,
            title=title,
            filename=filename,
            content_type=content_type,
            path=path,
            content=content,
        )

    return "Файл получила. Подпиши его `ticket #123 ...`, чтобы прикрепить к задаче, или `kb ...`, чтобы загрузить в базу знаний."


def _voice_message_content(transcript: str) -> str:
    clean_transcript = " ".join((transcript or "").split())
    return f"[voice] {clean_transcript}" if clean_transcript else "[voice]"


def _attachment_message_content(telegram_message: dict[str, Any]) -> str:
    document = telegram_message.get("document")
    photos = telegram_message.get("photo") or []
    photo = _largest_photo(photos) if isinstance(photos, list) else None
    payload = document or photo or {}
    label = "photo" if photo and not document else "document"
    fallback = "photo" if label == "photo" else str(payload.get("file_name") or "document")
    title = " ".join(_caption_title(telegram_message.get("caption"), fallback).split())
    return f"[{label}] {title}" if title else f"[{label}]"


async def _transcribe_voice_file(file_path: Path) -> str:
    audio_base64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return await SpeechKitClient().transcribe_audio_base64(audio_base64=audio_base64)


async def _answer_with_alice(db: AsyncSession, staff: Staff, text: str, *, audio_file: str | None = None) -> str:
    event_id = int(getattr(staff, "event_id"))
    response = await handle_command(
        db=db,
        event_id=event_id,
        current_staff=staff,
        text=text,
        source="telegram_voice" if audio_file else "telegram_text",
        audio_file=audio_file,
    )
    return response.model_response or response.message


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_eventops_secret: str | None = Header(default=None),
) -> dict[str, bool]:
    _check_webhook_secret(x_eventops_secret)
    update: dict[str, Any] = await request.json()
    telegram_message = update.get("message") or update.get("edited_message") or {}
    text = telegram_message.get("text")
    voice = telegram_message.get("voice")
    document = telegram_message.get("document")
    photo = telegram_message.get("photo")
    sender = telegram_message.get("from") or {}
    chat = telegram_message.get("chat") or {}
    telegram_id = sender.get("id")

    if (not text and not voice and not document and not photo) or telegram_id is None:
        return {"ok": True}

    staff = await _find_staff_by_telegram(db, str(telegram_id))
    if staff is None:
        chat_id = chat.get("id") or telegram_id
        await enqueue_notification(
            {
                "telegram_id": str(chat_id),
                "message": "Не нашла вас в команде мероприятия. Проверьте привязку telegram_id.",
            }
        )
        return {"ok": True}

    if voice:
        try:
            voice_path = await _save_telegram_voice(voice, staff, telegram_message)
            transcribed_text = await _transcribe_voice_file(voice_path)
        except Exception as exc:
            logger.exception("Failed to process Telegram voice: telegram_id=%s", telegram_id)
            await enqueue_notification(
                {
                    "telegram_id": str(chat.get("id") or telegram_id),
                    "message": "Не смогла разобрать голосовое сообщение. Попробуйте отправить текстом.",
                }
            )
            raise HTTPException(status_code=502, detail="Failed to process Telegram voice") from exc

        await _store_incoming_message(
            db,
            staff,
            _voice_message_content(transcribed_text),
        )
        try:
            reply = await _answer_with_alice(db, staff, transcribed_text, audio_file=str(voice_path))
        except Exception:
            logger.exception("Failed to answer Telegram voice via Alice: telegram_id=%s", telegram_id)
            reply = f"Распознала голосовое: {transcribed_text}\nНо не смогла получить ответ Алисы."
    elif document or photo:
        try:
            reply = await _handle_telegram_document(db, staff=staff, telegram_message=telegram_message)
            await _store_incoming_message(db, staff, _attachment_message_content(telegram_message))
        except Exception:
            logger.exception("Failed to process Telegram document/photo: telegram_id=%s", telegram_id)
            await db.rollback()
            return {"ok": True}
    else:
        await _store_incoming_message(db, staff, str(text))
        try:
            reply = await _answer_with_alice(db, staff, str(text))
        except Exception:
            logger.exception("Failed to answer Telegram text via Alice: telegram_id=%s", telegram_id)
            reply = "Приняла сообщение, но сейчас не смогла получить ответ Алисы."

    await enqueue_notification(
        {
            "telegram_id": str(chat.get("id") or telegram_id),
            "message": reply,
        }
    )
    return {"ok": True}


@router.get("/staff/by-contact", response_model=None)
async def find_staff_by_contact(
    telegram_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not telegram_id:
        raise HTTPException(status_code=400, detail="Pass telegram_id")

    staff = await db.scalar(select(Staff).where(Staff.telegram_id == telegram_id))
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff not found")
    return {"id": staff.id, "event_id": staff.event_id, "name": staff.name}
