"""Tool handlers for Alice router PoC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Role,
    Staff,
    StaffStatus,
    Ticket,
    TicketAssignment,
    TicketPriority,
    TicketStatus,
    TicketType,
    Visibility,
)


def _visibility_filter_for_staff(staff: Staff) -> Any:
    if staff.is_admin:
        return true()

    role_id = staff.role_id
    can_see_confidential = bool(getattr(getattr(staff, "role", None), "can_see_confidential", False))

    allow_confidential = and_(
        Ticket.visibility == Visibility.confidential,
        true() if can_see_confidential else false(),
    )

    return or_(
        Ticket.visibility == Visibility.public,
        and_(Ticket.visibility == Visibility.role_only, Ticket.assignee_role_id == role_id),
        allow_confidential,
    )


@dataclass(slots=True)
class AgentTools:
    db: AsyncSession
    event_id: int
    current_staff: Staff

    async def get_free_staff(self, *, role_id: int | None = None, zone_id: int | None = None, limit: int = 10) -> list[Staff]:
        query: Select[Any] = select(Staff).where(
            Staff.event_id == self.event_id,
            Staff.status == StaffStatus.free,
        )
        if role_id is not None:
            query = query.where(Staff.role_id == role_id)
        if zone_id is not None:
            query = query.where(Staff.zone_id == zone_id)

        query = query.limit(max(1, min(limit, 50)))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_ticket(
        self,
        *,
        title: str,
        description: str | None,
        ticket_type: TicketType = TicketType.incident,
        priority: TicketPriority = TicketPriority.medium,
        visibility: Visibility = Visibility.public,
        assignee_role_id: int | None = None,
        ai_suggestion: dict[str, Any] | None = None,
    ) -> Ticket:
        ticket = Ticket(
            event_id=self.event_id,
            title=title,
            description=description,
            type=ticket_type,
            priority=priority,
            status=TicketStatus.waiting,
            visibility=visibility,
            created_by_id=self.current_staff.id,
            assignee_role_id=assignee_role_id,
            ai_suggestion=ai_suggestion,
        )
        self.db.add(ticket)
        await self.db.flush()
        await self.db.refresh(ticket)
        return ticket

    async def assign_staff(self, *, ticket: Ticket, staff_ids: list[int]) -> Ticket:
        unique_staff_ids = list(dict.fromkeys(staff_ids))
        if not unique_staff_ids:
            return ticket

        existing_assignments = await self.db.execute(
            select(TicketAssignment.staff_id).where(TicketAssignment.ticket_id == ticket.id)
        )
        already_assigned = set(existing_assignments.scalars().all())

        staff_result = await self.db.execute(
            select(Staff).where(
                Staff.event_id == self.event_id,
                Staff.id.in_(unique_staff_ids),
            )
        )
        staff_list = list(staff_result.scalars().all())

        for staff in staff_list:
            if staff.id in already_assigned:
                continue
            self.db.add(TicketAssignment(ticket_id=ticket.id, staff_id=staff.id, confirmed=False))
            staff.status = StaffStatus.on_task

        ticket.status = TicketStatus.in_progress
        await self.db.flush()
        await self.db.refresh(ticket)
        return ticket

    async def get_ticket_list(self) -> list[Ticket]:
        query = (
            select(Ticket)
            .where(Ticket.event_id == self.event_id)
            .where(_visibility_filter_for_staff(self.current_staff))
            .order_by(Ticket.updated_at.desc())
            .limit(50)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def send_notification(self, *, telegram_id: str, message: str) -> None:
        try:
            from notifier import enqueue_notification  # type: ignore

            await enqueue_notification({"telegram_id": telegram_id, "message": message})
            return
        except Exception:
            pass

        try:
            from app.notifier import enqueue_notification  # type: ignore

            await enqueue_notification({"telegram_id": telegram_id, "message": message})
            return
        except Exception:
            # notifier module may be implemented by another owner; PoC keeps soft-fail.
            return

    @staticmethod
    def ask_clarification(question: str) -> dict[str, str]:
        return {"question": question}
