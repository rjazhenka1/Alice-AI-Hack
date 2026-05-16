"""Lightweight auth for PoC: login by Telegram username and bearer token by staff id."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from . import schemas
from .models import Event, Staff, StaffStatus


ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer(auto_error=True)
router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_username(value: str | None) -> str:
    return (value or "").strip().lstrip("@").lower()


def _display_username(value: str) -> str:
    normalized = _normalize_username(value)
    return f"@{normalized}" if normalized else ""


def _secret_key() -> str:
    return os.getenv("SECRET_KEY", "dev-secret-key-change-me")


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, _secret_key(), algorithm=ALGORITHM)


async def get_current_staff(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Staff:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
        subject = payload.get("sub")
        if subject is None:
            raise ValueError("Token subject is missing")
        staff_id = int(subject)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    result = await db.execute(select(Staff).where(Staff.id == staff_id))
    staff = result.scalar_one_or_none()
    if staff is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Staff not found")
    return staff


@router.post("/login", response_model=schemas.TokenResponse)
async def login(
    payload: schemas.LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> schemas.TokenResponse:
    username = _normalize_username(payload.telegram_username or payload.telegram_id)
    if not username:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Telegram username is required")

    result = await db.execute(
        select(Staff)
        .where(func.lower(Staff.telegram_username) == username)
        .order_by(Staff.is_admin.desc(), Staff.id.asc())
    )
    staff = result.scalars().first()
    if staff is None:
        admin_username = _normalize_username(os.getenv("ADMIN_TELEGRAM_USERNAME"))
        if username and admin_username and username == admin_username:
            existing_admin = await db.scalar(
                select(Staff).where(Staff.is_admin.is_(True)).order_by(Staff.id.asc())
            )
            if existing_admin is not None:
                existing_admin.telegram_username = username
                if not existing_admin.name:
                    existing_admin.name = _display_username(username)
                staff = existing_admin
            else:
                event = Event(name="Первое мероприятие", description="Создано автоматически для первого администратора")
                db.add(event)
                await db.flush()
                staff = Staff(
                    event_id=event.id,
                    name=_display_username(username),
                    telegram_username=username,
                    is_admin=True,
                    status=StaffStatus.free,
                )
                db.add(staff)
            await db.commit()
            await db.refresh(staff)

    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff not found")

    return schemas.TokenResponse(
        access_token=create_access_token({"sub": str(staff.id)}),
        staff_id=staff.id,
        is_admin=staff.is_admin,
    )


@router.get("/me", response_model=schemas.TokenResponse)
async def me(current_staff: Staff = Depends(get_current_staff)) -> schemas.TokenResponse:
    return schemas.TokenResponse(
        access_token="",
        staff_id=current_staff.id,
        is_admin=current_staff.is_admin,
    )
