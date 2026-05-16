from __future__ import annotations

from types import SimpleNamespace

from app.agent.prompts import (
    build_rag_entity_disambiguation_prompt,
    build_rag_informational_synthesis_prompt,
    build_system_prompt,
)


def test_build_system_prompt_injects_dynamic_sections_and_contract() -> None:
    roles = [
        SimpleNamespace(name="Регистрация", ai_prompt="Встречают участников"),
        SimpleNamespace(name="Live", ai_prompt="Поддержка трансляции"),
    ]
    zones = [SimpleNamespace(name="Вход"), SimpleNamespace(name="Зал A")]

    prompt = build_system_prompt(
        event_name="ICPC Semifinal",
        event_description="Полуфинал соревнований по программированию",
        roles=roles,
        zones=zones,
        free_staff_count=7,
        admin_staff=["- Анна (admin)", "- Максим (admin)"],
        kb_context=["- Регламент: admin://docs/reglament", "- Карта: admin://map/floor-3"],
        confidentiality_rules=[
            "- Контакты жюри — confidential/high",
            "- Решения по дисквалификациям до публикации — confidential/high",
        ],
        incident_summary=["- #12 На регистрации очередь", "- #15 Live: нет сигнала на сцене"],
        recent_dialogue=[
            {"role": "coordinator", "text": "Нужны люди на вход"},
            {"role": "assistant", "text": "Уточни, сколько людей нужно?"},
        ],
    )

    # Dynamic context interpolation
    assert "Название: ICPC Semifinal" in prompt
    assert "Описание: Полуфинал соревнований по программированию" in prompt
    assert "Свободных сотрудников (оценка): 7" in prompt
    assert "- Регистрация: Встречают участников" in prompt
    assert "- Live: Поддержка трансляции" in prompt
    assert "- Вход" in prompt
    assert "- Зал A" in prompt
    assert "- Анна (admin)" in prompt
    assert "- Максим (admin)" in prompt
    assert "- Регламент: admin://docs/reglament" in prompt
    assert "- Карта: admin://map/floor-3" in prompt
    assert "- Контакты жюри — confidential/high" in prompt
    assert "- Решения по дисквалификациям до публикации — confidential/high" in prompt
    assert "- #12 На регистрации очередь" in prompt
    assert "- #15 Live: нет сигнала на сцене" in prompt
    assert "- coordinator: Нужны люди на вход" in prompt
    assert "- assistant: Уточни, сколько людей нужно?" in prompt

    # Key contract snippets
    assert "=== КОНТРАКТ ВЫХОДА (СТРОГО ОДИН JSON, БЕЗ ТЕКСТА ВОКРУГ) ===" in prompt
    assert '"kind": "operational | clarification | informational | answered"' in prompt
    assert '"target": "create | respond | change_status | null"' in prompt
    assert "=== RAG-ОРКЕСТРАЦИЯ (ПСЕВДОКОД, API НЕИЗВЕСТЕН) ===" in prompt
    assert "=== БЕЗОПАСНОСТЬ ===" in prompt

    # Few-shot presence
    assert "=== FEW-SHOT (ОСНОВНОЙ РОУТИНГ) ===" in prompt
    assert "Пример 1 (create + цели по именам):" in prompt
    assert "Пример 3b (create + сущность-роль):" in prompt
    assert "Пример 7 (answered):" in prompt


def test_build_rag_entity_disambiguation_prompt_contains_rules_and_few_shots() -> None:
    prompt = build_rag_entity_disambiguation_prompt()

    assert "Ты — верификатор сопоставления сущностей после RAG." in prompt
    assert "Формат ответа: только JSON (массив id или null), без текста." in prompt
    assert "1) Нельзя возвращать id, если не уверен в соответствии." in prompt
    assert "3) Предпочитай кандидатов с лучшим смысловым совпадением input↔rag" in prompt

    # Few-shot coverage
    assert "Few-shot #1:" in prompt
    assert "Ответ: [1,2]" in prompt
    assert "Few-shot #2 (конфликт):" in prompt
    assert "Ответ: null" in prompt
    assert "Few-shot #3 (ошибка фамилии):" in prompt
    assert "Ответ: [2]" in prompt


def test_build_rag_informational_synthesis_prompt_contains_contract_and_few_shot() -> None:
    prompt = build_rag_informational_synthesis_prompt()

    assert "Ты формируешь финальный informational-ответ по вопросу координатора." in prompt
    assert '"kind": "informational"' in prompt
    assert '"answer": "краткий точный ответ"' in prompt
    assert "1) Используй только факты из rag_fragments." in prompt
    assert "2) Если данных недостаточно/нет — не выдумывай" in prompt
    assert "4) Никаких confidential-утечек." in prompt
    assert "5) Только JSON, без markdown." in prompt

    # Few-shot presence
    assert "Few-shot:" in prompt
    assert 'user_question: "Где туалет рядом с 331?"' in prompt
    assert "Источник: admin://map/floor-3" in prompt
    assert '{"kind":"informational","answer":"Туалет находится рядом с кабинетом 331, в правом крыле (источник: admin://map/floor-3)."' in prompt
