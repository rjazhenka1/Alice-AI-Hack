from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent import agent_command, agent_confirm
from app.agent.alice import AlicePlanner, PlannedCommand, SpeechKitClient
from app.models import (
    AgentSession,
    ConfidentialityRule,
    Event,
    KnowledgeBaseLink,
    Message,
    Role,
    Staff,
    StaffStatus,
    Ticket,
    TicketAssignment,
    TicketPriority,
    TicketStatus,
    Visibility,
    Zone,
)
from app.schemas import AgentCommandRequest, AgentConfirmRequest


@pytest_asyncio.fixture(autouse=True)
async def setup_alice_env():
    import os

    os.environ["ALICE_API_KEY"] = "test-key"
    os.environ["ALICE_FOLDER_ID"] = "test-folder"
    os.environ["ALICE_MODEL"] = "yandexgpt"

    async def fake_remote(self, *, text: str, system_prompt: str | None):
        AlicePlanner._last_system_prompt = system_prompt  # type: ignore[attr-defined]
        lowered = text.lower()
        if "расплывчато без уточнения" in lowered:
            if system_prompt and "Не предлагай действий и не создавай задачу" in system_prompt:
                return PlannedCommand(kind="answered", message="Недостаточно данных")
            return PlannedCommand(kind="imprecise", message="Формулировка расплывчата")
        if "расплывчато" in lowered:
            if system_prompt and "Не предлагай действий и не создавай задачу" in system_prompt:
                return PlannedCommand(kind="clarification", message="Уточни точную задачу и дедлайн")
            return PlannedCommand(kind="imprecise", message="Формулировка расплывчата")
        if "что происходит" in lowered or "что сейчас" in lowered:
            return PlannedCommand(kind="informational", message="Собираю сводку")
        if "напиши всем" in lowered:
            return PlannedCommand(
                kind="operational",
                target="broadcast",
                message="Отправлю всем",
                description="Сбор у штаба через 10 минут",
                assignees="all",
            )
        if "компьютерное зрение" in lowered:
            return PlannedCommand(kind="knowledge_base", message="Ищу в базе знаний", keywords=["Компьютерное зрение"])
        if "анну" in lowered:
            return PlannedCommand(kind="operational", message="Ок", title="Поставить на вход", description=text, assignees=["Анну"])
        if "ну ты поняла" in lowered:
            return PlannedCommand(kind="answered", message="Не понял задачу")
        if "нужны люди" in lowered:
            return PlannedCommand(kind="clarification", message="Уточни количество")
        return PlannedCommand(kind="operational", message="Ок", title=text[:120], description=text)

    AlicePlanner._plan_remote = fake_remote  # type: ignore[method-assign]

    async def fake_synthesize_knowledge(self, *, question: str, rag_fragments: list[str], system_prompt: str):
        _ = (self, question, system_prompt)
        if not rag_fragments:
            return None
        return rag_fragments[0]

    AlicePlanner.synthesize_knowledge_answer = fake_synthesize_knowledge  # type: ignore[method-assign]

    async def fake_transcribe(self, *, audio_base64: str, language: str = "ru-RU") -> str:
        _ = (self, audio_base64, language)
        return "Нужны люди на входе"

    async def fake_synthesize(self, *, text: str, voice: str = "alena") -> str:
        _ = (self, text, voice)
        return "c3luZXRoZXNpcy1iYXNlNjQ="

    SpeechKitClient.transcribe_audio_base64 = fake_transcribe  # type: ignore[method-assign]
    SpeechKitClient.synthesize_text_base64 = fake_synthesize  # type: ignore[method-assign]

    yield


async def _seed_event_with_staff(db: AsyncSession) -> tuple[int, int, int]:
    event = Event(name="ICPC Semifinal")
    db.add(event)
    await db.flush()

    coordinator = Staff(event_id=event.id, name="Coordinator", is_admin=True, status=StaffStatus.free)
    worker = Staff(event_id=event.id, name="Anna", status=StaffStatus.free)
    db.add_all([coordinator, worker])
    await db.flush()
    return event.id, coordinator.id, worker.id


async def _get_staff(db: AsyncSession, staff_id: int) -> Staff:
    result = await db.execute(select(Staff).where(Staff.id == staff_id))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_command_audio_transcribes_and_runs_regular_flow(db_session: AsyncSession):
    event_id, coordinator_id, _ = await _seed_event_with_staff(db_session)
    coordinator = await _get_staff(db_session, coordinator_id)

    async def fake_transcribe(self, *, audio_base64: str, audio_mime_type: str | None = None, language: str = "ru-RU") -> str:
        return "На входе толпа, срочно помогите"

    from app.agent.alice import SpeechKitClient

    SpeechKitClient.transcribe_audio_base64 = fake_transcribe  # type: ignore[method-assign]

    response = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(audio_base64="ZmFrZQ=="),
        db=db_session,
        current_staff=coordinator,
    )

    assert response.action == "ticket_created"
    assert response.ticket is not None
    assert response.model_response is not None
    assert "Создал задачу" in response.model_response
    assert response.author is not None
    assert response.author.id == coordinator_id


