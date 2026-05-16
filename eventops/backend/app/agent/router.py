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
from ..rag import search_document_chunks
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
from ..schemas import (
    AgentCommandResponse,
    AiSuggestion,
    RoleShort,
    StaffAuthor,
    Ticket as TicketSchema,
)


MAX_SESSION_MESSAGES = 20
KB_SNIPPET_MAX_CHARS = 1400
KB_ANSWER_MAX_CHARS = 3200
KB_ANSWER_EXCERPT_CHARS = 420
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


def _format_kb_chunk_line(chunk: dict[str, Any]) -> str:
    content = _sanitize_line(str(chunk.get("content") or ""), max_len=KB_SNIPPET_MAX_CHARS)
    source_title = str(chunk.get("source_title") or "Источник")
    source_url = str(chunk.get("source_url") or "no-url")
    return f"- {source_title}: {content} ({source_url})"


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[\wА-Яа-яЁё]+", (query or "").lower())
    stop_words = {
        "есть",
        "базе",
        "база",
        "знаний",
        "знаниях",
        "дисциплина",
        "дисциплины",
        "какой",
        "какая",
        "какие",
        "что",
        "это",
        "про",
        "найди",
        "расскажи",
        "информация",
        "информации",
    }
    result: list[str] = []
    for term in terms:
        if len(term) < 4 or term in stop_words or term in result:
            continue
        result.append(term)
    return result


CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def _normalize_entity_text(value: str) -> str:
    lowered = (value or "").strip().lower().replace("ё", "е")
    transliterated = lowered.translate(CYRILLIC_TO_LATIN)
    normalized = re.sub(r"[^a-zа-я0-9]+", " ", transliterated)
    return " ".join(normalized.split())


def _entity_tokens(value: str) -> list[str]:
    tokens = _normalize_entity_text(value).split()
    normalized_tokens: list[str] = []
    for token in tokens:
        if len(token) <= 2:
            continue
        # Lightweight Russian case fallback: "Анну" -> "ann", which still
        # matches "anna" by prefix below.
        normalized_tokens.append(token.rstrip("aeiouy"))
    return normalized_tokens


def _entity_matches_name(query: str, name: str) -> bool:
    normalized_query = _normalize_entity_text(query)
    normalized_name = _normalize_entity_text(name)
    if not normalized_query or not normalized_name:
        return False
    if normalized_query in normalized_name or normalized_name in normalized_query:
        return True

    query_tokens = _entity_tokens(query)
    name_tokens = _entity_tokens(name)
    return bool(query_tokens) and all(
        any(name_token.startswith(query_token) or query_token.startswith(name_token) for name_token in name_tokens)
        for query_token in query_tokens
    )


def _chunk_matches_query(chunk: dict[str, Any], query: str) -> bool:
    terms = _query_terms(query)
    if not terms:
        return True

    content = str(chunk.get("content") or "").lower()
    title = str(chunk.get("source_title") or "").lower()
    haystack = f"{title} {content}"

    # For named entities, require at least one exact term hit. Vector-only matches
    # are useful for recall, but too risky to present as facts to operators.
    return any(term in haystack for term in terms)


