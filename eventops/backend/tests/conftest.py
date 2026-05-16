from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth import create_access_token
from app.database import get_db
from app.main import app
from app.models import Base, Event, Role, Staff, StaffStatus


@pytest.fixture
async def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncSession, None]:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_async_engine(db_url, future=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    async with session_factory() as session:
        yield session

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


async def seed_event(db: AsyncSession, name: str = "ICPC Semifinal") -> Event:
    event = Event(name=name)
    db.add(event)
    await db.flush()
    return event


async def seed_role(
    db: AsyncSession,
    event_id: int,
    name: str = "Регистрация",
    *,
    can_see_confidential: bool = False,
) -> Role:
    role = Role(
        event_id=event_id,
        name=name,
        ai_prompt=f"{name} role",
        can_see_confidential=can_see_confidential,
    )
    db.add(role)
    await db.flush()
    return role


async def seed_staff(
    db: AsyncSession,
    event_id: int,
    name: str = "Coordinator",
    *,
    telegram_id: str | None = None,
    role_id: int | None = None,
    is_admin: bool = False,
) -> Staff:
    staff = Staff(
        event_id=event_id,
        name=name,
        telegram_id=telegram_id,
        role_id=role_id,
        status=StaffStatus.free,
        is_admin=is_admin,
    )
    db.add(staff)
    await db.flush()
    return staff


def auth_headers(staff: Staff) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(staff.id)})}"}
