from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Message, Role, Staff, Ticket, Visibility


async def ensure_event_access(event_id: int, current_staff: Staff) -> None:
    if current_staff.event_id != event_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this event")


async def can_see_confidential(db: AsyncSession, staff: Staff) -> bool:
    if staff.is_admin:
        return True
    if staff.role_id is None:
        return False
    result = await db.execute(select(Role.can_see_confidential).where(Role.id == staff.role_id))
    return bool(result.scalar_one_or_none())


async def ticket_visibility_filter(db: AsyncSession, staff: Staff) -> Any:
    if staff.is_admin:
        return true()

    confidential_allowed = await can_see_confidential(db, staff)
    return or_(
        Ticket.visibility == Visibility.public,
        and_(Ticket.visibility == Visibility.role_only, Ticket.assignee_role_id == staff.role_id),
        and_(Ticket.visibility == Visibility.confidential, true() if confidential_allowed else false()),
        Ticket.created_by_id == staff.id,
        Ticket.assignments.any(staff_id=staff.id),
    )


async def message_visibility_filter(db: AsyncSession, staff: Staff) -> Any:
    confidential_allowed = await can_see_confidential(db, staff)
    return or_(
        Message.visibility == Visibility.public,
        Message.to_staff_id == staff.id,
        Message.from_staff_id == staff.id,
        and_(Message.visibility == Visibility.role_only, Message.to_role_id == staff.role_id),
        and_(Message.visibility == Visibility.confidential, true() if confidential_allowed else false()),
    )