@pytest.mark.asyncio
async def test_command_rejects_empty_payload(db_session: AsyncSession):
    event_id, coordinator_id, _ = await _seed_event_with_staff(db_session)
    coordinator = await _get_staff(db_session, coordinator_id)

    with pytest.raises(HTTPException) as exc:
        await agent_command(
            event_id=event_id,
            payload=AgentCommandRequest(text=None, audio_base64=None),
            db=db_session,
            current_staff=coordinator,
        )

    assert exc.value.status_code == 422
    assert "Either text or audio_base64 is required" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_command_creates_ticket_on_operational_text(db_session: AsyncSession):
    event_id, coordinator_id, _ = await _seed_event_with_staff(db_session)
    coordinator = await _get_staff(db_session, coordinator_id)

    response = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="На входе толпа, срочно помогите"),
        db=db_session,
        current_staff=coordinator,
    )

    assert response.action == "ticket_created"
    assert response.ticket is not None
    assert response.suggestion is not None
    assert response.model_response is not None
    assert response.author is not None
    assert response.ticket.target["all"] is False
    assert isinstance(response.ticket.target["staff_ids"], list)
    assert response.ticket.target["staff_ids"] == []
    assert response.ticket.target["role_ids"] == []


@pytest.mark.asyncio
async def test_command_broadcasts_without_creating_ticket(db_session: AsyncSession, monkeypatch):
    event_id, coordinator_id, worker_id = await _seed_event_with_staff(db_session)
    coordinator = await _get_staff(db_session, coordinator_id)
    worker = await _get_staff(db_session, worker_id)
    coordinator.telegram_id = "100"
    worker.telegram_id = "101"
    await db_session.commit()

    queued_notifications: list[dict] = []

    async def fake_enqueue(payload: dict):
        queued_notifications.append(payload)

    monkeypatch.setattr("app.notifier.enqueue_notification", fake_enqueue)

    response = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="Напиши всем: сбор у штаба через 10 минут"),
        db=db_session,
        current_staff=coordinator,
    )

    assert response.action == "answered"
    assert "Telegram-очередь: 1" in response.message
    assert queued_notifications == [
        {"telegram_id": "101", "message": "Coordinator: Сбор у штаба через 10 минут"}
    ]

    tickets = list((await db_session.scalars(select(Ticket))).all())
    assert tickets == []
    messages = list((await db_session.scalars(select(Message))).all())
    assert len(messages) == 1
    assert messages[0].content == "Сбор у штаба через 10 минут"


@pytest.mark.asyncio
async def test_command_sets_priority_from_urgency_words(db_session: AsyncSession):
    event_id, coordinator_id, _ = await _seed_event_with_staff(db_session)
    coordinator = await _get_staff(db_session, coordinator_id)

    urgent = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="Срочно принесите удлинители в холл"),
        db=db_session,
        current_staff=coordinator,
    )
    relaxed = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="Не срочно принесите воду в штаб"),
        db=db_session,
        current_staff=coordinator,
    )

    assert urgent.ticket is not None
    assert urgent.ticket.priority == TicketPriority.high
    assert relaxed.ticket is not None
    assert relaxed.ticket.priority == TicketPriority.low


@pytest.mark.asyncio
async def test_confirm_assigns_staff_and_updates_status(db_session: AsyncSession):
    event_id, coordinator_id, worker_id = await _seed_event_with_staff(db_session)
    coordinator = await _get_staff(db_session, coordinator_id)

    create_response = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="На регистрации очередь, нужна помощь"),
        db=db_session,
        current_staff=coordinator,
    )
    assert create_response.ticket is not None

    confirmed = await agent_confirm(
        event_id=event_id,
        payload=AgentConfirmRequest(ticket_id=create_response.ticket.id, accept=True, staff_ids=[worker_id]),
        db=db_session,
        current_staff=coordinator,
    )

    assert confirmed.status.value == "in_progress"

    ticket_result = await db_session.execute(select(Ticket).where(Ticket.id == confirmed.id))
    ticket = ticket_result.scalar_one()
    assert ticket.status == TicketStatus.in_progress


