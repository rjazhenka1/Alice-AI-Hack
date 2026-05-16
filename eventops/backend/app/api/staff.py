from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import schemas
from ..auth import get_current_staff
from ..database import get_db
from ..models import Message, Role, Staff, StaffStatus, Ticket, TicketAssignment, Zone
from .common import ensure_event_access, message_visibility_filter, ticket_visibility_filter

router = APIRouter(prefix="/events/{event_id}", tags=["staff"])


def _require_admin(current_staff: Staff) -> None:
    if not current_staff.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can modify event setup")


async def _ensure_role(db: AsyncSession, event_id: int, role_id: int | None) -> None:
    if role_id is None:
        return
    role = await db.scalar(select(Role).where(Role.id == role_id, Role.event_id == event_id))
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")


async def _ensure_zone(db: AsyncSession, event_id: int, zone_id: int | None) -> None:
    if zone_id is None:
        return
    zone = await db.scalar(select(Zone).where(Zone.id == zone_id, Zone.event_id == event_id))
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")


@router.get("/staff", response_model=list[schemas.Staff])
async def list_staff(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> list[Staff]:
    await ensure_event_access(event_id, current_staff)
    result = await db.scalars(
        select(Staff)
        .options(selectinload(Staff.role), selectinload(Staff.zone))
        .where(Staff.event_id == event_id)
        .order_by(Staff.id.asc())
    )
    return list(result.all())


@router.post("/staff", response_model=schemas.Staff, status_code=status.HTTP_201_CREATED)
async def create_staff(
    event_id: int,
    payload: schemas.StaffCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Staff:
    await ensure_event_access(event_id, current_staff)
    _require_admin(current_staff)
    await _ensure_role(db, event_id, payload.role_id)
    await _ensure_zone(db, event_id, payload.zone_id)

    staff = Staff(event_id=event_id, **payload.model_dump())
    db.add(staff)
    await db.commit()
    result = await db.scalar(
        select(Staff).options(selectinload(Staff.role), selectinload(Staff.zone)).where(Staff.id == staff.id)
    )
    return result or staff


@router.patch("/staff/{staff_id}", response_model=schemas.Staff)
async def update_staff(
    event_id: int,
    staff_id: int,
    payload: schemas.StaffUpdate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Staff:
    await ensure_event_access(event_id, current_staff)
    _require_admin(current_staff)
    staff = await db.scalar(select(Staff).where(Staff.id == staff_id, Staff.event_id == event_id))
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff not found")

    data = payload.model_dump(exclude_unset=True)
    await _ensure_role(db, event_id, data.get("role_id"))
    await _ensure_zone(db, event_id, data.get("zone_id"))
    for key, value in data.items():
        setattr(staff, key, value)

    await db.commit()
    result = await db.scalar(
        select(Staff).options(selectinload(Staff.role), selectinload(Staff.zone)).where(Staff.id == staff.id)
    )
    return result or staff


@router.get("/staff/free", response_model=schemas.FreeStaffResponse)
async def list_free_staff(
    event_id: int,
    role_id: int | None = None,
    zone_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> schemas.FreeStaffResponse:
    await ensure_event_access(event_id, current_staff)
    query = (
        select(Staff)
        .options(selectinload(Staff.role), selectinload(Staff.zone))
        .where(Staff.event_id == event_id, Staff.status == StaffStatus.free)
    )
    if role_id is not None:
        query = query.where(Staff.role_id == role_id)
    if zone_id is not None:
        query = query.where(Staff.zone_id == zone_id)
    free_staff = list((await db.scalars(query.order_by(Staff.id.asc()))).all())
    total_staff = await db.scalar(select(func.count(Staff.id)).where(Staff.event_id == event_id))
    return schemas.FreeStaffResponse(staff=free_staff, total_free=len(free_staff), total_staff=int(total_staff or 0))


@router.get("/staff/{staff_id}/context", response_model=schemas.MyContext)
async def get_staff_context(
    event_id: int,
    staff_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> schemas.MyContext:
    await ensure_event_access(event_id, current_staff)
    if not current_staff.is_admin and current_staff.id != staff_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this staff context")

    target = await db.scalar(select(Staff).where(Staff.id == staff_id, Staff.event_id == event_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Staff not found")

    visible_tickets = await ticket_visibility_filter(db, current_staff)
    my_tickets = list(
        (
            await db.scalars(
                select(Ticket)
                .options(
                    selectinload(Ticket.created_by),
                    selectinload(Ticket.assignments).selectinload(TicketAssignment.staff),
                )
                .where(Ticket.event_id == event_id)
                .where(visible_tickets)
                .where(Ticket.assignments.any(staff_id=staff_id))
                .order_by(Ticket.updated_at.desc())
            )
        ).all()
    )
    role_tickets = []
    if target.role_id is not None:
        role_tickets = list(
            (
                await db.scalars(
                    select(Ticket)
                    .options(
                        selectinload(Ticket.created_by),
                        selectinload(Ticket.assignments).selectinload(TicketAssignment.staff),
                    )
                    .where(Ticket.event_id == event_id, Ticket.assignee_role_id == target.role_id)
                    .where(visible_tickets)
                    .order_by(Ticket.updated_at.desc())
                )
            ).all()
        )

    visible_messages = await message_visibility_filter(db, current_staff)
    my_messages = list(
        (
            await db.scalars(
                select(Message)
                .where(Message.event_id == event_id)
                .where(visible_messages)
                .where(or_(Message.to_staff_id == staff_id, Message.from_staff_id == staff_id, Message.to_role_id == target.role_id))
                .order_by(Message.created_at.desc())
            )
        ).all()
    )
    return schemas.MyContext(my_tickets=my_tickets, my_messages=my_messages, role_tickets=role_tickets)


@router.get("/roles", response_model=list[schemas.Role])
async def list_roles(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> list[Role]:
    await ensure_event_access(event_id, current_staff)
    return list((await db.scalars(select(Role).where(Role.event_id == event_id).order_by(Role.id.asc()))).all())


@router.post("/roles", response_model=schemas.Role, status_code=status.HTTP_201_CREATED)
async def create_role(
    event_id: int,
    payload: schemas.RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Role:
    await ensure_event_access(event_id, current_staff)
    _require_admin(current_staff)
    role = Role(event_id=event_id, **payload.model_dump())
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


@router.get("/zones", response_model=list[schemas.Zone])
async def list_zones(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> list[Zone]:
    await ensure_event_access(event_id, current_staff)
    return list((await db.scalars(select(Zone).where(Zone.event_id == event_id).order_by(Zone.id.asc()))).all())


@router.post("/zones", response_model=schemas.Zone, status_code=status.HTTP_201_CREATED)
async def create_zone(
    event_id: int,
    payload: schemas.ZoneCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> Zone:
    await ensure_event_access(event_id, current_staff)
    _require_admin(current_staff)
    zone = Zone(event_id=event_id, **payload.model_dump())
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return zone
