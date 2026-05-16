"""API endpoints for Alice agent interactions."""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.alice import SpeechKitClient
from ..agent.router import confirm_ticket, handle_command
from ..auth import get_current_staff
from ..database import get_db
from ..models import Staff
from ..schemas import (
    AgentCommandRequest,
    AgentCommandResponse,
    AgentConfirmRequest,
    AudioSynthesis,
    Ticket,
    TranscriptionRequest,
    TranscriptionResponse,
)


router = APIRouter(prefix="/events/{event_id}/agent", tags=["agent"])


def _agent_audio_dir() -> Path:
    return Path(os.getenv("AGENT_AUDIO_DIR", "storage/agent_audio"))


def _audio_extension(audio_mime_type: str | None) -> str:
    normalized = (audio_mime_type or "").split(";", maxsplit=1)[0].strip().lower()
    if normalized == "audio/webm":
        return ".webm"
    if normalized in {"audio/ogg", "audio/oga"}:
        return ".oga"
    if normalized in {"audio/mp4", "video/mp4"}:
        return ".mp4"
    if normalized in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return ".wav"
    return ".oga"


def _save_agent_audio(event_id: int, staff_id: int, audio_base64: str, audio_mime_type: str | None = None) -> str:
    try:
        audio = base64.b64decode(audio_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid audio_base64") from exc

    path = _agent_audio_dir() / str(event_id) / f"{staff_id}_{uuid4().hex}{_audio_extension(audio_mime_type)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return str(path)


@router.post("/command", response_model=AgentCommandResponse)
async def agent_command(
    event_id: int,
    payload: AgentCommandRequest,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> AgentCommandResponse:
    speechkit = SpeechKitClient()
    text = (payload.text or "").strip()
    has_text = bool(text)
    has_audio = bool((payload.audio_base64 or "").strip())
    had_both_sources = has_text and has_audio
    audio_file: str | None = None

    if has_audio and not has_text:
        try:
            audio_file = _save_agent_audio(
                event_id,
                current_staff.id,
                payload.audio_base64 or "",
                payload.audio_mime_type,
            )
            text = await speechkit.transcribe_audio_base64(
                audio_base64=payload.audio_base64 or "",
                audio_mime_type=payload.audio_mime_type,
            )
            has_text = bool(text)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    if not has_text and not has_audio:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Either text or audio_base64 is required")

    if had_both_sources:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Provide only one command source: text or audio_base64")

    try:
        response = await handle_command(
            db=db,
            event_id=event_id,
            current_staff=current_staff,
            text=text,
            source="agent_audio" if audio_file else "agent_text",
            audio_file=audio_file,
            client_context=[item.model_dump(exclude_none=True) for item in payload.context or []] if payload.context is not None else None,
            mode=payload.mode,
        )
        response.transcript = text if audio_file else response.transcript
        tts_source = (response.model_response or response.message or "").strip()
        try:
            response.audio = AudioSynthesis(
                audio_base64=await speechkit.synthesize_text_base64(text=tts_source),
                format="oggopus",
                status="ok",
            )
        except RuntimeError as exc:
            response.audio = AudioSynthesis(
                format="oggopus",
                status="error",
                detail=str(exc),
            )
        return response
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/transcribe", response_model=TranscriptionResponse)
async def agent_transcribe(
    event_id: int,
    payload: TranscriptionRequest,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> TranscriptionResponse:
    if current_staff.event_id != event_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this event")

    try:
        text = await SpeechKitClient().transcribe_audio_base64(
            audio_base64=payload.audio_base64,
            language=payload.language,
            audio_mime_type=payload.audio_mime_type,
        )
        return TranscriptionResponse(text=text, status="ok")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except RuntimeError as exc:
        return TranscriptionResponse(text=None, status="error", detail=str(exc))


@router.post("/confirm", response_model=Ticket)
async def agent_confirm(
    event_id: int,
    payload: AgentConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Ticket:
    try:
        return await confirm_ticket(
            db=db,
            event_id=event_id,
            current_staff=current_staff,
            ticket_id=payload.ticket_id,
            accept=payload.accept,
            staff_ids=payload.staff_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