@pytest.mark.asyncio
async def test_agent_prompt_uses_full_kb_and_confidentiality_rules(db_session: AsyncSession):
    event_id, _, _ = await _seed_event_with_staff(db_session)
    role = Role(event_id=event_id, name="Волонтёры", can_see_confidential=False)
    volunteer = Staff(event_id=event_id, name="Volunteer", role=role, status=StaffStatus.free)
    db_session.add_all(
        [
            role,
            volunteer,
            KnowledgeBaseLink(
                event_id=event_id,
                title="Публичный регламент",
                url="admin://knowledge/public-policy",
                visibility=Visibility.public,
                is_active=True,
            ),
            KnowledgeBaseLink(
                event_id=event_id,
                title="Закрытое решение жюри",
                url="admin://knowledge/jury-private",
                visibility=Visibility.confidential,
                is_active=True,
            ),
            ConfidentialityRule(
                event_id=event_id,
                category="Решения жюри",
                description="Не раскрывать до публикации",
                severity="high",
            ),
        ]
    )
    await db_session.flush()

    await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="ну ты поняла"),
        db=db_session,
        current_staff=volunteer,
    )

    prompt = AlicePlanner._last_system_prompt  # type: ignore[attr-defined]
    assert "Публичный регламент" in prompt
    assert "Закрытое решение жюри" in prompt
    assert "Решения жюри" in prompt
    assert "Не раскрывать до публикации" in prompt


@pytest.mark.asyncio
async def test_informational_command_searches_document_chunks(db_session: AsyncSession):
    event_id, coordinator_id, _ = await _seed_event_with_staff(db_session)
    coordinator = await _get_staff(db_session, coordinator_id)
    from app.models import DocumentChunk

    db_session.add(
        DocumentChunk(
            event_id=event_id,
            content="31. Компьютерное зрение 3 з.е. отлично",
            source_title="Учебная справка",
            source_url="storage/documents/test.jpg",
            chunk_index=0,
        )
    )
    await db_session.commit()

    response = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="Есть ли в базе знаний дисциплина Компьютерное зрение?"),
        db=db_session,
        current_staff=coordinator,
    )

    assert response.action == "answered"
    assert "Компьютерное зрение" in response.message
    assert "Учебная справка" not in response.message
    assert "storage/documents" not in response.message


@pytest.mark.asyncio
async def test_chat_mode_searches_document_chunks(db_session: AsyncSession):
    event_id, _, worker_id = await _seed_event_with_staff(db_session)
    worker = await _get_staff(db_session, worker_id)
    from app.models import DocumentChunk

    db_session.add(
        DocumentChunk(
            event_id=event_id,
            content="31. Компьютерное зрение 3 з.е. отлично",
            source_title="Учебная справка",
            source_url="storage/documents/test.jpg",
            chunk_index=0,
        )
    )
    await db_session.commit()

    response = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="Есть ли в базе знаний дисциплина Компьютерное зрение?", mode="chat"),
        db=db_session,
        current_staff=worker,
    )

    assert response.action == "answered"
    assert "Компьютерное зрение" in response.message
    assert "Учебная справка" not in response.message
    assert "storage/documents" not in response.message


def test_kb_answer_does_not_return_unrelated_vector_matches():
    from app.agent.router import _format_kb_search_answer

    answer = _format_kb_search_answer(
        [
            {
                "source_title": "kb_test2",
                "source_url": "storage/documents/test.jpg",
                "content": "31. Компьютерное зрение 3 з.е. отлично",
            },
            {
                "source_title": "kb_1txt",
                "source_url": "storage/documents/test.txt",
                "content": "1:0,72:72:99:2031,0 1:0,60:60:99:1509,0",
            },
        ],
        "А что есть про Максима Альжанова?",
    )

    assert answer == "В базе знаний сейчас не нашла точной информации по этому запросу."
    assert "Компьютерное зрение" not in answer


@pytest.mark.asyncio
async def test_ticket_summary_query_uses_tickets_not_knowledge(db_session: AsyncSession):
    event_id, coordinator_id, _ = await _seed_event_with_staff(db_session)
    coordinator = await _get_staff(db_session, coordinator_id)
    db_session.add(Ticket(event_id=event_id, title="Доставка удлинителей", status=TicketStatus.waiting))
    await db_session.commit()

    response = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="Какие актуальные задачи сейчас?"),
        db=db_session,
        current_staff=coordinator,
    )

    assert response.action == "answered"
    assert "Актуальные задачи" in response.message
    assert "Доставка удлинителей" in response.message
    assert "базе знаний" not in response.message


@pytest.mark.asyncio
async def test_assignee_resolution_matches_cyrillic_first_name_to_latin_staff(db_session: AsyncSession):
    event_id, coordinator_id, _ = await _seed_event_with_staff(db_session)
    coordinator = await _get_staff(db_session, coordinator_id)

    response = await agent_command(
        event_id=event_id,
        payload=AgentCommandRequest(text="Поставь Анну на вход"),
        db=db_session,
        current_staff=coordinator,
    )

    assert response.ticket is not None
    assert response.ticket.target["staff_ids"] == [2]