def _relevant_excerpt(content: str, query: str, *, max_len: int = KB_ANSWER_EXCERPT_CHARS) -> str:
    normalized = _sanitize_line(content, max_len=max(len(content), max_len))
    lowered = normalized.lower()
    positions = [lowered.find(term) for term in _query_terms(query)]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return _sanitize_line(normalized, max_len=max_len)

    center = min(positions)
    start = max(0, center - max_len // 3)
    end = min(len(normalized), start + max_len)
    excerpt = normalized[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(normalized):
        excerpt += "..."
    return excerpt


def _format_kb_search_answer(chunks: list[dict[str, Any]], query: str) -> str:
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    filtered_chunks = [chunk for chunk in chunks if _chunk_matches_query(chunk, query)]
    if not filtered_chunks:
        return "В базе знаний сейчас не нашла точной информации по этому запросу."

    for chunk in filtered_chunks:
        source_title = str(chunk.get("source_title") or "Источник")
        source_url = str(chunk.get("source_url") or "no-url")
        excerpt = _relevant_excerpt(str(chunk.get("content") or ""), query)
        dedupe_key = (source_title, excerpt)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        lines.append(f"- {source_title}: {excerpt} ({source_url})")
        if len(lines) >= 3:
            break

    answer = "Нашла в базе знаний:\n" + "\n".join(lines)
    if len(answer) <= KB_ANSWER_MAX_CHARS:
        return answer
    return answer[:KB_ANSWER_MAX_CHARS].rstrip() + "\n..."


def _is_ticket_summary_query(text: str) -> bool:
    lowered = (text or "").lower()
    ticket_words = ("задач", "тикет", "инцидент")
    summary_words = ("актуаль", "сейчас", "текущ", "список", "какие", "что есть", "статус")
    return any(word in lowered for word in ticket_words) and any(word in lowered for word in summary_words)


async def _build_ticket_summary_response(
    db: AsyncSession,
    *,
    event_id: int,
    visible_clause: Any,
    response_author: StaffAuthor | None,
    response_author_role: RoleShort | None,
) -> AgentCommandResponse:
    ticket_result = await db.execute(
        select(Ticket)
        .where(Ticket.event_id == event_id)
        .where(visible_clause)
        .where(Ticket.status.not_in([TicketStatus.resolved, TicketStatus.closed]))
        .order_by(Ticket.updated_at.desc(), Ticket.id.desc())
        .limit(8)
    )
    tickets = list(ticket_result.scalars().all())
    if not tickets:
        message = "Сейчас актуальных задач не найдено."
    else:
        lines = [f"- #{ticket.id} {ticket.title} ({ticket.status.value})" for ticket in tickets]
        message = "Актуальные задачи:\n" + "\n".join(lines)
    return AgentCommandResponse(
        action="answered",
        message=message,
        model_response=message,
        author=response_author,
        author_role=response_author_role,
    )


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
    query_text: str | None = None,
) -> list[str]:
    if query_text:
        chunks = await search_document_chunks(db, event_id=event_id, query=query_text, limit=5)
        if chunks:
            return [_format_kb_chunk_line(chunk) for chunk in chunks]

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


async def _response_author(db: AsyncSession, staff: Staff) -> tuple[StaffAuthor, str | None]:
    role_name: str | None = None
    role_short: RoleShort | None = None
    if staff.role_id is not None:
        role = await db.scalar(select(Role).where(Role.id == staff.role_id, Role.event_id == staff.event_id))
        if role is not None:
            role_name = role.name
            role_short = RoleShort.model_validate(role)

    return StaffAuthor(
        id=staff.id,
        name=staff.name,
        status=staff.status,
        role=role_short,
    ), role_name


async def _resolve_assignees_with_rag(
    db: AsyncSession,
    *,
    event_id: int,
    assignees: list[str],
) -> tuple[list[int], list[int]] | None:
    """Resolve assignee names -> (role_ids, staff_ids).

    Non-informational flow uses people+roles RAG (and optional KB context) by contract.
    Concrete RAG API is intentionally left as pseudocode until integration is finalized.
    """
    role_ids: list[int] = []
    staff_ids: list[int] = []
    unresolved: list[str] = []

    for entity in assignees:
        raw = (entity or "").strip()
        if not raw:
            continue

        role_match = await db.scalar(
            select(Role).where(Role.event_id == event_id, Role.name.ilike(raw))
        )
        if role_match is not None:
            role_ids.append(int(role_match.id))
            continue

        staff_result = await db.execute(select(Staff).where(Staff.event_id == event_id).order_by(Staff.id.asc()))
        staff_matches = [staff for staff in staff_result.scalars().all() if _entity_matches_name(raw, staff.name)]
        if len(staff_matches) == 1:
            staff_ids.append(int(staff_matches[0].id))
            continue

        unresolved.append(raw)

    if unresolved:
        # PSEUDOCODE (non-informational RAG):
        # people_candidates = [rag.search_people(query=name) for name in unresolved]
        # role_candidates = [rag.search_roles(query=name) for name in unresolved]
        # kb_hints = rag.search_docs(keywords=unresolved)  # optional contextual hints
        # selected_ids = llm_verify_entity_ids(input_names=unresolved, candidates=rag_candidates)
        # if selected_ids is None:
        #     return None
        # staff_ids.extend(selected_ids)
        return None

    return list(dict.fromkeys(role_ids)), list(dict.fromkeys(staff_ids))


def _normalize_ticket_status(raw: str | None) -> TicketStatus | None:
    if not raw:
        return None
    try:
        return TicketStatus(str(raw).strip().lower())
    except Exception:
        return None


async def _find_staff_for_query(db: AsyncSession, *, event_id: int, query: str) -> Staff | None:
    normalized = (query or "").strip().lower()
    if not normalized:
        return None
    result = await db.execute(
        select(Staff)
        .where(Staff.event_id == event_id)
        .order_by(Staff.id.asc())
    )
    candidates = list(result.scalars().all())
    matches = [staff for staff in candidates if normalized in str(staff.name).lower() or _entity_matches_name(normalized, staff.name)]
    if len(matches) == 1:
        return matches[0]
    return None


def _extract_completion_query(text: str) -> str | None:
    cleaned = text.strip().lower()
    if not cleaned.startswith("я сделал"):
        return None
    tail = cleaned[len("я сделал") :].strip(" .,!?")
    tail = re.sub(r"^задачу\s*", "", tail)
    return tail or ""


def _finalize_response(response: AgentCommandResponse) -> AgentCommandResponse:
    model_text = (response.model_response or "").strip()
    ui_text = (response.message or "").strip()

    if not model_text and ui_text:
        response.model_response = ui_text
        return response
    if model_text and not ui_text:
        response.message = model_text
        return response
    if model_text and ui_text and not ui_text.startswith(model_text):
        response.message = f"{model_text}\n\n{ui_text}"
    return response


async def handle_command(
    *,
    db: AsyncSession,
    event_id: int,
    current_staff: Staff,
    text: str,
    source: str | None = None,
    audio_file: str | None = None,
    client_context: list[dict[str, Any]] | None = None,
    mode: str = "command",
) -> AgentCommandResponse:
    response_author, response_author_role = await _response_author(db, current_staff)
    mode = mode if mode in {"command", "chat", "ticket_question"} else "command"
    if mode == "command" and not current_staff.is_admin:
        mode = "chat"

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

    if mode != "command":
        system_prompt += (
            "\n\nТекущий режим: справочный чат участника, не операционная команда координатора. "
            "Запрещено создавать тикеты, назначать людей или предлагать tool-действия. "
            "Отвечай только по видимому контексту мероприятия, базе знаний и видимым тикетам. "
            "Если точного ответа нет, верни kind=clarification и коротко скажи, что вопрос нужно передать администратору."
        )

    completion_query = _extract_completion_query(text)
    if mode == "command" and completion_query is not None:
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
                model_response="Не понял, какую именно задачу отметить выполненной. Напиши название задачи.",
                author=response_author,
                author_role=response_author_role,
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
                model_response=f"Отметил задачу #{target_ticket.id} «{target_ticket.title}» как выполненную.",
                author=response_author,
                author_role=response_author_role,
                ticket=_serialize_ticket(target_ticket_for_response),
            )

        response = _finalize_response(response)
        context.append({"role": "assistant", "text": response.model_response or response.message})
        session.context = _trim_context(context)
        await db.commit()
        return response

    if _is_ticket_summary_query(text):
        response = await _build_ticket_summary_response(
            db,
            event_id=event_id,
            visible_clause=visible_clause,
            response_author=response_author,
            response_author_role=response_author_role,
        )
        context.append({"role": "assistant", "text": response.model_response or response.message})
        session.context = _trim_context(context)
        await db.commit()
        return response

    planned = await planner.plan(text, system_prompt=system_prompt)
    planned = await _resolve_imprecise_plan(
        planner=planner,
        text=text,
        system_prompt=system_prompt,
        planned=planned,
    )

    if mode != "command":
        if planned.kind == "informational":
            response = await _build_ticket_summary_response(
                db,
                event_id=event_id,
                visible_clause=visible_clause,
                response_author=response_author,
                response_author_role=response_author_role,
            )
        elif planned.kind in {"answered", "clarification"}:
            response = AgentCommandResponse(
                action="question_asked" if planned.kind == "clarification" else "answered",
                message=planned.message,
                model_response=planned.message,
                author=response_author,
                author_role=response_author_role,
            )
        else:
            message = (
                "Не нашла точный ответ в базе знаний. "
                "Передай вопрос администратору в обсуждении задачи."
                if mode == "ticket_question"
                else "Не нашла точный ответ в базе знаний. Передала вопрос администратору."
            )
            response = AgentCommandResponse(
                action="question_asked",
                message=message,
                model_response=message,
                author=response_author,
                author_role=response_author_role,
            )

        response = _finalize_response(response)
        context.append({"role": "assistant", "text": response.model_response or response.message})
        session.context = _trim_context(context)
        await db.commit()
        return response

    if planned.kind == "clarification":
        response = AgentCommandResponse(
            action="question_asked",
            message=planned.message,
            model_response=planned.message,
            author=response_author,
            author_role=response_author_role,
        )
    elif planned.kind == "answered":
        response = AgentCommandResponse(
            action="answered",
            message=planned.message,
            model_response=planned.message,
            author=response_author,
            author_role=response_author_role,
        )
    elif planned.kind == "informational":
        response = await _build_ticket_summary_response(
            db,
            event_id=event_id,
            visible_clause=visible_clause,
            response_author=response_author,
            response_author_role=response_author_role,
        )
    elif planned.kind == "knowledge_base":
        search_query = " ".join([text, *(planned.keywords or [])]).strip()
        docs = await search_document_chunks(db, event_id=event_id, query=search_query, limit=5)
        if not docs and not planned.keywords:
            response = AgentCommandResponse(
                action="question_asked",
                message="Уточни, пожалуйста, что именно нужно найти в знаниях мероприятия.",
                model_response="Уточни, пожалуйста, что именно нужно найти в знаниях мероприятия.",
                author=response_author,
                author_role=response_author_role,
            )
        else:
            if not docs:
                info_answer = planned.answer or "В базе знаний сейчас не нашёл подходящих материалов."
            else:
                info_answer = planned.answer or _format_kb_search_answer(docs, text)
            response = AgentCommandResponse(
                action="answered",
                message=info_answer,
                model_response=info_answer,
                author=response_author,
                author_role=response_author_role,
            )
    else:
        operational_target = (planned.target or "create").strip().lower()

        if operational_target == "change_status":
            if planned.ticket_id is None:
                response = AgentCommandResponse(
                    action="question_asked",
                    message="Уточни, пожалуйста, id задачи для смены статуса.",
                    model_response="Уточни, пожалуйста, id задачи для смены статуса.",
                    author=response_author,
                    author_role=response_author_role,
                )
            else:
                ticket = await _load_ticket_for_response(db, event_id=event_id, ticket_id=planned.ticket_id)
                next_status = _normalize_ticket_status(planned.status)
                if ticket is None or next_status is None:
                    response = AgentCommandResponse(
                        action="question_asked",
                        message="Не смог определить задачу или статус. Уточни id и нужный статус.",
                        model_response="Не смог определить задачу или статус. Уточни id и нужный статус.",
                        author=response_author,
                        author_role=response_author_role,
                    )
                else:
                    ticket.status = next_status
                    await db.flush()
                    refreshed = await _load_ticket_for_response(db, event_id=event_id, ticket_id=planned.ticket_id)
                    response = AgentCommandResponse(
                        action="answered",
                        message=f"Обновил статус задачи #{planned.ticket_id} на {next_status.value}.",
                        model_response=planned.message,
                        author=response_author,
                        author_role=response_author_role,
                        ticket=_serialize_ticket(refreshed),
                    )

        elif operational_target == "respond":
            explicit_id = planned.ticket_id
            if explicit_id is not None:
                ticket = await _load_ticket_for_response(db, event_id=event_id, ticket_id=explicit_id)
                if ticket is None:
                    response = AgentCommandResponse(
                        action="question_asked",
                        message=f"Не вижу задачу #{explicit_id} в доступной области. Уточни номер.",
                        model_response=f"Не вижу задачу #{explicit_id} в доступной области. Уточни номер.",
                        author=response_author,
                        author_role=response_author_role,
                    )
                else:
                    answer = f"Задача #{ticket.id}: {ticket.title}. Текущий статус: {ticket.status.value}."
                    response = AgentCommandResponse(
                        action="answered",
                        message=answer,
                        model_response=planned.message,
                        author=response_author,
                        author_role=response_author_role,
                        ticket=_serialize_ticket(ticket),
                    )
            else:
                staff = await _find_staff_for_query(db, event_id=event_id, query=text)
                if staff is None:
                    response = AgentCommandResponse(
                        action="question_asked",
                        message="Уточни, пожалуйста, сотрудника или номер задачи, чтобы дать точный ответ.",
                        model_response="Уточни, пожалуйста, сотрудника или номер задачи, чтобы дать точный ответ.",
                        author=response_author,
                        author_role=response_author_role,
                    )
                else:
                    assigned = await db.execute(
                        select(Ticket)
                        .join(TicketAssignment, TicketAssignment.ticket_id == Ticket.id)
                        .where(Ticket.event_id == event_id)
                        .where(TicketAssignment.staff_id == staff.id)
                        .where(visible_clause)
                        .order_by(Ticket.updated_at.desc())
                        .limit(5)
                    )
                    tickets = list(assigned.scalars().all())
                    if not tickets:
                        answer = f"У {staff.name} сейчас нет видимых задач."
                    else:
                        lines = [f"- #{t.id} {t.title} ({t.status.value})" for t in tickets]
                        answer = f"Задачи у {staff.name}:\n" + "\n".join(lines)
                    response = AgentCommandResponse(
                        action="answered",
                        message=answer,
                        model_response=planned.message,
                        author=response_author,
                        author_role=response_author_role,
                    )

        else:
            reasoning = "Автоподбор исполнителей отключён. Назначь людей вручную при подтверждении."
            target_payload: dict[str, Any] = {"all": False, "role_ids": [], "staff_ids": []}

            if isinstance(planned.assignees, str) and planned.assignees.strip().lower() == "all":
                target_payload = {"all": True, "role_ids": [], "staff_ids": []}
                reasoning = "Задача помечена на всех участников."
            elif isinstance(planned.assignees, list) and planned.assignees:
                resolved = await _resolve_assignees_with_rag(db, event_id=event_id, assignees=planned.assignees)
                if resolved is None:
                    response = AgentCommandResponse(
                        action="question_asked",
                        message="Не смог однозначно сопоставить цели по именам. Уточни, пожалуйста, исполнителей.",
                        model_response=planned.message,
                        author=response_author,
                        author_role=response_author_role,
                    )
                    response = _finalize_response(response)
                    context.append({"role": "assistant", "text": response.model_response or response.message})
                    session.context = _trim_context(context)
                    await db.commit()
                    return response

                role_ids, staff_ids = resolved
                target_payload = {"all": False, "role_ids": role_ids, "staff_ids": staff_ids}
                reasoning = "Цели сопоставлены по именам и подготовлены для назначения."

            ai_suggestion = {
                "reasoning": reasoning,
                "suggested_staff_ids": target_payload["staff_ids"],
                "confidence": "low",
            }
            created_ticket = await tools.create_ticket(
                title=planned.title or "Операционная задача",
                description=planned.description,
                target=target_payload,
                assignee_role_id=(target_payload["role_ids"][0] if target_payload["role_ids"] else None),
                ai_suggestion=ai_suggestion,
            )
            ticket_for_response = await _load_ticket_for_response(db, event_id=event_id, ticket_id=created_ticket.id)

            operational_text = (
                f"Создал задачу #{created_ticket.id}: {created_ticket.title}. "
                f"{reasoning} После подтверждения отправлю уведомления исполнителям."
            )
            model_text = (planned.message or "").strip()
            full_model_response = f"{model_text}\n\n{operational_text}" if model_text else operational_text

            response = AgentCommandResponse(
                action="ticket_created",
                message=operational_text,
                model_response=full_model_response,
                author=response_author,
                author_role=response_author_role,
                suggestion=AiSuggestion(
                    reasoning=reasoning,
                    suggested_staff_ids=target_payload["staff_ids"],
                    confidence="low",
                    ticket_id=created_ticket.id,
                ),
                ticket=_serialize_ticket(ticket_for_response),
            )

    response = _finalize_response(response)
    context.append({"role": "assistant", "text": response.model_response or response.message})
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
