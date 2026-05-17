from __future__ import annotations

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.alice import KnowledgeCaptureDecision
from app.auth import ALGORITHM
from app.models import DocumentChunk, KnowledgeBaseLink, Message, Staff, Ticket

from conftest import auth_headers, seed_event, seed_role, seed_staff


pytestmark = pytest.mark.asyncio


async def test_auth_login_returns_valid_jwt(client: AsyncClient, db_session: AsyncSession):
    event = await seed_event(db_session)
    staff = await seed_staff(
        db_session,
        event.id,
        name="Admin",
        telegram_id="1001",
        telegram_username="admin_user",
        is_admin=True,
    )
    await db_session.commit()

    response = await client.post("/auth/login", json={"telegram_username": "@admin_user"})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["staff_id"] == staff.id
    assert body["is_admin"] is True

    payload = jwt.decode(body["access_token"], "test-secret", algorithms=[ALGORITHM])
    assert payload["sub"] == str(staff.id)
    assert "exp" in payload

    events_response = await client.get(
        "/events",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert events_response.status_code == 200
    assert events_response.json()[0]["id"] == event.id


async def test_auth_login_bootstraps_first_admin_from_env(client: AsyncClient, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_USERNAME", "@BellatorHonoris")

    response = await client.post("/auth/login", json={"telegram_username": "@BellatorHonoris"})

    assert response.status_code == 200
    body = response.json()
    assert body["is_admin"] is True

    events_response = await client.get(
        "/events",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert events_response.status_code == 200
    assert events_response.json()[0]["name"] == "Первое мероприятие"


async def test_roles_create_and_list_requires_event_admin(client: AsyncClient, db_session: AsyncSession):
    event = await seed_event(db_session)
    admin = await seed_staff(db_session, event.id, name="Admin", is_admin=True)
    member = await seed_staff(db_session, event.id, name="Volunteer")
    await db_session.commit()

    forbidden = await client.post(
        f"/events/{event.id}/roles",
        json={"name": "Live"},
        headers=auth_headers(member),
    )
    assert forbidden.status_code == 403

    create_response = await client.post(
        f"/events/{event.id}/roles",
        json={
            "name": "Регистрация",
            "description": "Вход и бейджи",
            "ai_prompt": "Помогает на входе и регистрации",
            "color": "#22c55e",
            "can_see_confidential": False,
        },
        headers=auth_headers(admin),
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["event_id"] == event.id
    assert created["name"] == "Регистрация"
    assert created["color"] == "#22c55e"

    list_response = await client.get(f"/events/{event.id}/roles", headers=auth_headers(member))
    assert list_response.status_code == 200
    assert [role["name"] for role in list_response.json()] == ["Регистрация"]


async def test_tickets_create_and_list_visibility_basic(client: AsyncClient, db_session: AsyncSession):
    event = await seed_event(db_session)
    registration = await seed_role(db_session, event.id, "Регистрация")
    tech = await seed_role(db_session, event.id, "Техкомитет")
    admin = await seed_staff(db_session, event.id, name="Admin", is_admin=True)
    registration_staff = await seed_staff(
        db_session,
        event.id,
        name="Anna",
        role_id=registration.id,
    )
    tech_staff = await seed_staff(db_session, event.id, name="Max", role_id=tech.id)
    await db_session.commit()

    public_response = await client.post(
        f"/events/{event.id}/tickets",
        json={"title": "Очередь на входе", "priority": "high", "visibility": "public"},
        headers=auth_headers(admin),
    )
    assert public_response.status_code == 201
    assert public_response.json()["created_by_id"] == admin.id
    assert public_response.json()["sender"]["id"] == admin.id
    assert public_response.json()["created_by"]["name"] == "Admin"

    role_only_response = await client.post(
        f"/events/{event.id}/tickets",
        json={
            "title": "Проверить бейджи",
            "visibility": "role_only",
            "assignee_role_id": registration.id,
        },
        headers=auth_headers(admin),
    )
    assert role_only_response.status_code == 201

    confidential_response = await client.post(
        f"/events/{event.id}/tickets",
        json={"title": "Закрытый инцидент", "visibility": "confidential"},
        headers=auth_headers(admin),
    )
    assert confidential_response.status_code == 201

    regular_confidential = await client.post(
        f"/events/{event.id}/tickets",
        json={"title": "Нельзя создать", "visibility": "confidential"},
        headers=auth_headers(registration_staff),
    )
    assert regular_confidential.status_code == 403

    admin_list = await client.get(f"/events/{event.id}/tickets", headers=auth_headers(admin))
    assert admin_list.status_code == 200
    assert {ticket["title"] for ticket in admin_list.json()} == {
        "Очередь на входе",
        "Проверить бейджи",
        "Закрытый инцидент",
    }

    registration_list = await client.get(
        f"/events/{event.id}/tickets",
        headers=auth_headers(registration_staff),
    )
    assert registration_list.status_code == 200
    assert {ticket["title"] for ticket in registration_list.json()} == {
        "Очередь на входе",
        "Проверить бейджи",
    }

    tech_list = await client.get(f"/events/{event.id}/tickets", headers=auth_headers(tech_staff))
    assert tech_list.status_code == 200
    assert [ticket["title"] for ticket in tech_list.json()] == ["Очередь на входе"]


async def test_ticket_replies_use_ticket_visibility_and_sender(
    client: AsyncClient,
    db_session: AsyncSession,
):
    event = await seed_event(db_session)
    admin = await seed_staff(db_session, event.id, name="Admin", is_admin=True)
    member = await seed_staff(db_session, event.id, name="Volunteer")
    await db_session.commit()

    ticket_response = await client.post(
        f"/events/{event.id}/tickets",
        json={"title": "Проверить вход"},
        headers=auth_headers(admin),
    )
    assert ticket_response.status_code == 201
    ticket_id = ticket_response.json()["id"]

    reply_response = await client.post(
        f"/events/{event.id}/tickets/{ticket_id}/replies",
        json={"content": "Взял, иду к входу"},
        headers=auth_headers(member),
    )
    assert reply_response.status_code == 201
    reply = reply_response.json()
    assert reply["content"] == "Взял, иду к входу"
    assert reply["sender"]["id"] == member.id

    replies_response = await client.get(
        f"/events/{event.id}/tickets/{ticket_id}/replies",
        headers=auth_headers(admin),
    )
    assert replies_response.status_code == 200
    assert [item["content"] for item in replies_response.json()] == ["Взял, иду к входу"]


async def test_admin_reply_to_other_admin_ticket_can_be_promoted_to_knowledge(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    event = await seed_event(db_session)
    creator = await seed_staff(db_session, event.id, name="Creator", is_admin=True)
    responder = await seed_staff(db_session, event.id, name="Responder", is_admin=True)
    await db_session.commit()

    async def fake_assess(self, *, conversation: str, system_prompt: str):
        assert "Тикет" in conversation
        assert "Разговор" in conversation
        assert "знан" in system_prompt.lower()
        return KnowledgeCaptureDecision(
            useful=True,
            title="Инструкция по бейджам",
            content="Если закончились бейджи, нужно взять запас на стойке регистрации.",
            tags=["registration", "badges"],
            reason="Повторно полезная инструкция",
        )

    monkeypatch.setattr("app.api.tickets.AlicePlanner.assess_knowledge_candidate", fake_assess)

    ticket_response = await client.post(
        f"/events/{event.id}/tickets",
        json={"title": "Закончились бейджи", "description": "Что делать на регистрации?"},
        headers=auth_headers(creator),
    )
    ticket_id = ticket_response.json()["id"]

    reply_response = await client.post(
        f"/events/{event.id}/tickets/{ticket_id}/replies",
        json={"content": "Запасные бейджи лежат на стойке регистрации."},
        headers=auth_headers(responder),
    )

    assert reply_response.status_code == 201
    link = await db_session.scalar(select(KnowledgeBaseLink).where(KnowledgeBaseLink.title == "Инструкция по бейджам"))
    assert link is not None
    assert link.tags == ["registration", "badges"]
    chunk = await db_session.scalar(select(DocumentChunk).where(DocumentChunk.knowledge_base_link_id == link.id))
    assert chunk is not None
    assert "запас" in chunk.content.lower()


async def test_attach_document_to_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    event = await seed_event(db_session)
    admin = await seed_staff(db_session, event.id, name="Admin", is_admin=True)
    await db_session.commit()

    ticket_response = await client.post(
        f"/events/{event.id}/tickets",
        json={"title": "Проверить вход"},
        headers=auth_headers(admin),
    )
    ticket_id = ticket_response.json()["id"]

    upload_response = await client.post(
        f"/events/{event.id}/tickets/{ticket_id}/documents",
        data={"title": "Схема входа"},
        files={"file": ("entrance.txt", b"hello", "text/plain")},
        headers=auth_headers(admin),
    )

    assert upload_response.status_code == 201
    document = upload_response.json()
    assert document["title"] == "Схема входа"
    assert document["filename"] == "entrance.txt"
    assert document["size"] == 5

    db_session.expire_all()
    ticket = await db_session.scalar(select(Ticket).where(Ticket.id == ticket_id))
    assert ticket is not None
    assert ticket.documents[0]["title"] == "Схема входа"
    chunk = await db_session.scalar(select(DocumentChunk).where(DocumentChunk.ticket_id == ticket_id))
    assert chunk is not None
    assert "hello" in chunk.content


async def test_upload_knowledge_document(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    event = await seed_event(db_session)
    admin = await seed_staff(db_session, event.id, name="Admin", is_admin=True)
    member = await seed_staff(db_session, event.id, name="Member")
    await db_session.commit()

    forbidden = await client.post(
        f"/events/{event.id}/knowledge/upload",
        data={"title": "Регламент"},
        files={"file": ("rules.pdf", b"pdf", "application/pdf")},
        headers=auth_headers(member),
    )
    assert forbidden.status_code == 403

    response = await client.post(
        f"/events/{event.id}/knowledge/upload",
        data={"title": "Регламент", "description": "Основные правила", "tags": "rules, venue"},
        files={"file": ("rules.pdf", b"pdf", "application/pdf")},
        headers=auth_headers(admin),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Регламент"
    assert body["description"] == "Основные правила"
    assert body["tags"] == ["rules", "venue"]
    assert body["url"].endswith("_rules.pdf")

    link = await db_session.scalar(select(KnowledgeBaseLink).where(KnowledgeBaseLink.id == body["id"]))
    assert link is not None
    assert link.url == body["url"]

    chunk = await db_session.scalar(select(DocumentChunk).where(DocumentChunk.knowledge_base_link_id == link.id))
    assert chunk is not None
    assert "pdf" in chunk.content

    search_response = await client.get(
        f"/events/{event.id}/knowledge/search",
        params={"q": "pdf"},
        headers=auth_headers(admin),
    )
    assert search_response.status_code == 200
    assert search_response.json()[0]["source_title"] == "Регламент"


async def test_knowledge_search_respects_confidential_visibility(
    client: AsyncClient,
    db_session: AsyncSession,
):
    event = await seed_event(db_session)
    admin = await seed_staff(db_session, event.id, name="Admin", is_admin=True)
    volunteer = await seed_staff(db_session, event.id, name="Volunteer")
    public_link = KnowledgeBaseLink(
        event_id=event.id,
        title="Публичная инструкция",
        url="admin://public",
        visibility="public",
        is_active=True,
    )
    secret_link = KnowledgeBaseLink(
        event_id=event.id,
        title="Закрытая инструкция",
        url="admin://secret",
        visibility="confidential",
        is_active=True,
    )
    db_session.add_all([public_link, secret_link])
    await db_session.flush()
    db_session.add_all(
        [
            DocumentChunk(
                event_id=event.id,
                knowledge_base_link_id=public_link.id,
                content="Общий регламент регистрации",
                source_title=public_link.title,
                source_url=public_link.url,
                chunk_index=0,
            ),
            DocumentChunk(
                event_id=event.id,
                knowledge_base_link_id=secret_link.id,
                content="Секретный регламент жюри",
                source_title=secret_link.title,
                source_url=secret_link.url,
                chunk_index=0,
            ),
        ]
    )
    await db_session.commit()

    volunteer_response = await client.get(
        f"/events/{event.id}/knowledge/search",
        params={"q": "регламент", "limit": 10},
        headers=auth_headers(volunteer),
    )
    assert volunteer_response.status_code == 200
    assert {item["source_title"] for item in volunteer_response.json()} == {"Публичная инструкция"}

    admin_response = await client.get(
        f"/events/{event.id}/knowledge/search",
        params={"q": "регламент", "limit": 10},
        headers=auth_headers(admin),
    )
    assert admin_response.status_code == 200
    assert {item["source_title"] for item in admin_response.json()} == {
        "Публичная инструкция",
        "Закрытая инструкция",
    }


async def test_admin_can_broadcast_to_all_role_or_staff(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    event = await seed_event(db_session)
    registration = await seed_role(db_session, event.id, "Регистрация")
    admin = await seed_staff(db_session, event.id, name="Admin", telegram_id="100", is_admin=True)
    anna = await seed_staff(db_session, event.id, name="Anna", telegram_id="101", role_id=registration.id)
    max_staff = await seed_staff(db_session, event.id, name="Max", telegram_id="102")
    no_telegram = await seed_staff(db_session, event.id, name="No Telegram")
    await db_session.commit()

    queued_notifications: list[dict] = []

    async def fake_enqueue(payload: dict):
        queued_notifications.append(payload)

    monkeypatch.setattr("app.api.messages.enqueue_notification", fake_enqueue)

    forbidden = await client.post(
        f"/events/{event.id}/messages/broadcast",
        json={"message": "Нельзя", "target": "all"},
        headers=auth_headers(anna),
    )
    assert forbidden.status_code == 403

    all_response = await client.post(
        f"/events/{event.id}/messages/broadcast",
        json={"message": "Сбор у штаба", "target": "all"},
        headers=auth_headers(admin),
    )
    assert all_response.status_code == 200
    assert all_response.json()["queued_count"] == 2
    assert all_response.json()["target_staff_ids"] == [anna.id, max_staff.id, no_telegram.id]
    assert all_response.json()["skipped_without_telegram_ids"] == [no_telegram.id]
    assert [item["telegram_id"] for item in queued_notifications] == ["101", "102"]

    queued_notifications.clear()
    role_response = await client.post(
        f"/events/{event.id}/messages/broadcast",
        json={"message": "Регистрация, к входу", "target": "role", "role_id": registration.id},
        headers=auth_headers(admin),
    )
    assert role_response.status_code == 200
    assert role_response.json()["target_staff_ids"] == [anna.id]
    assert [item["telegram_id"] for item in queued_notifications] == ["101"]

    queued_notifications.clear()
    staff_response = await client.post(
        f"/events/{event.id}/messages/broadcast",
        json={"message": "Макс, проверь звук", "target": "staff", "staff_ids": [max_staff.id]},
        headers=auth_headers(admin),
    )
    assert staff_response.status_code == 200
    assert staff_response.json()["target_staff_ids"] == [max_staff.id]
    assert queued_notifications[0]["message"] == "Admin: Макс, проверь звук"


async def test_telegram_webhook_text_saves_message_and_queues_reply(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    event = await seed_event(db_session)
    staff = await seed_staff(
        db_session,
        event.id,
        name="Telegram User",
        telegram_id="777",
    )
    await db_session.commit()

    queued_notifications: list[dict[str, str]] = []

    async def fake_enqueue_notification(payload: dict[str, str]) -> None:
        queued_notifications.append(payload)

    monkeypatch.setattr("app.api.integrations.enqueue_notification", fake_enqueue_notification)

    response = await client.post(
        "/integrations/telegram/webhook",
        json={
            "message": {
                "message_id": 10,
                "from": {"id": 777},
                "chat": {"id": 777},
                "text": "Нужна помощь у входа",
            }
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    message = await db_session.scalar(select(Message).where(Message.from_staff_id == staff.id))
    assert message is not None
    assert message.event_id == event.id
    assert message.content == "Нужна помощь у входа"

    assert queued_notifications[0]["telegram_id"] == "777"
    assert queued_notifications[0]["message"]


async def test_telegram_start_registers_user_in_first_event(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    event = await seed_event(db_session)
    await db_session.commit()
    queued_notifications: list[dict[str, str]] = []

    async def fake_enqueue_notification(payload: dict[str, str]) -> None:
        queued_notifications.append(payload)

    monkeypatch.setattr("app.api.integrations.enqueue_notification", fake_enqueue_notification)

    response = await client.post(
        "/integrations/telegram/webhook",
        json={
            "message": {
                "message_id": 20,
                "from": {"id": 900, "username": "new_user", "first_name": "Новый", "last_name": "Участник"},
                "chat": {"id": 900},
                "text": "/start",
            }
        },
    )

    assert response.status_code == 200
    staff = await db_session.scalar(select(Staff).where(Staff.telegram_id == "900"))
    assert staff is not None
    assert staff.event_id == event.id
    assert staff.name == "Новый Участник"
    assert staff.telegram_username == "new_user"
    assert queued_notifications == [
        {
            "telegram_id": "900",
            "message": "Готово, добавила вас в мероприятие как участника: Новый Участник.",
        }
    ]


async def test_telegram_start_updates_existing_user_without_duplicate(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    event = await seed_event(db_session)
    staff = await seed_staff(db_session, event.id, name="Telegram User", telegram_id="901")
    await db_session.commit()
    queued_notifications: list[dict[str, str]] = []

    async def fake_enqueue_notification(payload: dict[str, str]) -> None:
        queued_notifications.append(payload)

    monkeypatch.setattr("app.api.integrations.enqueue_notification", fake_enqueue_notification)

    response = await client.post(
        "/integrations/telegram/webhook",
        json={
            "message": {
                "message_id": 21,
                "from": {"id": 901, "username": "known_user", "first_name": "Known"},
                "chat": {"id": 901},
                "text": "/start",
            }
        },
    )

    assert response.status_code == 200
    rows = (await db_session.scalars(select(Staff).where(Staff.telegram_id == "901"))).all()
    assert len(rows) == 1
    await db_session.refresh(rows[0])
    assert rows[0].id == staff.id
    assert rows[0].telegram_username == "known_user"
    assert rows[0].name == "Known"
    assert queued_notifications[0]["telegram_id"] == "901"


async def test_telegram_webhook_voice_transcribes_and_answers(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    event = await seed_event(db_session)
    staff = await seed_staff(db_session, event.id, name="Telegram User", telegram_id="778")
    await db_session.commit()

    voice_path = tmp_path / "voice.oga"
    voice_path.write_bytes(b"fake")
    queued_notifications: list[dict[str, str]] = []

    async def fake_save_voice(*args, **kwargs):
        return voice_path

    async def fake_transcribe(path):
        assert path == voice_path
        return "Что мне делать?"

    async def fake_answer(db, staff, text, **kwargs):
        assert text == "Что мне делать?"
        assert kwargs["audio_file"] == str(voice_path)
        return "Твоя текущая задача: быть на регистрации."

    async def fake_enqueue_notification(payload: dict[str, str]) -> None:
        queued_notifications.append(payload)

    monkeypatch.setattr("app.api.integrations._save_telegram_voice", fake_save_voice)
    monkeypatch.setattr("app.api.integrations._transcribe_voice_file", fake_transcribe)
    monkeypatch.setattr("app.api.integrations._answer_with_alice", fake_answer)
    monkeypatch.setattr("app.api.integrations.enqueue_notification", fake_enqueue_notification)

    response = await client.post(
        "/integrations/telegram/webhook",
        json={
            "message": {
                "message_id": 11,
                "from": {"id": 778},
                "chat": {"id": 778},
                "voice": {"file_id": "file-1", "duration": 2},
            }
        },
    )

    assert response.status_code == 200
    message = await db_session.scalar(select(Message).where(Message.from_staff_id == staff.id))
    assert message is not None
    assert message.content == "[voice] Что мне делать?"
    assert queued_notifications == [
        {
            "telegram_id": "778",
            "message": "Твоя текущая задача: быть на регистрации.",
        }
    ]


async def test_telegram_document_can_attach_to_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    event = await seed_event(db_session)
    staff = await seed_staff(db_session, event.id, name="Telegram User", telegram_id="779", is_admin=True)
    await db_session.commit()
    ticket_response = await client.post(
        f"/events/{event.id}/tickets",
        json={"title": "Проверить вход"},
        headers=auth_headers(staff),
    )
    ticket_id = ticket_response.json()["id"]
    queued_notifications: list[dict[str, str]] = []

    async def fake_get_file_path(client, token, file_id):
        return "documents/report.txt"

    async def fake_download_bytes(client, token, file_path):
        return b"ticket document body"

    async def fake_enqueue_notification(payload: dict[str, str]) -> None:
        queued_notifications.append(payload)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr("app.api.integrations._get_telegram_file_path", fake_get_file_path)
    monkeypatch.setattr("app.api.integrations._download_telegram_file_bytes", fake_download_bytes)
    monkeypatch.setattr("app.api.integrations.enqueue_notification", fake_enqueue_notification)

    response = await client.post(
        "/integrations/telegram/webhook",
        json={
            "message": {
                "message_id": 12,
                "from": {"id": 779},
                "chat": {"id": 779},
                "caption": f"ticket #{ticket_id} Отчёт",
                "document": {"file_id": "doc-1", "file_name": "report.txt", "mime_type": "text/plain"},
            }
        },
    )

    assert response.status_code == 200
    assert queued_notifications[0]["message"] == f"Прикрепила документ к задаче #{ticket_id}: Отчёт"
    message = await db_session.scalar(select(Message).where(Message.from_staff_id == staff.id))
    assert message is not None
    assert message.content == "[document] Отчёт"
    db_session.expire_all()
    ticket = await db_session.scalar(select(Ticket).where(Ticket.id == ticket_id))
    assert ticket is not None
    assert ticket.documents[0]["title"] == "Отчёт"
    chunk = await db_session.scalar(select(DocumentChunk).where(DocumentChunk.ticket_id == ticket_id))
    assert chunk is not None
    assert "ticket document body" in chunk.content


async def test_telegram_document_can_upload_to_knowledge_and_be_used_by_rag(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    event = await seed_event(db_session)
    staff = await seed_staff(db_session, event.id, name="Telegram Admin", telegram_id="780", is_admin=True)
    await db_session.commit()
    queued_notifications: list[dict[str, str]] = []

    async def fake_get_file_path(client, token, file_id):
        return "documents/rules.txt"

    async def fake_download_bytes(client, token, file_path):
        return b"unique registration policy"

    async def fake_enqueue_notification(payload: dict[str, str]) -> None:
        queued_notifications.append(payload)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr("app.api.integrations._get_telegram_file_path", fake_get_file_path)
    monkeypatch.setattr("app.api.integrations._download_telegram_file_bytes", fake_download_bytes)
    monkeypatch.setattr("app.api.integrations.enqueue_notification", fake_enqueue_notification)

    response = await client.post(
        "/integrations/telegram/webhook",
        json={
            "message": {
                "message_id": 13,
                "from": {"id": 780},
                "chat": {"id": 780},
                "caption": "kb Регламент регистрации",
                "document": {"file_id": "doc-2", "file_name": "rules.txt", "mime_type": "text/plain"},
            }
        },
    )

    assert response.status_code == 200
    assert "Загрузила документ в базу знаний" in queued_notifications[0]["message"]
    link = await db_session.scalar(select(KnowledgeBaseLink).where(KnowledgeBaseLink.title == "Регламент регистрации"))
    assert link is not None
    chunk = await db_session.scalar(select(DocumentChunk).where(DocumentChunk.knowledge_base_link_id == link.id))
    assert chunk is not None
    assert "unique registration policy" in chunk.content

    search_response = await client.get(
        f"/events/{event.id}/knowledge/search",
        params={"q": "registration"},
        headers=auth_headers(staff),
    )
    assert search_response.status_code == 200
    assert search_response.json()[0]["source_title"] == "Регламент регистрации"


async def test_telegram_photo_kb_upload_extracts_text_for_rag(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    event = await seed_event(db_session)
    staff = await seed_staff(db_session, event.id, name="Telegram Admin", telegram_id="781", is_admin=True)
    await db_session.commit()
    queued_notifications: list[dict[str, str]] = []

    async def fake_get_file_path(client, token, file_id):
        return "photos/image.jpg"

    async def fake_download_bytes(client, token, file_path):
        return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02binary-image"

    async def fake_enqueue_notification(payload: dict[str, str]) -> None:
        queued_notifications.append(payload)

    async def fake_recognize_text(self, *, content, mime_type):
        assert content.startswith(b"\xff\xd8")
        assert mime_type == "image/jpeg"
        return "Схема входа: проход через левую дверь"

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr("app.api.integrations._get_telegram_file_path", fake_get_file_path)
    monkeypatch.setattr("app.api.integrations._download_telegram_file_bytes", fake_download_bytes)
    monkeypatch.setattr("app.api.integrations.enqueue_notification", fake_enqueue_notification)
    monkeypatch.setattr("app.rag.VisionOCRClient.recognize_text", fake_recognize_text)

    response = await client.post(
        "/integrations/telegram/webhook",
        json={
            "message": {
                "message_id": 14,
                "from": {"id": 781},
                "chat": {"id": 781},
                "caption": "kb Схема входа",
                "photo": [{"file_id": "photo-1", "file_size": 100}],
            }
        },
    )

    assert response.status_code == 200
    assert queued_notifications[0]["message"] == "Загрузила документ в базу знаний: Схема входа. Чанков: 1."
    message = await db_session.scalar(select(Message).where(Message.from_staff_id == staff.id))
    assert message is not None
    assert message.content == "[photo] Схема входа"
    link = await db_session.scalar(select(KnowledgeBaseLink).where(KnowledgeBaseLink.title == "Схема входа"))
    assert link is not None
    chunk = await db_session.scalar(select(DocumentChunk).where(DocumentChunk.knowledge_base_link_id == link.id))
    assert chunk is not None
    assert "проход через левую дверь" in chunk.content
