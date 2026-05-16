from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, false, select, true
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import schemas
from ..auth import get_current_staff
from ..database import get_db
from ..models import Role, Staff, StaffStatus, Ticket, TicketAssignment, TicketPriority, TicketReply, TicketStatus, Visibility
from ..notifier import enqueue_notification, format_task_notification
from .common import can_see_confidential, ensure_event_access, ticket_visibility_filter

router = APIRouter(prefix="/events/{event_id}/tickets", tags=["tickets"])


def _priority_order():
    return case(
        (Ticket.priority == TicketPriority.critical, 0),
        (Ticket.priority == TicketPriority.high, 1),
        (Ticket.priority == TicketPriority.medium, 2),
        else_=3,
    )


async def _load_ticket(db: AsyncSession, event_id: int, ticket_id: int) -> Ticket | None:
    return await db.scalar(
        select(Ticket)
        .options(
            selectinload(Ticket.created_by),
            selectinload(Ticket.assignments).selectinload(TicketAssignment.staff),
        )
        .where(Ticket.id == ticket_id, Ticket.event_id == event_id)
    )


async def _load_visible_ticket(
    db: AsyncSession,
    event_id: int,
    ticket_id: int,
    current_staff: Staff,
) -> Ticket | None:
    visible_clause = await ticket_visibility_filter(db, current_staff)
    return await db.scalar(
        select(Ticket)
        .options(
            selectinload(Ticket.created_by),
            selectinload(Ticket.assignments).selectinload(TicketAssignment.staff),
        )
        .where(Ticket.id == ticket_id, Ticket.event_id == event_id)
        .where(visible_clause)
    )


async def _ensure_role(db: AsyncSession, event_id: int, role_id: int | None) -> None:
    if role_id is None:
        return
    role = await db.scalar(select(Role).where(Role.id == role_id, Role.event_id == event_id))
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")


async def _ensure_can_use_visibility(db: AsyncSession, current_staff: Staff, visibility: Visibility) -> None:
    if visibility != Visibility.confidential:
        return
    if not await can_see_confidential(db, current_staff):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to confidential visibility")


async def _reply_visibility_filter(db: AsyncSession, current_staff: Staff) -> ColumnElement[bool]:
    if current_staff.is_admin:
        return TicketReply.id.is_not(None)
    confidential_allowed = await can_see_confidential(db, current_staff)
    return (
        (TicketReply.visibility == Visibility.public)
        | (TicketReply.from_staff_id == current_staff.id)
        | ((TicketReply.visibility == Visibility.confidential) & (true() if confidential_allowed else false()))
    )


