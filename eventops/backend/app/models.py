"""
EventOps AI — SQLAlchemy models
"""

import enum
from datetime import UTC, datetime
from typing import Any
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey,
    Integer, JSON, String, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC for SQLAlchemy DateTime columns, Python 3.12-safe."""
    return datetime.now(UTC).replace(tzinfo=None)


# ─── Enums ────────────────────────────────────────────────────────────────────

class TicketType(str, enum.Enum):
    planned  = "planned"   # плановая задача
    incident = "incident"  # инцидент
    tech     = "tech"      # техническая проблема
    question = "question"  # вопрос


class TicketPriority(str, enum.Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


class TicketStatus(str, enum.Enum):
    new       = "new"
    in_progress = "in_progress"
    waiting   = "waiting"       # ожидает подтверждения
    resolved  = "resolved"
    closed    = "closed"


class Visibility(str, enum.Enum):
    public       = "public"        # видят все
    role_only    = "role_only"     # видит только своя роль
    confidential = "confidential"  # только admin + роли с can_see_confidential


class StaffStatus(str, enum.Enum):
    free     = "free"
    busy     = "busy"
    on_task  = "on_task"
    offline  = "offline"


# ─── Models ───────────────────────────────────────────────────────────────────

class Event(Base):
    """Мероприятие — верхний уровень иерархии."""
    __tablename__ = "events"

    id          = Column(Integer, primary_key=True)
    name        = Column(String(255), nullable=False)
    description = Column(Text)
    start_time  = Column(DateTime)
    end_time    = Column(DateTime)
    created_at  = Column(DateTime, default=utcnow)

    zones   = relationship("Zone",   back_populates="event", cascade="all, delete-orphan")
    roles   = relationship("Role",   back_populates="event", cascade="all, delete-orphan")
    staff   = relationship("Staff",  back_populates="event", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="event", cascade="all, delete-orphan")
    knowledge_base_links = relationship("KnowledgeBaseLink", back_populates="event", cascade="all, delete-orphan")
    confidentiality_rules = relationship("ConfidentialityRule", back_populates="event", cascade="all, delete-orphan")
    ticket_replies = relationship("TicketReply", back_populates="event", cascade="all, delete-orphan")


class Zone(Base):
    """
    Физическая зона площадки: Холл 1, Регистрация, Live-зона и т.д.
    Используется для определения ближайших свободных людей.
    """
    __tablename__ = "zones"

    id          = Column(Integer, primary_key=True)
    event_id    = Column(Integer, ForeignKey("events.id"), nullable=False)
    name        = Column(String(100), nullable=False)
    description = Column(Text)

    event = relationship("Event", back_populates="zones")
    staff = relationship("Staff", back_populates="zone")


class Role(Base):
    """
    Роль команды: Техкомитет, Live, Регистрация, Жюри, Оргкомитет и т.д.
    ai_prompt — описание роли для Алисы, чтобы та понимала,
    кому маршрутизировать задачи без явного указания роли.

    Пример ai_prompt для "Техкомитет":
        "Отвечает за работу оборудования, интернет, проектор,
         звук, технические неисправности."
    """
    __tablename__ = "roles"

    id                   = Column(Integer, primary_key=True)
    event_id             = Column(Integer, ForeignKey("events.id"), nullable=False)
    name                 = Column(String(100), nullable=False)
    description          = Column(Text)
    ai_prompt            = Column(Text)          # используется в системном промпте Алисы
    color                = Column(String(7), default="#6366f1")  # hex, для UI
    can_see_confidential = Column(Boolean, default=False)        # жюри и оргкомитет

    event = relationship("Event", back_populates="roles")
    staff = relationship("Staff", back_populates="role")


class Staff(Base):
    """
    Участник команды: волонтёр или организатор.
    telegram_id — идентификатор для уведомлений.
    """
    __tablename__ = "staff"

    id                = Column(Integer, primary_key=True)
    event_id          = Column(Integer, ForeignKey("events.id"), nullable=False)
    name              = Column(String(255), nullable=False)
    telegram_id       = Column(String(50), nullable=True, unique=True)
    telegram_username = Column(String(100), nullable=True)
    role_id           = Column(Integer, ForeignKey("roles.id"), nullable=True)
    zone_id           = Column(Integer, ForeignKey("zones.id"), nullable=True)
    status            = Column(Enum(StaffStatus), default=StaffStatus.free)
    is_admin          = Column(Boolean, default=False)
    created_at        = Column(DateTime, default=utcnow)

    event       = relationship("Event", back_populates="staff")
    role        = relationship("Role",  back_populates="staff")
    zone        = relationship("Zone",  back_populates="staff")
    assignments = relationship("TicketAssignment", back_populates="staff")


class Ticket(Base):
    """
    Тикет / задача / инцидент.

    assignee_role_id — задача на всю роль (Алиса выбрала роль автоматически).
    assignments      — конкретные назначения на людей (после подтверждения).
    ai_suggestion    — JSON с предложением Алисы:
        {
          "reasoning": "Анна и Максим свободны и ближе всего к регистрации",
          "suggested_staff_ids": [3, 7],
          "confidence": "high"
        }
    """
    __tablename__ = "tickets"

    id               = Column(Integer, primary_key=True)
    event_id         = Column(Integer, ForeignKey("events.id"), nullable=False)
    title            = Column(String(255), nullable=False)
    description      = Column(Text)
    type             = Column(Enum(TicketType),     default=TicketType.incident)
    priority         = Column(Enum(TicketPriority), default=TicketPriority.medium)
    status           = Column(Enum(TicketStatus),   default=TicketStatus.new)
    visibility       = Column(Enum(Visibility),     default=Visibility.public)

    created_by_id    = Column(Integer, ForeignKey("staff.id"), nullable=True)
    assignee_role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)

    ai_suggestion    = Column(JSON, nullable=True)

    created_at       = Column(DateTime, default=utcnow)
    updated_at       = Column(DateTime, default=utcnow, onupdate=utcnow)

    event       = relationship("Event",  back_populates="tickets")
    created_by  = relationship("Staff",  foreign_keys=[created_by_id])
    role        = relationship("Role",   foreign_keys=[assignee_role_id])
    assignments = relationship("TicketAssignment", back_populates="ticket",
                               cascade="all, delete-orphan")
    replies     = relationship("TicketReply", back_populates="ticket", cascade="all, delete-orphan")

    @property
    def sender(self) -> Staff | None:
        return self.created_by

    @property
    def target(self) -> dict[str, Any]:
        payload = self.ai_suggestion if isinstance(self.ai_suggestion, dict) else {}
        raw = payload.get("target") if isinstance(payload, dict) else None
        if isinstance(raw, dict):
            return {
                "all": bool(raw.get("all", False)),
                "role_ids": [int(v) for v in raw.get("role_ids", []) if isinstance(v, int)],
                "staff_ids": [int(v) for v in raw.get("staff_ids", []) if isinstance(v, int)],
            }
        return {"all": False, "role_ids": [], "staff_ids": []}

    @target.setter
    def target(self, value: dict[str, Any] | None) -> None:
        payload = self.ai_suggestion if isinstance(self.ai_suggestion, dict) else {}
        target_payload = value or {}
        payload["target"] = {
            "all": bool(target_payload.get("all", False)),
            "role_ids": [int(v) for v in target_payload.get("role_ids", []) if isinstance(v, int)],
            "staff_ids": [int(v) for v in target_payload.get("staff_ids", []) if isinstance(v, int)],
        }
        self.ai_suggestion = payload


class TicketAssignment(Base):
    """
    Назначение конкретного человека на тикет.
    confirmed = True означает, что человек принял задачу.
    """
    __tablename__ = "ticket_assignments"

    id          = Column(Integer, primary_key=True)
    ticket_id   = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    staff_id    = Column(Integer, ForeignKey("staff.id"), nullable=False)
    assigned_at = Column(DateTime, default=utcnow)
    confirmed   = Column(Boolean, default=False)

    ticket = relationship("Ticket", back_populates="assignments")
    staff  = relationship("Staff",  back_populates="assignments")


class TicketReply(Base):
    """Ответ/комментарий к тикету от участника мероприятия."""
    __tablename__ = "ticket_replies"

    id            = Column(Integer, primary_key=True)
    event_id      = Column(Integer, ForeignKey("events.id"), nullable=False)
    ticket_id     = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    from_staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False)
    content       = Column(Text, nullable=False)
    visibility    = Column(Enum(Visibility), default=Visibility.public)
    created_at    = Column(DateTime, default=utcnow)

    event      = relationship("Event", back_populates="ticket_replies")
    ticket     = relationship("Ticket", back_populates="replies")
    from_staff = relationship("Staff", foreign_keys=[from_staff_id])

    @property
    def sender(self) -> Staff | None:
        return self.from_staff


class Message(Base):
    """
    Сообщения между людьми / от координатора к роли.
    Используется для Q&A: волонтёр задаёт вопрос → организатор отвечает.

    to_staff_id  — личное сообщение конкретному человеку
    to_role_id   — сообщение всей роли (например, всем из "Регистрация")
    visibility   — фильтрация конфиденциальных сообщений
    """
    __tablename__ = "messages"

    id            = Column(Integer, primary_key=True)
    event_id      = Column(Integer, ForeignKey("events.id"), nullable=False)
    from_staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False)
    to_staff_id   = Column(Integer, ForeignKey("staff.id"), nullable=True)
    to_role_id    = Column(Integer, ForeignKey("roles.id"), nullable=True)
    content       = Column(Text, nullable=False)
    is_read       = Column(Boolean, default=False)
    visibility    = Column(Enum(Visibility), default=Visibility.public)
    created_at    = Column(DateTime, default=utcnow)

    from_staff = relationship("Staff", foreign_keys=[from_staff_id])
    to_staff   = relationship("Staff", foreign_keys=[to_staff_id])
    to_role    = relationship("Role",  foreign_keys=[to_role_id])


class AgentSession(Base):
    """
    Контекст диалога с Алисой для конкретного сотрудника.
    context — список сообщений в формате Alice AI API:
        [{"role": "user", "text": "..."}, {"role": "assistant", "text": "..."}]
    Сбрасывается в начале каждого мероприятия.
    """
    __tablename__ = "agent_sessions"

    id         = Column(Integer, primary_key=True)
    event_id   = Column(Integer, ForeignKey("events.id"), nullable=False)
    staff_id   = Column(Integer, ForeignKey("staff.id"), nullable=False)
    context    = Column(JSON, default=list)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    staff = relationship("Staff", foreign_keys=[staff_id])


class KnowledgeBaseLink(Base):
    """Ссылка на регламент/документ/инструкцию, которую Алиса может использовать в ответах."""
    __tablename__ = "knowledge_base_links"

    id          = Column(Integer, primary_key=True)
    event_id    = Column(Integer, ForeignKey("events.id"), nullable=False)
    title       = Column(String(255), nullable=False)
    url         = Column(String(2048), nullable=False)
    description = Column(Text)
    tags        = Column(JSON, default=list)
    is_active   = Column(Boolean, default=True)
    visibility  = Column(Enum(Visibility), default=Visibility.public)
    created_at  = Column(DateTime, default=utcnow)
    updated_at  = Column(DateTime, default=utcnow, onupdate=utcnow)

    event = relationship("Event", back_populates="knowledge_base_links")


class ConfidentialityRule(Base):
    """Правило, какие категории данных считаются закрытыми на мероприятии."""
    __tablename__ = "confidentiality_rules"

    id          = Column(Integer, primary_key=True)
    event_id    = Column(Integer, ForeignKey("events.id"), nullable=False)
    category    = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    severity    = Column(String(20), default="medium")
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=utcnow)
    updated_at  = Column(DateTime, default=utcnow, onupdate=utcnow)

    event = relationship("Event", back_populates="confidentiality_rules")
