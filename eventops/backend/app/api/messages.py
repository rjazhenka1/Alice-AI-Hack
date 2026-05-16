from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import schemas
from ..auth import get_current_staff
from ..database import get_db
from ..models import Message, Role, Staff, Visibility
from ..notifier import enqueue_notification

router = APIRouter(prefix="/events/{event_id}/messages", tags=["messages"])


def _serialize_message(message: Message) -> schemas.Message:
    return schemas.Message.model_validate(message)


def _visible_message_filter(current_staff: Staff):
    confidential_allowed: Any = current_staff.is_admin
    if current_staff.role_id is not None:
        confidential_allowed = or_(
            current_staff.is_admin,
            exists().where(
                and_(
                    Role.id == current_staff.role_id,
                    Role.can_see_confidential.is_(True),
                )
            ),
        )

    visibility_filter: Any = Message.visibility == Visibility.public
    if current_staff.role_id is not None:
        visibility_filter = or_(
            visibility_filter,
            and_(
                Message.visibility == Visibility.role_only,
                Message.to_role_id == current_staff.role_id,
            ),
            and_(
                Message.visibility == Visibility.role_only,
                Message.from_staff_id == current_staff.id,
            ),
        )
    if confidential_allowed is True:
        visibility_filter = or_(visibility_filter, Message.visibility == Visibility.confidential)
    elif confidential_allowed is not False:
        visibility_filter = or_(
            visibility_filter,
            and_(Message.visibility == Visibility.confidential, confidential_allowed),
        )

    return and_(
        Message.event_id == current_staff.event_id,
        or_(
            visibility_filter,
            Message.to_staff_id == current_staff.id,
            Message.from_staff_id == current_staff.id,
        ),
    )


async def _ensure_event_access(event_id: int, current_staff: Staff) -> None:
    if current_staff.event_id != event_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this event",
        )


async def _message_targets(
    db: AsyncSession,
    event_id: int,
    message: schemas.MessageCreate,
) -> list[Staff]:
    if message.to_staff_id is not None:
        staff = await db.scalar(
            select(Staff).where(Staff.id == message.to_staff_id, Staff.event_id == event_id)
        )
        if staff is None:
            raise HTTPException(status_code=404, detail="Target staff not found")
        return [staff]

    if message.to_role_id is not None:
        role = await db.scalar(
            select(Role).where(Role.id == message.to_role_id, Role.event_id == event_id)
        )
        if role is None:
            raise HTTPException(status_code=404, detail="Target role not found")
        result = await db.scalars(
            select(Staff).where(Staff.event_id == event_id, Staff.role_id == message.to_role_id)
        )
        return list(result)

    result = await db.scalars(select(Staff).where(Staff.event_id == event_id))
    return list(result)


async def _enqueue_message_delivery(
    targets: list[Staff],
    sender: Staff,
    content: str,
) -> None:
    text = f"{sender.name}: {content}"
    for staff in targets:
        if staff.id == sender.id:
            continue
        if not staff.telegram_id:
            continue
        await enqueue_notification(
            {
                "telegram_id": staff.telegram_id,
                "message": text,
            }
        )


@router.get("", response_model=list[schemas.Message])
async def list_messages(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> list[Message]:
    await _ensure_event_access(event_id, current_staff)
    result = await db.scalars(
        select(Message)
        .options(selectinload(Message.from_staff).selectinload(Staff.role))
        .where(_visible_message_filter(current_staff))
        .order_by(Message.created_at.desc(), Message.id.desc())
    )
    return [_serialize_message(item) for item in result]


@router.post("", response_model=schemas.Message, status_code=status.HTTP_201_CREATED)
async def create_message(
    event_id: int,
    payload: schemas.MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Message:
    await _ensure_event_access(event_id, current_staff)
    targets = await _message_targets(db, event_id, payload)
    message = Message(
        event_id=event_id,
        from_staff_id=current_staff.id,
        to_staff_id=payload.to_staff_id,
        to_role_id=payload.to_role_id,
        content=payload.content,
        visibility=payload.visibility,
    )
    db.add(message)
    await db.commit()
    message = await db.scalar(
        select(Message)
        .options(selectinload(Message.from_staff).selectinload(Staff.role))
        .where(Message.id == message.id)
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found after create")
    await _enqueue_message_delivery(targets, current_staff, payload.content)
    return _serialize_message(message)


@router.patch("/{message_id}/read", response_model=schemas.Message)
async def mark_message_read(
    event_id: int,
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Message:
    await _ensure_event_access(event_id, current_staff)
    message = await db.scalar(
        select(Message)
        .options(selectinload(Message.from_staff).selectinload(Staff.role))
        .where(
            Message.id == message_id,
            Message.event_id == event_id,
            _visible_message_filter(current_staff),
        )
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    message.is_read = True  # type: ignore[assignment]
    await db.commit()
    return _serialize_message(message)