@router.get("", response_model=list[schemas.Ticket])
async def list_tickets(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> list[Ticket]:
    await ensure_event_access(event_id, current_staff)
    visible_clause = await ticket_visibility_filter(db, current_staff)
    result = await db.scalars(
        select(Ticket)
        .options(
            selectinload(Ticket.created_by),
            selectinload(Ticket.assignments).selectinload(TicketAssignment.staff),
        )
        .where(Ticket.event_id == event_id)
        .where(visible_clause)
        .order_by(_priority_order(), Ticket.updated_at.desc(), Ticket.id.desc())
    )
    return list(result.all())


@router.post("", response_model=schemas.Ticket, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    event_id: int,
    payload: schemas.TicketCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Ticket:
    await ensure_event_access(event_id, current_staff)
    await _ensure_role(db, event_id, payload.assignee_role_id)
    await _ensure_can_use_visibility(db, current_staff, payload.visibility)

    data = payload.model_dump()
    previous_messages = data.pop("previous_messages", None)
    ticket = Ticket(event_id=event_id, created_by_id=current_staff.id, **data)
    ticket.previous_messages = previous_messages
    db.add(ticket)
    await db.commit()
    loaded = await _load_ticket(db, event_id, ticket.id)
    return loaded or ticket


@router.patch("/{ticket_id}", response_model=schemas.Ticket)
async def update_ticket(
    event_id: int,
    ticket_id: int,
    payload: schemas.TicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Ticket:
    await ensure_event_access(event_id, current_staff)
    visible_clause = await ticket_visibility_filter(db, current_staff)
    ticket = await db.scalar(
        select(Ticket)
        .options(selectinload(Ticket.created_by))
        .where(Ticket.id == ticket_id, Ticket.event_id == event_id)
        .where(visible_clause)
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not current_staff.is_admin and ticket.created_by_id != current_staff.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin or creator can update ticket")

    data = payload.model_dump(exclude_unset=True)
    if "assignee_role_id" in data:
        await _ensure_role(db, event_id, data["assignee_role_id"])
    if "visibility" in data:
        await _ensure_can_use_visibility(db, current_staff, data["visibility"])
    previous_messages = data.pop("previous_messages", None)
    for key, value in data.items():
        setattr(ticket, key, value)
    if previous_messages is not None:
        ticket.previous_messages = previous_messages

    await db.commit()
    loaded = await _load_ticket(db, event_id, ticket.id)
    return loaded or ticket


@router.get("/{ticket_id}/replies", response_model=list[schemas.TicketReply])
async def list_ticket_replies(
    event_id: int,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> list[TicketReply]:
    await ensure_event_access(event_id, current_staff)
    ticket = await _load_visible_ticket(db, event_id, ticket_id, current_staff)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    result = await db.scalars(
        select(TicketReply)
        .options(selectinload(TicketReply.from_staff))
        .where(TicketReply.event_id == event_id, TicketReply.ticket_id == ticket_id)
        .where(await _reply_visibility_filter(db, current_staff))
        .order_by(TicketReply.created_at.asc(), TicketReply.id.asc())
    )
    return list(result.all())


@router.post("/{ticket_id}/replies", response_model=schemas.TicketReply, status_code=status.HTTP_201_CREATED)
async def create_ticket_reply(
    event_id: int,
    ticket_id: int,
    payload: schemas.TicketReplyCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> TicketReply:
    await ensure_event_access(event_id, current_staff)
    ticket = await _load_visible_ticket(db, event_id, ticket_id, current_staff)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    await _ensure_can_use_visibility(db, current_staff, payload.visibility)

    reply = TicketReply(
        event_id=event_id,
        ticket_id=ticket_id,
        from_staff_id=current_staff.id,
        content=payload.content,
        visibility=payload.visibility,
    )
    db.add(reply)
    ticket.updated_at = reply.created_at
    await db.commit()
    loaded = await db.scalar(
        select(TicketReply)
        .options(selectinload(TicketReply.from_staff))
        .where(TicketReply.id == reply.id)
    )
    return loaded or reply


@router.post("/{ticket_id}/assign", response_model=schemas.Ticket)
async def assign_ticket(
    event_id: int,
    ticket_id: int,
    payload: schemas.AssignRequest,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Ticket:
    await ensure_event_access(event_id, current_staff)
    if not current_staff.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can assign tickets")
    ticket = await _load_ticket(db, event_id, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    staff_result = await db.scalars(select(Staff).where(Staff.event_id == event_id, Staff.id.in_(payload.staff_ids)))
    staff_list = list(staff_result.all())
    found_ids = {staff.id for staff in staff_list}
    missing_ids = set(payload.staff_ids) - found_ids
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Staff not found: {sorted(missing_ids)}")

    existing_ids = {assignment.staff_id for assignment in ticket.assignments}
    for staff in staff_list:
        if staff.id in existing_ids:
            continue
        db.add(TicketAssignment(ticket_id=ticket.id, staff_id=staff.id, confirmed=False))
        staff.status = StaffStatus.on_task
        if staff.telegram_id:
            await enqueue_notification(
                {
                    "telegram_id": staff.telegram_id,
                    "message": format_task_notification(
                        ticket_id=ticket.id,
                        title=ticket.title,
                        description=ticket.description,
                    ),
                }
            )

    ticket.status = TicketStatus.in_progress
    await db.commit()
    loaded = await _load_ticket(db, event_id, ticket.id)
    return loaded or ticket


@router.patch("/{ticket_id}/assignments/{assignment_id}", response_model=schemas.TicketAssignmentOut)
async def confirm_assignment(
    event_id: int,
    ticket_id: int,
    assignment_id: int,
    payload: schemas.ConfirmAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> TicketAssignment:
    await ensure_event_access(event_id, current_staff)
    assignment = await db.scalar(
        select(TicketAssignment)
        .options(selectinload(TicketAssignment.staff))
        .join(Ticket, Ticket.id == TicketAssignment.ticket_id)
        .where(Ticket.event_id == event_id, Ticket.id == ticket_id, TicketAssignment.id == assignment_id)
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if not current_staff.is_admin and assignment.staff_id != current_staff.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only assignee or admin can confirm assignment")

    assignment.confirmed = payload.confirmed
    if payload.confirmed:
        assignment.staff.status = StaffStatus.on_task
    await db.commit()
    await db.refresh(assignment)
    return assignment
