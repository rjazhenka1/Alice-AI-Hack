"""API endpoints for Alice agent interactions."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.alice import SpeechKitClient, audio_not_supported_message
from ..agent.router import confirm_ticket, handle_command
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

try:
    from ..auth import get_current_staff
except Exception:  # pragma: no cover - fallback for partial PoC environments
    async def get_current_staff() -> Staff:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth is not configured")


try:
    from ..database import get_db
except Exception:  # pragma: no cover - fallback for partial PoC environments
    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured")
        yield


router = APIRouter(prefix="/events/{event_id}/agent", tags=["agent"])


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

    if has_audio and not has_text:
        return AgentCommandResponse(
            action="answered",
            message=audio_not_supported_message(),
            audio=AudioSynthesis(status="not_implemented", detail="SpeechKit TTS stub is not implemented yet"),
        )

    if not has_text and not has_audio:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Either text or audio_base64 is required")

    if has_text and has_audio:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Provide only one command source: text or audio_base64")

    try:
        response = await handle_command(db=db, event_id=event_id, current_staff=current_staff, text=text)
        if response.audio is None:
            response.audio = AudioSynthesis(status="not_implemented", detail="SpeechKit TTS stub is not implemented yet")
        # Keep reference so stub method exists in merge target; implementation comes later.
        _ = speechkit
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
    # Event/staff dependencies are intentionally kept for future auth and access checks.
    _ = (event_id, db, current_staff, payload)
    return TranscriptionResponse(
        text=None,
        status="not_implemented",
        detail="SpeechKit STT stub is not implemented yet",
    )


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
