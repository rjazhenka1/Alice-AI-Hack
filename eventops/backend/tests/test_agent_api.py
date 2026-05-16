from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from api.agent import agent_command, agent_confirm
from agent.alice import AlicePlanner, PlannedCommand
from database import SessionLocal, init_models
from models import AgentSession, Event, Message, Role, Staff, StaffStatus, Ticket, TicketAssignment, TicketStatus, Zone
from schemas import AgentCommandRequest, AgentConfirmRequest


@pytest.fixture(autouse=True)
async def setup_db():
    import os

    os.environ["ALICE_API_KEY"] = "test-key"
    os.environ["ALICE_FOLDER_ID"] = "test-folder"
    os.environ["ALICE_MODEL"] = "yandexgpt"

    async def fake_remote(self, *, text: str, system_prompt: str | None):
        lowered = text.lower()
        if "что происходит" in lowered or "что сейчас" in lowered:
            return PlannedCommand(kind="informational", message="Собираю сводку")
        if "ну ты поняла" in lowered:
            return PlannedCommand(kind="answered", message="Не понял задачу")
        if "нужны люди" in lowered:
            return PlannedCommand(kind="clarification", message="Уточни количество")
        return PlannedCommand(kind="operational", message="Ок", title=text[:120], description=text)

    AlicePlanner._plan_remote = fake_remote  # type: ignore[method-assign]

    await init_models()
    async with SessionLocal() as db:
        for model in (TicketAssignment, Ticket, AgentSession, Message, Staff, Role, Zone, Event):
            rows = await db.execute(select(model))
            for row in rows.scalars().all():
                await db.delete(row)
        await db.commit()
    yield


async def _seed_event_with_staff() -> tuple[int, int, int]:
    async with SessionLocal() as db:
        event = Event(name="ICPC Semifinal")
        db.add(event)
        await db.flush()

        coordinator = Staff(event_id=event.id, name="Coordinator", is_admin=True, status=StaffStatus.free)
        worker = Staff(event_id=event.id, name="Anna", status=StaffStatus.free)
        db.add_all([coordinator, worker])
        await db.commit()
        return event.id, coordinator.id, worker.id


async def _get_staff(staff_id: int) -> Staff:
    async with SessionLocal() as db:
        result = await db.execute(select(Staff).where(Staff.id == staff_id))
        return result.scalar_one()


@pytest.mark.asyncio
async def test_command_audio_returns_abi_fallback():
    event_id, coordinator_id, _ = await _seed_event_with_staff()
    coordinator = await _get_staff(coordinator_id)

    async with SessionLocal() as db:
        response = await agent_command(
            event_id=event_id,
            payload=AgentCommandRequest(audio_base64="ZmFrZQ=="),
            db=db,
            current_staff=coordinator,
        )

    assert response.action == "answered"
    assert response.message == "Поддержка голосовых сообщений не реализована"


@pytest.mark.asyncio
async def test_command_rejects_empty_payload():
    event_id, coordinator_id, _ = await _seed_event_with_staff()
    coordinator = await _get_staff(coordinator_id)

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await agent_command(
                event_id=event_id,
                payload=AgentCommandRequest(text=None, audio_base64=None),
                db=db,
                current_staff=coordinator,
            )

    assert exc.value.status_code == 422
    assert "Either text or audio_base64 is required" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_command_creates_ticket_on_operational_text():
    event_id, coordinator_id, _ = await _seed_event_with_staff()
    coordinator = await _get_staff(coordinator_id)

    async with SessionLocal() as db:
        response = await agent_command(
            event_id=event_id,
            payload=AgentCommandRequest(text="На входе толпа, срочно помогите"),
            db=db,
            current_staff=coordinator,
        )

    assert response.action == "ticket_created"
    assert response.ticket is not None
    assert response.suggestion is not None


@pytest.mark.asyncio
async def test_confirm_assigns_staff_and_updates_status():
    event_id, coordinator_id, worker_id = await _seed_event_with_staff()
    coordinator = await _get_staff(coordinator_id)

    async with SessionLocal() as db:
        create_response = await agent_command(
            event_id=event_id,
            payload=AgentCommandRequest(text="На регистрации очередь, нужна помощь"),
            db=db,
            current_staff=coordinator,
        )
        assert create_response.ticket is not None

        confirmed = await agent_confirm(
            event_id=event_id,
            payload=AgentConfirmRequest(ticket_id=create_response.ticket.id, accept=True, staff_ids=[worker_id]),
            db=db,
            current_staff=coordinator,
        )

    assert confirmed.status.value == "in_progress"

    async with SessionLocal() as db:
        ticket_result = await db.execute(select(Ticket).where(Ticket.id == confirmed.id))
        ticket = ticket_result.scalar_one()
        assert ticket.status == TicketStatus.in_progress
