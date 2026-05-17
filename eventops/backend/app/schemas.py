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
    telegram_id: Optional[str] = None
    telegram_username: Optional[str] = None

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
    telegram_id: Optional[str]        = None
    telegram_username: Optional[str]  = None
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


class RoleShort(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class StaffAuthor(BaseModel):
    id: int
    name: str
    status: StaffStatus
    role: Optional[RoleShort] = None

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
    target:           Optional[dict[str, Any]] = None
    previous_messages: Optional[list[dict[str, Any]]] = Field(
        None,
        description=(
            "Дополнительное поле для ручного создания/импорта тикета. "
            "В agent flow фронт не заполняет это поле: бэкенд сам ведёт цепочку "
            "отдельно для каждого current_staff внутри мероприятия."
        ),
    )

class TicketUpdate(BaseModel):
    title:            Optional[str]            = None
    description:      Optional[str]            = None
    type:             Optional[TicketType]      = None
    priority:         Optional[TicketPriority]  = None
    status:           Optional[TicketStatus]    = None
    visibility:       Optional[Visibility]      = None
    assignee_role_id: Optional[int]            = None
    target:           Optional[dict[str, Any]] = None
    previous_messages: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Ручное обновление цепочки исходных сообщений тикета.",
    )

class TicketAssignmentOut(BaseModel):
    id:          int
    staff:       StaffShort
    assigned_at: datetime
    confirmed:   bool

    model_config = {"from_attributes": True}


class TicketReplyCreate(BaseModel):
    content:    str = Field(..., min_length=1, examples=["Взял задачу, буду через 5 минут"])
    visibility: Visibility = Visibility.public


class TicketReply(BaseModel):
    id:            int
    event_id:      int
    ticket_id:     int
    from_staff_id: int
    sender:        Optional[StaffShort] = None
    content:       str
    visibility:    Visibility
    created_at:    datetime

    model_config = {"from_attributes": True}


class DocumentAttachment(BaseModel):
    id: str
    title: str
    filename: str
    content_type: Optional[str] = None
    size: int
    path: str
    uploaded_by_id: Optional[int] = None
    created_at: datetime


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
    sender:           Optional[StaffShort] = None
    created_by:       Optional[StaffShort] = None
    assignee_role_id: Optional[int]
    target:           dict[str, Any] = {"all": False, "role_ids": [], "staff_ids": []}
    previous_messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Сообщения, из которых была создана задача. Для agent flow цепочка "
            "ведётся бэкендом отдельно для каждого пользователя и сбрасывается "
            "после создания задачи или закрытия вопроса."
        ),
    )
    documents:        list[DocumentAttachment] = Field(default_factory=list)
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

class BroadcastCreate(BaseModel):
    message:              str       = Field(..., min_length=1, examples=["Сбор у штаба через 10 минут"])
    target:               str       = Field("all", pattern=r"^(all|role|staff)$")
    role_id:              Optional[int] = None
    staff_ids:            list[int] = Field(default_factory=list)
    disable_notification: bool      = False
    include_sender:       bool      = False

class BroadcastResponse(BaseModel):
    queued_count: int
    target_staff_ids: list[int]
    skipped_without_telegram_ids: list[int]
    message_ids: list[int]

class Message(BaseModel):
    id:            int
    event_id:      int
    from_staff_id: int
    author:        Optional[StaffAuthor] = None
    to_staff_id:   Optional[int]
    to_role_id:    Optional[int]
    content:       str
    is_read:       bool
    visibility:    Visibility
    created_at:    datetime

    model_config = {"from_attributes": True}


# ─── Knowledge Base & Confidentiality ─────────────────────────────────────────

class KnowledgeBaseLinkCreate(BaseModel):
    title:       str = Field(..., max_length=255)
    url:         str = Field(..., max_length=2048)
    description: Optional[str] = None
    tags:        list[str] = Field(default_factory=list)
    is_active:   bool = True
    visibility:  Visibility = Visibility.public


class KnowledgeBaseLinkUpdate(BaseModel):
    title:       Optional[str] = Field(None, max_length=255)
    url:         Optional[str] = Field(None, max_length=2048)
    description: Optional[str] = None
    tags:        Optional[list[str]] = None
    is_active:   Optional[bool] = None
    visibility:  Optional[Visibility] = None


