"""API endpoints for Alice agent interactions."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.alice import SpeechKitClient
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
    had_both_sources = has_text and has_audio

    if has_audio and not has_text:
        try:
            text = await speechkit.transcribe_audio_base64(audio_base64=payload.audio_base64 or "")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
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
        response = await handle_command(db=db, event_id=event_id, current_staff=current_staff, text=text)
        try:
            response.audio = AudioSynthesis(
                audio_base64=await speechkit.synthesize_text_base64(text=response.message),
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
