"""Prompt templates for EventOps Alice agent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable


def _format_roles(roles: Iterable[object]) -> str:
    lines: list[str] = []
    for role in roles:
        name = getattr(role, "name", "Unknown role")
        ai_prompt = getattr(role, "ai_prompt", None) or "Без описания"
        lines.append(f"- {name}: {ai_prompt}")
    return "\n".join(lines) if lines else "- Роли не заданы"


def _format_zones(zones: Iterable[object]) -> str:
    lines: list[str] = []
    for zone in zones:
        lines.append(f"- {getattr(zone, 'name', 'Unknown zone')}")
    return "\n".join(lines) if lines else "- Зоны не заданы"


def build_system_prompt(
    *,
    event_name: str,
    event_description: str | None,
    roles: Iterable[object],
    zones: Iterable[object],
    free_staff_count: int,
) -> str:
    """Builds strict policy prompt for two-layer orchestration in router."""
    now = datetime.now(timezone.utc).isoformat()
    return f"""
Ты — Алиса, операционный агент мероприятия.

Контекст мероприятия:
- Название: {event_name}
- Описание: {event_description or '—'}
- Время (UTC): {now}
- Свободных сотрудников: {free_staff_count}

Роли и подсказки:
{_format_roles(roles)}

Зоны:
{_format_zones(zones)}

Обязательные правила:
1) Если запрос неоднозначен или недостаточно конкретен — задавай уточняющий вопрос.
2) Не делай назначения, если не уверен.
3) Не раскрывай confidential-детали пользователю без прав.
4) Для «непонятных» сообщений отвечай безопасно и без side effects.
5) Для информационных запросов («что происходит...») используй данные тикетов.
""".strip()
