"""Alice integration and lightweight PoC intent planner."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import base64
import binascii
from dataclasses import dataclass

import httpx


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlannedCommand:
    kind: str
    message: str
    title: str | None = None
    description: str | None = None


@dataclass(slots=True)
class KnowledgeCaptureDecision:
    useful: bool
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    reason: str | None = None


class SpeechKitClient:
    """Yandex SpeechKit STT/TTS client used by agent audio endpoints."""

    def __init__(self) -> None:
        self.api_key = os.getenv("ALICE_API_KEY")
        self.folder_id = os.getenv("ALICE_FOLDER_ID")
        self.timeout_seconds = 30
        self.stt_url = os.getenv("SPEECHKIT_STT_URL", "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize")
        self.tts_url = os.getenv("SPEECHKIT_TTS_URL", "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize")
        self.tts_voice = os.getenv("SPEECHKIT_TTS_VOICE", "alena")
        self.tts_lang = os.getenv("SPEECHKIT_TTS_LANG", "ru-RU")

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("SpeechKit is not configured: set ALICE_API_KEY")
        headers = {"Authorization": f"Api-Key {self.api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _folder_id(self) -> str:
        if not self.folder_id:
            raise RuntimeError("SpeechKit is not configured: set ALICE_FOLDER_ID")
        return self.folder_id

    @staticmethod
    def _decode_audio(audio_base64: str) -> bytes:
        try:
            return base64.b64decode(audio_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Invalid audio_base64") from exc

    async def transcribe_audio_base64(self, *, audio_base64: str, language: str = "ru-RU") -> str:
        audio = self._decode_audio(audio_base64)
        start = time.perf_counter()
        params = {
            "folderId": self._folder_id(),
            "lang": language,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.stt_url,
                    params=params,
                    headers=self._headers(content_type="application/octet-stream"),
                    content=audio,
                )
                response.raise_for_status()
                data = response.json()
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("speechkit_stt_ok latency_ms=%.1f language=%s", elapsed_ms, language)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("speechkit_stt_failed latency_ms=%.1f language=%s error=%s", elapsed_ms, language, exc)
            raise RuntimeError("SpeechKit STT request failed") from exc

        chunks = data.get("chunks")
        if isinstance(chunks, list) and chunks:
            text = " ".join(str(chunk.get("alternatives", [{}])[0].get("text", "")).strip() for chunk in chunks)
        else:
            text = str(data.get("result", "")).strip()
        if not text:
            raise RuntimeError("SpeechKit STT returned empty transcription")
        return text

    async def synthesize_text_base64(self, *, text: str, voice: str = "alena") -> str:
        normalized = (text or "").strip()
        if not normalized:
            raise RuntimeError("SpeechKit TTS text is empty")

        payload = {
            "folderId": self._folder_id(),
            "text": normalized,
            "lang": self.tts_lang,
            "voice": voice or self.tts_voice,
            "format": "oggopus",
        }

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.tts_url,
                    headers=self._headers(),
                    data=payload,
                )
                response.raise_for_status()
                audio_bytes = response.content
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("speechkit_tts_ok latency_ms=%.1f voice=%s", elapsed_ms, payload["voice"])
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("speechkit_tts_failed latency_ms=%.1f voice=%s error=%s", elapsed_ms, payload["voice"], exc)
            raise RuntimeError("SpeechKit TTS request failed") from exc

        if not audio_bytes:
            raise RuntimeError("SpeechKit TTS returned empty audio")
        return base64.b64encode(audio_bytes).decode("ascii")


class YandexEmbeddingClient:
    """Yandex text-search embeddings for RAG document/query vectors."""

    def __init__(self) -> None:
        self.api_key = os.getenv("ALICE_API_KEY")
        self.folder_id = os.getenv("ALICE_FOLDER_ID")
        self.timeout_seconds = 15
        self.api_url = os.getenv(
            "YANDEX_EMBEDDING_URL",
            "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding",
        )

    async def embed(self, text: str, model: str = "text-search-doc") -> list[float]:
        normalized = (text or "").strip()
        if not normalized:
            raise RuntimeError("Embedding text is empty")
        if not self.api_key or not self.folder_id:
            raise RuntimeError("Yandex embeddings are not configured: set ALICE_API_KEY and ALICE_FOLDER_ID")

        payload = {
            "modelUri": f"emb://{self.folder_id}/{model}",
            "text": normalized,
        }
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.api_url,
                    headers={"Authorization": f"Api-Key {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("yandex_embedding_ok latency_ms=%.1f model=%s", elapsed_ms, model)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("yandex_embedding_failed latency_ms=%.1f model=%s error=%s", elapsed_ms, model, exc)
            raise RuntimeError("Yandex embedding request failed") from exc

        embedding = data.get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError("Yandex embedding response did not include embedding")
        return [float(value) for value in embedding]


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

    async def assess_knowledge_candidate(
        self,
        *,
        conversation: str,
        system_prompt: str,
    ) -> KnowledgeCaptureDecision:
        if not self.api_key or not self.folder_id:
            raise RuntimeError("Alice API is not configured: set ALICE_API_KEY and ALICE_FOLDER_ID")
        if self.model == "poc-rule-based":
            raise RuntimeError("Alice model is not configured: set ALICE_MODEL to real model id")

        payload = {
            "modelUri": self._build_model_uri(),
            "completionOptions": {
                "stream": False,
                "temperature": 0.1,
                "maxTokens": "600",
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": conversation},
            ],
        }
        headers: dict[str, str] = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
            "x-folder-id": self.folder_id,
        }

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("alice_knowledge_capture_ok latency_ms=%.1f model=%s", elapsed_ms, self.model)
            text_reply = self._extract_text_from_response(data)
            if not text_reply:
                return KnowledgeCaptureDecision(useful=False, reason="empty model response")
            return self._parse_knowledge_decision_json(text_reply)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("alice_knowledge_capture_failed latency_ms=%.1f model=%s error=%s", elapsed_ms, self.model, exc)
            return KnowledgeCaptureDecision(useful=False, reason="model request failed")

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
            "message должен быть конкретным и полезным: 2-4 коротких предложения, "
            "без confidential-утечек. Если запрос неясный — kind=clarification или kind=answered."
        )
        payload = {
            "modelUri": self._build_model_uri(),
            "completionOptions": {
                "stream": False,
                "temperature": 0.2,
                "maxTokens": "700",
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

    def _parse_knowledge_decision_json(self, raw_text: str) -> KnowledgeCaptureDecision:
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = clean.strip("`")
            clean = clean.replace("json", "", 1).strip()

        try:
            parsed = json.loads(clean)
        except Exception:
            return KnowledgeCaptureDecision(useful=False, reason="invalid JSON")

        useful = bool(parsed.get("useful"))
        title = parsed.get("title")
        content = parsed.get("content")
        raw_tags = parsed.get("tags") or []
        tags = [str(item) for item in raw_tags if isinstance(item, str)] if isinstance(raw_tags, list) else []
        reason = parsed.get("reason")
        if useful and not str(content or "").strip():
            return KnowledgeCaptureDecision(useful=False, reason="empty useful content")
        return KnowledgeCaptureDecision(
            useful=useful,
            title=str(title) if title is not None else None,
            content=str(content) if content is not None else None,
            tags=tags,
            reason=str(reason) if reason is not None else None,
        )

    def _build_model_uri(self) -> str:
        folder_id = self.folder_id or ""
        model = (self.model or "").strip()
        if model.startswith("gpt://"):
            return model
        # For modern model ids (e.g. yandexgpt-5-lite) URI is usually without /latest.
        return f"gpt://{folder_id}/{model}"
