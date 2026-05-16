import re
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import case, false, select, true
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import schemas
from ..agent.alice import AlicePlanner
from ..agent.prompts import build_knowledge_capture_prompt
from ..auth import get_current_staff
from ..database import get_db
from ..models import KnowledgeBaseLink, Role, Staff, StaffStatus, Ticket, TicketAssignment, TicketPriority, TicketReply, TicketStatus, Visibility
from ..notifier import enqueue_notification, format_task_notification
from ..rag import index_document_chunks
from .common import can_see_confidential, ensure_event_access, ticket_visibility_filter

router = APIRouter(prefix="/events/{event_id}/tickets", tags=["tickets"])
logger = logging.getLogger(__name__)


def _document_storage_dir() -> Path:
    return Path("storage/documents")


def _safe_filename(value: str) -> str:
    name = Path(value or "document").name
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name) or "document"


async def _save_upload(file: UploadFile, destination: Path) -> bytes:
    content = await file.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return content


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


async def _maybe_capture_organizer_reply_as_knowledge(
    db: AsyncSession,
    *,
    ticket: Ticket,
    reply: TicketReply,
    current_staff: Staff,
) -> None:
    if not current_staff.is_admin:
        return
    if ticket.created_by_id is None or ticket.created_by_id == current_staff.id:
        return

    creator = await db.get(Staff, ticket.created_by_id)
    if creator is None or not creator.is_admin:
        return

    replies_result = await db.scalars(
        select(TicketReply)
        .where(TicketReply.event_id == ticket.event_id, TicketReply.ticket_id == ticket.id)
        .order_by(TicketReply.created_at.asc(), TicketReply.id.asc())
    )
    replies = list(replies_result.all())
    conversation_lines = [
        f"Тикет #{ticket.id}: {ticket.title}",
        f"Описание тикета: {ticket.description or '—'}",
        f"Создал организатор: {creator.name}",
        f"Ответил организатор: {current_staff.name}",
        "Разговор:",
    ]
    for item in replies:
        author = current_staff.name if item.from_staff_id == current_staff.id else f"staff:{item.from_staff_id}"
        conversation_lines.append(f"- {author}: {item.content}")
    conversation = "\n".join(conversation_lines)

    decision = await AlicePlanner().assess_knowledge_candidate(
        conversation=conversation,
        system_prompt=build_knowledge_capture_prompt(),
    )
    if not decision.useful or not decision.content:
        return

    title = decision.title or f"Знание из тикета #{ticket.id}: {ticket.title}"
    link = KnowledgeBaseLink(
        event_id=ticket.event_id,
        title=title[:255],
        url=f"admin://tickets/{ticket.id}/replies/{reply.id}",
        description=decision.reason,
        tags=decision.tags or ["ticket_reply"],
        is_active=True,
        visibility=ticket.visibility,
    )
    db.add(link)
    await db.flush()
    await index_document_chunks(
        db,
        event_id=ticket.event_id,
        content=decision.content.encode("utf-8"),
        source_title=link.title,
        source_url=link.url,
        knowledge_base_link_id=link.id,
        metadata={
            "source": "ticket_reply",
            "ticket_id": ticket.id,
            "reply_id": reply.id,
        },
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
    await db.flush()
    ticket.updated_at = reply.created_at
    try:
        await _maybe_capture_organizer_reply_as_knowledge(
            db,
            ticket=ticket,
            reply=reply,
            current_staff=current_staff,
        )
    except Exception:
        # KB capture must never break ticket replies.
        logger.exception("Failed to capture ticket reply as knowledge: ticket_id=%s reply_id=%s", ticket.id, reply.id)
    await db.commit()
    loaded = await db.scalar(
        select(TicketReply)
        .options(selectinload(TicketReply.from_staff))
        .where(TicketReply.id == reply.id)
    )
    return loaded or reply


@router.post("/{ticket_id}/documents", response_model=schemas.DocumentAttachment, status_code=status.HTTP_201_CREATED)
async def attach_ticket_document(
    event_id: int,
    ticket_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> schemas.DocumentAttachment:
    await ensure_event_access(event_id, current_staff)
    ticket = await _load_visible_ticket(db, event_id, ticket_id, current_staff)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    document_id = uuid4().hex
    filename = _safe_filename(file.filename or "document")
    destination = _document_storage_dir() / str(event_id) / "tickets" / str(ticket_id) / f"{document_id}_{filename}"
    content = await _save_upload(file, destination)
    document = {
        "id": document_id,
        "title": title or filename,
        "filename": filename,
        "content_type": file.content_type,
        "size": len(content),
        "path": str(destination),
        "uploaded_by_id": current_staff.id,
        "created_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }
    ticket.documents = [*ticket.documents, document]
    await index_document_chunks(
        db,
        event_id=event_id,
        content=content,
        source_title=document["title"],
        source_url=document["path"],
        ticket_id=ticket_id,
        metadata={"filename": filename, "content_type": file.content_type},
    )
    await db.commit()
    return schemas.DocumentAttachment.model_validate(document)


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