class KnowledgeBaseLink(KnowledgeBaseLinkCreate):
    id:         int
    event_id:   int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentChunkSearchResult(BaseModel):
    id: int
    event_id: int
    knowledge_base_link_id: Optional[int] = None
    ticket_id: Optional[int] = None
    content: str
    source_title: str
    source_url: Optional[str] = None
    chunk_index: int
    score: Optional[float] = None


class ConfidentialityRuleCreate(BaseModel):
    category:    str = Field(..., max_length=255)
    description: str
    severity:    str = Field("medium", pattern=r"^(low|medium|high)$")
    is_active:   bool = True


class ConfidentialityRuleUpdate(BaseModel):
    category:    Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    severity:    Optional[str] = Field(None, pattern=r"^(low|medium|high)$")
    is_active:   Optional[bool] = None


class ConfidentialityRule(ConfidentialityRuleCreate):
    id:         int
    event_id:   int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Agent ────────────────────────────────────────────────────────────────────

class AgentContextMessage(BaseModel):
    role: str = Field(..., examples=["user"], description="user | assistant | system")
    text: str = Field(..., min_length=1)
    source: Optional[str] = Field(None, description="agent_text | agent_audio | telegram_text | telegram_voice")
    audio_file: Optional[str] = Field(None, description="Путь к сохранённому аудиофайлу, если сообщение было голосовым")


class AgentCommandRequest(BaseModel):
    """
    Главный эндпоинт агента.
    text — текст команды (или распознанный голос).
    audio_base64 — альтернатива тексту: wav/ogg в base64,
                   бэкенд сам прогоняет через STT Алисы.
    context — опциональная предыстория до 20 сообщений; если передана,
              используется вместо сохранённой session-памяти для этого запроса.
    """
    text:          Optional[str]  = Field(None, examples=["На регистрации очередь, нужны люди"])
    audio_base64:  Optional[str]  = None  # base64-encoded audio
    audio_mime_type: Optional[str] = Field(
        None,
        description="MIME type исходной записи браузера, например audio/webm;codecs=opus",
    )
    mode:          str = Field(
        "command",
        pattern=r"^(command|chat|ticket_question)$",
        description=(
            "command — операционная команда координатора с возможным созданием тикетов; "
            "chat — справочный чат без создания тикетов; "
            "ticket_question — вопрос внутри обсуждения тикета без создания новых тикетов."
        ),
    )
    context:       Optional[list[AgentContextMessage]] = Field(
        None,
        max_length=20,
        description="Опциональный контекст диалога до 20 сообщений.",
    )


class TranscriptionRequest(BaseModel):
    """Отладочная ручка для транскрипции входного аудио."""

    audio_base64: str = Field(..., min_length=1, description="Base64-encoded audio payload")
    language: str = Field("ru-RU", description="Язык распознавания")
    audio_mime_type: Optional[str] = Field(
        None,
        description="MIME type исходной записи, например audio/webm;codecs=opus",
    )


class TranscriptionResponse(BaseModel):
    """Результат транскрипции (stub-first контракт)."""

    text: Optional[str] = None
    status: str = Field(..., description="ok | not_implemented | error")
    detail: Optional[str] = None


class AudioSynthesis(BaseModel):
    """Синтезированный голосовой ответ Алисы (base64)."""

    audio_base64: Optional[str] = None
    format: str = Field("oggopus", description="Аудио-формат синтеза")
    status: str = Field(..., description="ok | not_implemented | error")
    detail: Optional[str] = None

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
    action = "answered"         — Алиса дала текстовый ответ (инфо/фолбэк/подтверждение)
    """
    action:      str
    message:     str                      # текст ответа Алисы для UI
    model_response: Optional[str]         = None  # полный текст ответа модели (источник для TTS)
    transcript:  Optional[str]            = None  # распознанный текст входного голосового
    author:      Optional[StaffAuthor]    = None
    author_role: Optional[RoleShort | str] = None
    audio:       Optional[AudioSynthesis] = None
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
