"""Alice agent orchestration (Variant A PoC)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent.alice import AlicePlanner
from agent.prompts import build_system_prompt
from agent.tools import AgentTools
from models import AgentSession, Event, Role, Staff, StaffStatus, Ticket, TicketAssignment, TicketStatus, Visibility, Zone
from schemas import AgentCommandResponse, AiSuggestion, Ticket as TicketSchema


MAX_SESSION_MESSAGES = 20


def _trim_context(context: list[dict[str, str]]) -> list[dict[str, str]]:
    return context[-MAX_SESSION_MESSAGES:]


async def _get_or_create_session(db: AsyncSession, *, event_id: int, staff_id: int) -> AgentSession:
    result = await db.execute(
        select(AgentSession).where(
            AgentSession.event_id == event_id,
            AgentSession.staff_id == staff_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is not None:
        return session

    session = AgentSession(event_id=event_id, staff_id=staff_id, context=[])
    db.add(session)
    await db.flush()
    return session


async def _load_event_context(db: AsyncSession, *, event_id: int) -> tuple[Event, list[Role], list[Zone], int]:
    event_result = await db.execute(select(Event).where(Event.id == event_id))
    event = event_result.scalar_one_or_none()
    if event is None:
        raise ValueError("Event not found")

    roles_result = await db.execute(select(Role).where(Role.event_id == event_id).order_by(Role.id.asc()))
    zones_result = await db.execute(select(Zone).where(Zone.event_id == event_id).order_by(Zone.id.asc()))
    free_count_result = await db.execute(
        select(Staff).where(
            Staff.event_id == event_id,
            Staff.status == StaffStatus.free,
        )
    )
    free_staff_count = len(list(free_count_result.scalars().all()))

    return event, list(roles_result.scalars().all()), list(zones_result.scalars().all()), free_staff_count


async def _can_see_confidential(db: AsyncSession, staff: Staff) -> bool:
    if staff.is_admin:
        return True
    if staff.role_id is None:
        return False
    role_result = await db.execute(select(Role).where(Role.id == staff.role_id))
    role = role_result.scalar_one_or_none()
    return bool(role and role.can_see_confidential)


async def _ticket_visibility_clause(db: AsyncSession, staff: Staff) -> Any:
    if staff.is_admin:
        return true()

    can_see_confidential = await _can_see_confidential(db, staff)
    return or_(
        Ticket.visibility == Visibility.public,
        and_(Ticket.visibility == Visibility.role_only, Ticket.assignee_role_id == staff.role_id),
        and_(
            Ticket.visibility == Visibility.confidential,
            true() if can_see_confidential else false(),
        ),
    )


async def _load_ticket_for_response(db: AsyncSession, *, event_id: int, ticket_id: int) -> Ticket | None:
    result = await db.execute(
        select(Ticket)
        .options(selectinload(Ticket.assignments).selectinload(TicketAssignment.staff))
        .where(Ticket.event_id == event_id, Ticket.id == ticket_id)
    )
    return result.scalar_one_or_none()


def _serialize_ticket(ticket: Ticket | None) -> TicketSchema | None:
    if ticket is None:
        return None
    return TicketSchema.model_validate(ticket)


async def handle_command(
    *,
    db: AsyncSession,
    event_id: int,
    current_staff: Staff,
    text: str,
) -> AgentCommandResponse:
    session = await _get_or_create_session(db, event_id=event_id, staff_id=current_staff.id)
    tools = AgentTools(db=db, event_id=event_id, current_staff=current_staff)
    planner = AlicePlanner()

    event, roles, zones, free_staff_count = await _load_event_context(db, event_id=event_id)
    system_prompt = build_system_prompt(
        event_name=event.name,
        event_description=event.description,
        roles=roles,
        zones=zones,
        free_staff_count=free_staff_count,
    )

    context = list(session.context or [])
    context.append({"role": "user", "text": text})

    planned = await planner.plan(text, system_prompt=system_prompt)

    if planned.kind == "clarification":
        response = AgentCommandResponse(action="question_asked", message=planned.message)
    elif planned.kind == "answered":
        response = AgentCommandResponse(action="answered", message=planned.message)
    elif planned.kind == "informational":
        visible_clause = await _ticket_visibility_clause(db, current_staff)
        ticket_result = await db.execute(
            select(Ticket)
            .where(Ticket.event_id == event_id)
            .where(visible_clause)
            .order_by(Ticket.updated_at.desc())
            .limit(5)
        )
        tickets = list(ticket_result.scalars().all())
        if not tickets:
            response = AgentCommandResponse(action="answered", message="Сейчас активных тикетов не найдено.")
        else:
            lines = [f"- #{t.id} {t.title} ({t.status.value})" for t in tickets]
            response = AgentCommandResponse(
                action="answered",
                message="Текущая сводка:\n" + "\n".join(lines),
            )
    else:
        free_staff = await tools.get_free_staff(limit=2)
        suggested_ids = [member.id for member in free_staff]
        suggested_names = [member.name for member in free_staff]

        reasoning = (
            f"Рекомендую {', '.join(suggested_names)} — они свободны сейчас."
            if suggested_names
            else "Свободные исполнители не найдены, требуется ручное назначение."
        )
        ai_suggestion = {
            "reasoning": reasoning,
            "suggested_staff_ids": suggested_ids,
            "confidence": "medium" if suggested_ids else "low",
        }
        created_ticket = await tools.create_ticket(
            title=planned.title or "Операционная задача",
            description=planned.description,
            ai_suggestion=ai_suggestion,
        )
        ticket_for_response = await _load_ticket_for_response(db, event_id=event_id, ticket_id=created_ticket.id)

        response = AgentCommandResponse(
            action="ticket_created",
            message=f"Создал задачу: {created_ticket.title}",
            suggestion=AiSuggestion(
                reasoning=reasoning,
                suggested_staff_ids=suggested_ids,
                confidence="medium" if suggested_ids else "low",
                ticket_id=created_ticket.id,
            ),
            ticket=_serialize_ticket(ticket_for_response),
        )

    context.append({"role": "assistant", "text": response.message})
    session.context = _trim_context(context)
    await db.commit()
    return response


async def confirm_ticket(
    *,
    db: AsyncSession,
    event_id: int,
    current_staff: Staff,
    ticket_id: int,
    accept: bool,
    staff_ids: list[int] | None,
) -> TicketSchema:
    tools = AgentTools(db=db, event_id=event_id, current_staff=current_staff)
    ticket_result = await db.execute(
        select(Ticket)
        .options(selectinload(Ticket.assignments).selectinload(TicketAssignment.staff))
        .where(Ticket.event_id == event_id, Ticket.id == ticket_id)
    )
    ticket = ticket_result.scalar_one_or_none()
    if ticket is None:
        raise ValueError("Ticket not found")

    if accept:
        suggested_ids = []
        if isinstance(ticket.ai_suggestion, dict):
            raw = ticket.ai_suggestion.get("suggested_staff_ids") or []
            if isinstance(raw, list):
                suggested_ids = [int(v) for v in raw if isinstance(v, int)]

        final_staff_ids = list(staff_ids or suggested_ids)
        ticket = await tools.assign_staff(ticket=ticket, staff_ids=final_staff_ids)

        if final_staff_ids:
            staff_result = await db.execute(
                select(Staff).where(
                    Staff.event_id == event_id,
                    Staff.id.in_(final_staff_ids),
                )
            )
            for staff in staff_result.scalars().all():
                if staff.telegram_id:
                    await tools.send_notification(
                        telegram_id=staff.telegram_id,
                        message=f"Новая задача: {ticket.title}",
                    )
    else:
        ticket.status = TicketStatus.waiting

    await db.commit()
    refreshed_ticket = await _load_ticket_for_response(db, event_id=event_id, ticket_id=ticket.id)
    if refreshed_ticket is None:
        raise ValueError("Ticket disappeared after confirmation")
    return TicketSchema.model_validate(refreshed_ticket)
