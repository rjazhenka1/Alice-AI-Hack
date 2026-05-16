from __future__ import annotations

import jwt
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ALGORITHM
from app.models import Message

from conftest import auth_headers, seed_event, seed_role, seed_staff


async def test_auth_login_returns_valid_jwt(client: AsyncClient, db_session: AsyncSession):
    event = await seed_event(db_session)
    staff = await seed_staff(
        db_session,
        event.id,
        name="Admin",
        telegram_id="1001",
        is_admin=True,
    )
    await db_session.commit()

    response = await client.post("/auth/login", json={"telegram_id": "1001"})

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

    assert queued_notifications == [
        {
            "telegram_id": "777",
            "message": "Приняла сообщение и передала в штаб.",
        }
    ]
