"""
EventOps AI — Pydantic schemas (OpenAPI contract)

Соглашение по именованию:
  XBase   — общие поля (используется как основа)
  XCreate — тело запроса при создании (POST)
  XUpdate — тело запроса при обновлении (PATCH), все поля Optional
  X       — полный ответ с id и служебными полями
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from .models import (
    StaffStatus, TicketPriority, TicketStatus,
    TicketType, Visibility
)


# ─── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    telegram_id: str

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    staff_id:     int
    is_admin:     bool


# ─── Zone ─────────────────────────────────────────────────────────────────────

class ZoneCreate(BaseModel):
    name:        str = Field(..., max_length=100, examples=["Холл 1"])
    description: Optional[str] = None

class Zone(ZoneCreate):
    id:       int
    event_id: int

    model_config = {"from_attributes": True}


# ─── Role ─────────────────────────────────────────────────────────────────────

class RoleCreate(BaseModel):
    name:                 str   = Field(..., max_length=100, examples=["Техкомитет"])
    description:          Optional[str] = None
    ai_prompt:            Optional[str] = Field(
        None,
        description="Описание роли для Алисы — чтобы та могла маршрутизировать "
                    "задачи без явного указания роли в запросе."
    )
    color:                str   = Field("#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")
    can_see_confidential: bool  = False

class Role(RoleCreate):
    id:       int
    event_id: int

    model_config = {"from_attributes": True}


# ─── Staff ────────────────────────────────────────────────────────────────────

class StaffCreate(BaseModel):
    name:              str            = Field(..., examples=["Анна Иванова"])
    telegram_id:       Optional[str]  = None
    telegram_username: Optional[str]  = None
    role_id:           Optional[int]  = None
    zone_id:           Optional[int]  = None
    is_admin:          bool           = False

class StaffUpdate(BaseModel):
    name:      Optional[str]          = None
    role_id:   Optional[int]          = None
    zone_id:   Optional[int]          = None
    status:    Optional[StaffStatus]  = None
    is_admin:  Optional[bool]         = None

class StaffShort(BaseModel):
    """Компактное представление — для списков и назначений."""
    id:     int
    name:   str
    status: StaffStatus

    model_config = {"from_attributes": True}

class Staff(StaffCreate):
    id:         int
    event_id:   int
    status:     StaffStatus
    role:       Optional[Role]  = None
    zone:       Optional[Zone]  = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── Event ────────────────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    name:        str            = Field(..., examples=["ICPC 2025 Semifinal"])
    description: Optional[str] = None
    start_time:  Optional[datetime] = None
    end_time:    Optional[datetime] = None

class Event(EventCreate):
    id:         int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

class EventSummary(BaseModel):
    """
    Полная сводка мероприятия — передаётся Алисе как контекст.
    Включает всех людей, роли, зоны, открытые тикеты.
    """
    event:          Event
    zones:          list[Zone]
    roles:          list[Role]
    staff:          list[Staff]
    open_tickets:   list["Ticket"]


# ─── Ticket ───────────────────────────────────────────────────────────────────

class TicketCreate(BaseModel):
    title:            str              = Field(..., examples=["На регистрации очередь"])
    description:      Optional[str]   = None
    type:             TicketType       = TicketType.incident
    priority:         TicketPriority   = TicketPriority.medium
    visibility:       Visibility       = Visibility.public
    assignee_role_id: Optional[int]   = None

class TicketUpdate(BaseModel):
    title:            Optional[str]            = None
    description:      Optional[str]            = None
    type:             Optional[TicketType]      = None
    priority:         Optional[TicketPriority]  = None
    status:           Optional[TicketStatus]    = None
    visibility:       Optional[Visibility]      = None
    assignee_role_id: Optional[int]            = None

class TicketAssignmentOut(BaseModel):
    id:          int
    staff:       StaffShort
    assigned_at: datetime
    confirmed:   bool

    model_config = {"from_attributes": True}

class Ticket(BaseModel):
    id:               int
    event_id:         int
    title:            str
    description:      Optional[str]
    type:             TicketType
    priority:         TicketPriority
    status:           TicketStatus
    visibility:       Visibility
    created_by_id:    Optional[int]
    assignee_role_id: Optional[int]
    ai_suggestion:    Optional[dict[str, Any]]
    assignments:      list[TicketAssignmentOut] = []
    created_at:       datetime
    updated_at:       datetime

    model_config = {"from_attributes": True}

class AssignRequest(BaseModel):
    """Тело запроса для ручного назначения людей на тикет."""
    staff_ids: list[int] = Field(..., min_length=1)

class ConfirmAssignmentRequest(BaseModel):
    confirmed: bool


# ─── Message ──────────────────────────────────────────────────────────────────

class MessageCreate(BaseModel):
    content:      str           = Field(..., examples=["Нужна помощь у входа"])
    to_staff_id:  Optional[int] = None
    to_role_id:   Optional[int] = None
    visibility:   Visibility    = Visibility.public

class Message(BaseModel):
    id:            int
    event_id:      int
    from_staff_id: int
    to_staff_id:   Optional[int]
    to_role_id:    Optional[int]
    content:       str
    is_read:       bool
    visibility:    Visibility
    created_at:    datetime

    model_config = {"from_attributes": True}


# ─── Agent ────────────────────────────────────────────────────────────────────

class AgentCommandRequest(BaseModel):
    """
    Главный эндпоинт агента.
    text — текст команды (или распознанный голос).
    audio_base64 — альтернатива тексту: wav/ogg в base64,
                   бэкенд сам прогоняет через STT Алисы.
    """
    text:          Optional[str]  = Field(None, examples=["На регистрации очередь, нужны люди"])
    audio_base64:  Optional[str]  = None  # base64-encoded audio

class AiSuggestion(BaseModel):
    """Предложение Алисы — возвращается фронту для подтверждения."""
    reasoning:          str              # объяснение решения
    suggested_staff_ids: list[int]
    confidence:         str              # "high" | "medium" | "low"
    ticket_id:          Optional[int]    # None если тикет ещё не создан

class AgentCommandResponse(BaseModel):
    """
    Ответ агента на команду координатора.
    action = "ticket_created"   — создан тикет, ждём подтверждения
    action = "question_asked"   — Алиса задала уточняющий вопрос
    action = "task_assigned"    — задача назначена без уточнений
    action = "answered"         — Алиса ответила на информационный запрос
    """
    action:      str
    message:     str                      # текст ответа Алисы для UI
    suggestion:  Optional[AiSuggestion]  = None
    ticket:      Optional[Ticket]        = None

class AgentConfirmRequest(BaseModel):
    """Подтверждение или отклонение предложения Алисы."""
    ticket_id:   int
    accept:      bool
    staff_ids:   Optional[list[int]] = None  # если хотят назначить вручную


# ─── Staff context (для запросов волонтёра) ───────────────────────────────────

class MyContext(BaseModel):
    """
    Отвечает на вопросы вида:
    'что мне делать', 'что меня спрашивали', 'что делает мой холл'
    Возвращается только то, что видит данный сотрудник (с учётом visibility).
    """
    my_tickets:   list[Ticket]
    my_messages:  list[Message]
    role_tickets: list[Ticket]


# ─── Misc ─────────────────────────────────────────────────────────────────────

class FreeStaffResponse(BaseModel):
    """Список свободных людей — используется Алисой и фронтом."""
    staff:         list[Staff]
    total_free:    int
    total_staff:   int
