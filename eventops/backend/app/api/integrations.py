import base64
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.alice import SpeechKitClient
from ..agent.router import handle_command
from ..database import get_db
from ..models import Message, Staff
from ..notifier import enqueue_notification

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


def _extension_from_file_path(file_path: str | None) -> str:
    if not file_path:
        return ".oga"
    return Path(file_path).suffix or ".oga"


def _safe_filename_part(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", str(value))


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


def _voice_message_content(voice: dict[str, Any], file_path: Path) -> str:
    duration = voice.get("duration")
    mime_type = voice.get("mime_type")
    file_size = voice.get("file_size")
    return (
        "[voice] "
        f"path={file_path} "
        f"duration={duration if duration is not None else 'unknown'} "
        f"mime_type={mime_type or 'unknown'} "
        f"file_size={file_size if file_size is not None else 'unknown'}"
    )


async def _transcribe_voice_file(file_path: Path) -> str:
    audio_base64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return await SpeechKitClient().transcribe_audio_base64(audio_base64=audio_base64)


async def _answer_with_alice(
    db: AsyncSession,
    staff: Staff,
    text: str,
    *,
    audio_file: str | None = None,
) -> str:
    response = await handle_command(
        db=db,
        event_id=staff.event_id,
        current_staff=staff,
        text=text,
        source="telegram_voice" if audio_file else "telegram_text",
        audio_file=audio_file,
    )
    return response.message


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
    sender = telegram_message.get("from") or {}
    chat = telegram_message.get("chat") or {}
    telegram_id = sender.get("id")

    if (not text and not voice) or telegram_id is None:
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
            f"{_voice_message_content(voice, voice_path)} transcript={transcribed_text}",
        )
        try:
            reply = await _answer_with_alice(db, staff, transcribed_text, audio_file=str(voice_path))
        except Exception:
            logger.exception("Failed to answer Telegram voice via Alice: telegram_id=%s", telegram_id)
            reply = f"Распознала голосовое: {transcribed_text}\nНо не смогла получить ответ Алисы."
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
