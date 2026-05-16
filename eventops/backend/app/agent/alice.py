"""Alice integration and lightweight PoC intent planner."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass

import httpx


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlannedCommand:
    kind: str
    message: str
    title: str | None = None
    description: str | None = None


def audio_not_supported_message() -> str:
    """ABI stub for variant B until SpeechKit implementation is added."""
    return "Поддержка голосовых сообщений не реализована"


class AlicePlanner:
    """
    PoC planner that classifies command into canonical scenarios.

    If external Alice integration is configured later, this class can be swapped
    without changing router/api ABI.
    """

    def __init__(self) -> None:
        self.model = os.getenv("ALICE_MODEL", "poc-rule-based")
        self.api_key = os.getenv("ALICE_API_KEY")
        self.folder_id = os.getenv("ALICE_FOLDER_ID")
        self.timeout_seconds = 15
        self.api_url = os.getenv(
            "ALICE_API_URL",
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        )

    async def plan(self, text: str, *, system_prompt: str | None = None) -> PlannedCommand:
        if not self.api_key or not self.folder_id:
            raise RuntimeError("Alice API is not configured: set ALICE_API_KEY and ALICE_FOLDER_ID")
        if self.model == "poc-rule-based":
            raise RuntimeError("Alice model is not configured: set ALICE_MODEL to real model id")

        remote_plan = await self._plan_remote(text=text, system_prompt=system_prompt)
        if remote_plan is None:
            raise RuntimeError("Alice API request failed or returned invalid response")
        return remote_plan

    def _plan_local(self, text: str) -> PlannedCommand:
        normalized = (text or "").strip()
        lowered = normalized.lower()

        if not normalized:
            return PlannedCommand(
                kind="clarification",
                message="Опиши, что случилось, где и сколько людей нужно.",
            )

        if self._looks_like_unknown(lowered):
            return PlannedCommand(
                kind="answered",
                message="Не понял задачу. Опиши, что случилось, где и сколько людей нужно.",
            )

        if self._needs_clarification(lowered):
            return PlannedCommand(
                kind="clarification",
                message="Уточни, пожалуйста: сколько людей нужно и на какое время?",
            )

        if self._is_info_request(lowered):
            return PlannedCommand(
                kind="informational",
                message="Собираю текущую сводку по тикетам.",
            )

        title = self._extract_title(normalized)
        return PlannedCommand(
            kind="operational",
            message="Принял. Подготовил предложение по задаче.",
            title=title,
            description=normalized,
        )

    @staticmethod
    def _looks_like_unknown(lowered: str) -> bool:
        return lowered in {"ну ты поняла", "ну ты понял", "сделай это", "разберись"}

    @staticmethod
    def _needs_clarification(lowered: str) -> bool:
        return "нужны люди" in lowered or "нужен человек" in lowered

    @staticmethod
    def _is_info_request(lowered: str) -> bool:
        triggers = (
            "что происходит",
            "что сейчас",
            "какая ситуация",
            "что по",
        )
        return any(t in lowered for t in triggers)

    @staticmethod
    def _extract_title(text: str) -> str:
        sentence = re.split(r"[.!?]", text, maxsplit=1)[0].strip()
        return sentence[:200] or "Операционная задача"

    async def _plan_remote(self, *, text: str, system_prompt: str | None) -> PlannedCommand | None:
        request_prompt = (
            "Верни только JSON без markdown в формате "
            '{"kind":"operational|clarification|informational|imprecise|answered",'
            '"message":"...","title":"...","description":"..."}. '
            "Если запрос неясный — kind=clarification или kind=answered."
        )
        payload = {
            "modelUri": self._build_model_uri(),
            "completionOptions": {
                "stream": False,
                "temperature": 0.2,
                "maxTokens": "300",
            },
            "messages": [
                {"role": "system", "text": (system_prompt or "") + "\n\n" + request_prompt},
                {"role": "user", "text": text},
            ],
        }
        api_key = self.api_key or ""
        folder_id = self.folder_id or ""
        headers: dict[str, str] = {
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/json",
            "x-folder-id": folder_id,
        }

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("alice_api_call_ok latency_ms=%.1f model=%s", elapsed_ms, self.model)
            text_reply = self._extract_text_from_response(data)
            if not text_reply:
                return None
            return self._parse_plan_json(text_reply)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("alice_api_call_failed latency_ms=%.1f model=%s error=%s", elapsed_ms, self.model, exc)
            return None

    @staticmethod
    def _extract_text_from_response(data: dict) -> str:
        try:
            return (
                data.get("result", {})
                .get("alternatives", [{}])[0]
                .get("message", {})
                .get("text", "")
                .strip()
            )
        except Exception:
            return ""

    def _parse_plan_json(self, raw_text: str) -> PlannedCommand:
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = clean.strip("`")
            clean = clean.replace("json", "", 1).strip()

        try:
            parsed = json.loads(clean)
        except Exception:
            return self._plan_local(raw_text)

        kind = str(parsed.get("kind", "answered"))
        message = str(parsed.get("message", "Не удалось разобрать ответ модели."))
        title = parsed.get("title")
        description = parsed.get("description")
        if kind not in {"operational", "clarification", "informational", "imprecise", "answered"}:
            kind = "answered"
        return PlannedCommand(
            kind=kind,
            message=message,
            title=str(title) if title is not None else None,
            description=str(description) if description is not None else None,
        )

    def _build_model_uri(self) -> str:
        folder_id = self.folder_id or ""
        model = (self.model or "").strip()
        if model.startswith("gpt://"):
            return model
        # For modern model ids (e.g. yandexgpt-5-lite) URI is usually without /latest.
        return f"gpt://{folder_id}/{model}"
