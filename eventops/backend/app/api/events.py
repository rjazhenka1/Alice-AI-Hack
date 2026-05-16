from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import schemas
from ..auth import get_current_staff
from ..database import get_db
from ..models import Event, Role, Staff, Ticket, TicketAssignment, TicketStatus, Zone
from .common import ensure_event_access, ticket_visibility_filter

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[schemas.Event])
async def list_events(
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> list[Event]:
    event = await db.get(Event, current_staff.event_id)
    return [event] if event is not None else []


@router.post("", response_model=schemas.Event, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: schemas.EventCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Event:
    if not current_staff.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can create events")
    event = Event(**payload.model_dump())
    db.add(event)
    await db.flush()
    current_staff.event_id = event.id
    await db.commit()
    await db.refresh(event)
    return event


@router.get("/{event_id}", response_model=schemas.Event)
async def get_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Event:
    await ensure_event_access(event_id, current_staff)
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/{event_id}/summary", response_model=schemas.EventSummary)
async def get_event_summary(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> schemas.EventSummary:
    await ensure_event_access(event_id, current_staff)
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    zones = list((await db.scalars(select(Zone).where(Zone.event_id == event_id))).all())
    roles = list((await db.scalars(select(Role).where(Role.event_id == event_id))).all())
    staff = list(
        (
            await db.scalars(
                select(Staff)
                .options(selectinload(Staff.role), selectinload(Staff.zone))
                .where(Staff.event_id == event_id)
            )
        ).all()
    )
    visible_clause = await ticket_visibility_filter(db, current_staff)
    open_tickets = list(
        (
            await db.scalars(
                select(Ticket)
                .options(
                    selectinload(Ticket.created_by),
                    selectinload(Ticket.assignments).selectinload(TicketAssignment.staff),
                )
                .where(Ticket.event_id == event_id, Ticket.status.not_in([TicketStatus.closed, TicketStatus.resolved]))
                .where(visible_clause)
                .order_by(Ticket.updated_at.desc())
            )
        ).all()
    )
    return schemas.EventSummary(event=event, zones=zones, roles=roles, staff=staff, open_tickets=open_tickets)
