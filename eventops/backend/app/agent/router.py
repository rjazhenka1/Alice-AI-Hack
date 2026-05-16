"""Alice agent orchestration (Variant A PoC)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .alice import AlicePlanner
from .prompts import build_system_prompt
from .tools import AgentTools
from ..models import (
    AgentSession,
    ConfidentialityRule,
    Event,
    KnowledgeBaseLink,
    Role,
    Staff,
    StaffStatus,
    Ticket,
    TicketAssignment,
    TicketStatus,
    Visibility,
    Zone,
)
from ..schemas import AgentCommandResponse, AiSuggestion, Ticket as TicketSchema


MAX_SESSION_MESSAGES = 20
IMPRECISE_SECOND_PASS_INSTRUCTION = (
    "Если запрос расплывчатый, верни kind=clarification и ровно один конкретный уточняющий вопрос. "
    "Не предлагай действий и не создавай задачу."
)
IMPRECISE_FALLBACK_QUESTION = "Уточни, пожалуйста, что именно нужно сделать, где и в какой срок."


def _trim_context(context: list[dict[str, str]]) -> list[dict[str, str]]:
    return context[-MAX_SESSION_MESSAGES:]


def _message_record(*, role: str, text: str, audio_file: str | None = None, source: str | None = None) -> dict[str, str]:
    record = {"role": role, "text": text}
    if audio_file:
        record["audio_file"] = audio_file
    if source:
        record["source"] = source
    return record


def _previous_messages(context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in _trim_context(context):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        record: dict[str, Any] = {
            "role": str(item.get("role") or "unknown"),
            "text": text,
        }
        if item.get("audio_file"):
            record["audio_file"] = str(item["audio_file"])
        if item.get("source"):
            record["source"] = str(item["source"])
        messages.append(record)
    return messages


def _normalize_client_context(context: list[dict[str, Any]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in context[-MAX_SESSION_MESSAGES:]:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        role = str(item.get("role") or "user").strip() or "user"
        messages.append(
            _message_record(
                role=role,
                text=text,
                audio_file=str(item["audio_file"]) if item.get("audio_file") else None,
                source=str(item["source"]) if item.get("source") else None,
            )
        )
    return messages


def _sanitize_line(text: str, *, max_len: int = 220) -> str:
    return " ".join((text or "").split())[:max_len]


def _build_imprecise_second_pass_prompt(system_prompt: str) -> str:
    return system_prompt + "\n\n" + IMPRECISE_SECOND_PASS_INSTRUCTION


def _fallback_clarification_plan(plan: Any) -> Any:
    return type(plan)(
        kind="clarification",
        message=IMPRECISE_FALLBACK_QUESTION,
        title=None,
        description=None,
    )


async def _resolve_imprecise_plan(
    *,
    planner: AlicePlanner,
    text: str,
    system_prompt: str,
    planned: Any,
) -> Any:
    if planned.kind != "imprecise":
        return planned

    second_pass = await planner.plan(text, system_prompt=_build_imprecise_second_pass_prompt(system_prompt))
    if second_pass.kind == "clarification":
        return second_pass

    return _fallback_clarification_plan(planned)


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


async def _load_admin_staff_names(db: AsyncSession, *, event_id: int) -> list[str]:
    result = await db.execute(
        select(Staff)
        .where(Staff.event_id == event_id, Staff.is_admin.is_(True))
        .order_by(Staff.name.asc())
        .limit(20)
    )
    admins = list(result.scalars().all())
    return [f"- {admin.name}" for admin in admins]


async def _load_kb_context(
    db: AsyncSession,
    *,
    event_id: int,
    visible_clause: Any,
) -> list[str]:
    result = await db.execute(
        select(KnowledgeBaseLink)
        .where(
            KnowledgeBaseLink.event_id == event_id,
            KnowledgeBaseLink.is_active.is_(True),
        )
        .where(visible_clause)
        .order_by(KnowledgeBaseLink.id.asc())
        .limit(10)
    )
    links = list(result.scalars().all())
    lines: list[str] = []
    for link in links:
        description = _sanitize_line(link.description or "", max_len=160)
        tags = ", ".join(link.tags or []) if isinstance(link.tags, list) else ""
        tail = f" — {description}" if description else ""
        tags_tail = f" tags: {tags}" if tags else ""
        lines.append(f"- {link.title}: {link.url}{tail}{tags_tail}")
    return lines


async def _load_confidentiality_rules(db: AsyncSession, *, event_id: int) -> list[str]:
    result = await db.execute(
        select(ConfidentialityRule)
        .where(ConfidentialityRule.event_id == event_id, ConfidentialityRule.is_active.is_(True))
        .order_by(ConfidentialityRule.severity.desc(), ConfidentialityRule.id.asc())
        .limit(20)
    )
    rules = list(result.scalars().all())
    return [
        f"- {rule.category} [{rule.severity}]: {_sanitize_line(rule.description, max_len=180)}"
        for rule in rules
    ]


async def _load_incident_summary(
    db: AsyncSession,
    *,
    event_id: int,
    visible_clause: Any,
) -> list[str]:
    result = await db.execute(
        select(Ticket)
        .where(Ticket.event_id == event_id)
        .where(visible_clause)
        .where(Ticket.visibility != Visibility.confidential)
        .order_by(Ticket.updated_at.desc(), Ticket.id.desc())
        .limit(8)
    )
    tickets = list(result.scalars().all())
    lines: list[str] = []
    for ticket in tickets:
        lines.append(f"- #{ticket.id} {ticket.title} [{ticket.status.value}]")
    return lines


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


async def _kb_visibility_clause(db: AsyncSession, staff: Staff) -> Any:
    if staff.is_admin:
        return true()

    can_see_confidential = await _can_see_confidential(db, staff)
    return or_(
        KnowledgeBaseLink.visibility == Visibility.public,
        and_(KnowledgeBaseLink.visibility == Visibility.role_only, true() if staff.role_id else false()),
        and_(
            KnowledgeBaseLink.visibility == Visibility.confidential,
            true() if can_see_confidential else false(),
        ),
    )


async def _load_ticket_for_response(db: AsyncSession, *, event_id: int, ticket_id: int) -> Ticket | None:
    result = await db.execute(
        select(Ticket)
        .options(
            selectinload(Ticket.created_by),
            selectinload(Ticket.assignments).selectinload(TicketAssignment.staff),
        )
        .where(Ticket.event_id == event_id, Ticket.id == ticket_id)
    )
    return result.scalar_one_or_none()


def _serialize_ticket(ticket: Ticket | None) -> TicketSchema | None:
    if ticket is None:
        return None
    return TicketSchema.model_validate(ticket)


def _extract_completion_query(text: str) -> str | None:
    cleaned = text.strip().lower()
    if not cleaned.startswith("я сделал"):
        return None
    tail = cleaned[len("я сделал") :].strip(" .,!?")
    tail = re.sub(r"^задачу\s*", "", tail)
    return tail or ""


async def handle_command(
    *,
    db: AsyncSession,
    event_id: int,
    current_staff: Staff,
    text: str,
    source: str | None = None,
    audio_file: str | None = None,
    client_context: list[dict[str, Any]] | None = None,
) -> AgentCommandResponse:
    session = await _get_or_create_session(db, event_id=event_id, staff_id=current_staff.id)
    context = (
        _normalize_client_context(client_context)
        if client_context is not None
        else list(session.context or [])
    )
    context.append(_message_record(role="user", text=text, audio_file=audio_file, source=source))

    tools = AgentTools(db=db, event_id=event_id, current_staff=current_staff)
    planner = AlicePlanner()

    event, roles, zones, free_staff_count = await _load_event_context(db, event_id=event_id)
    visible_clause = await _ticket_visibility_clause(db, current_staff)
    kb_visible_clause = await _kb_visibility_clause(db, current_staff)
    admin_staff = await _load_admin_staff_names(db, event_id=event_id)
    kb_context = await _load_kb_context(db, event_id=event_id, visible_clause=kb_visible_clause)
    confidentiality_rules = await _load_confidentiality_rules(db, event_id=event_id)
    incident_summary = await _load_incident_summary(
        db,
        event_id=event_id,
        visible_clause=visible_clause,
    )

    system_prompt = build_system_prompt(
        event_name=event.name,
        event_description=event.description,
        roles=roles,
        zones=zones,
        free_staff_count=free_staff_count,
        admin_staff=admin_staff,
        kb_context=kb_context,
        confidentiality_rules=confidentiality_rules,
        incident_summary=incident_summary,
        recent_dialogue=_trim_context(context[:-1]),
    )

    completion_query = _extract_completion_query(text)
    if completion_query is not None:
        tickets_result = await db.execute(
            select(Ticket)
            .where(Ticket.event_id == event_id)
            .where(visible_clause)
            .where(Ticket.status.not_in([TicketStatus.resolved, TicketStatus.closed]))
            .order_by(Ticket.updated_at.desc())
            .limit(20)
        )
        candidates = list(tickets_result.scalars().all())

        target_ticket: Ticket | None = None
        if completion_query == "":
            target_ticket = candidates[0] if candidates else None
        else:
            for ticket in candidates:
                title = (ticket.title or "").lower()
                if completion_query in title:
                    target_ticket = ticket
                    break

        if target_ticket is None:
            response = AgentCommandResponse(
                action="question_asked",
                message="Не понял, какую именно задачу отметить выполненной. Напиши название задачи.",
            )
        else:
            target_ticket.status = TicketStatus.resolved
            await db.flush()
            target_ticket_for_response = await _load_ticket_for_response(
                db,
                event_id=event_id,
                ticket_id=target_ticket.id,
            )
            response = AgentCommandResponse(
                action="answered",
                message=f"Отметил задачу #{target_ticket.id} «{target_ticket.title}» как выполненную.",
                ticket=_serialize_ticket(target_ticket_for_response),
            )

        context.append({"role": "assistant", "text": response.message})
        session.context = [] if response.action == "answered" else _trim_context(context)
        await db.commit()
        return response

    planned = await planner.plan(text, system_prompt=system_prompt)
    planned = await _resolve_imprecise_plan(
        planner=planner,
        text=text,
        system_prompt=system_prompt,
        planned=planned,
    )

    if planned.kind == "clarification":
        response = AgentCommandResponse(action="question_asked", message=planned.message)
    elif planned.kind == "answered":
        response = AgentCommandResponse(action="answered", message=planned.message)
    elif planned.kind == "informational":
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
            previous_messages=_previous_messages(context),
            ai_suggestion=ai_suggestion,
        )
        ticket_for_response = await _load_ticket_for_response(db, event_id=event_id, ticket_id=created_ticket.id)

        response = AgentCommandResponse(
            action="ticket_created",
            message=(
                f"Создал задачу #{created_ticket.id}: {created_ticket.title}. "
                f"{reasoning} После подтверждения отправлю уведомления исполнителям."
            ),
            suggestion=AiSuggestion(
                reasoning=reasoning,
                suggested_staff_ids=suggested_ids,
                confidence="medium" if suggested_ids else "low",
                ticket_id=created_ticket.id,
            ),
            ticket=_serialize_ticket(ticket_for_response),
        )

    context.append({"role": "assistant", "text": response.message})
    if response.action in {"ticket_created", "answered"}:
        session.context = []
    else:
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
        .options(
            selectinload(Ticket.created_by),
            selectinload(Ticket.assignments).selectinload(TicketAssignment.staff),
        )
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
                    from ..notifier import format_task_notification

                    await tools.send_notification(
                        telegram_id=staff.telegram_id,
                        message=format_task_notification(
                            ticket_id=ticket.id,
                            title=ticket.title,
                            description=ticket.description,
                        ),
                    )
    else:
        ticket.status = TicketStatus.waiting

    await db.commit()
    refreshed_ticket = await _load_ticket_for_response(db, event_id=event_id, ticket_id=ticket.id)
    if refreshed_ticket is None:
        raise ValueError("Ticket disappeared after confirmation")
    return TicketSchema.model_validate(refreshed_ticket)
