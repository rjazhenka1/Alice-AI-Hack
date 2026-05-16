"""Alice integration and lightweight PoC intent planner."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
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
    target: str | None = None
    title: str | None = None
    description: str | None = None
    assignees: str | list[str] | None = None
    ticket_id: int | None = None
    status: str | None = None
    keywords: list[str] | None = None
    answer: str | None = None


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

    @staticmethod
    def _speechkit_format(audio_mime_type: str | None) -> str:
        normalized = (audio_mime_type or "").split(";", maxsplit=1)[0].strip().lower()
        if normalized in {"audio/ogg", "audio/oga"}:
            return "oggopus"
        if normalized in {"audio/x-wav", "audio/wav", "audio/wave"}:
            return "lpcm"
        if normalized == "audio/mpeg":
            return "mp3"
        return "oggopus"

    @staticmethod
    def _needs_oggopus_conversion(audio_mime_type: str | None) -> bool:
        normalized = (audio_mime_type or "").split(";", maxsplit=1)[0].strip().lower()
        return normalized in {"audio/webm", "audio/mp4", "video/mp4"}

    @staticmethod
    def _convert_to_oggopus(audio: bytes, audio_mime_type: str | None) -> bytes:
        if not SpeechKitClient._needs_oggopus_conversion(audio_mime_type):
            return audio

        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is required to transcribe browser audio")

        suffix = ".webm"
        normalized = (audio_mime_type or "").split(";", maxsplit=1)[0].strip().lower()
        if normalized in {"audio/mp4", "video/mp4"}:
            suffix = ".mp4"

        with tempfile.NamedTemporaryFile(suffix=suffix) as source:
            with tempfile.NamedTemporaryFile(suffix=".ogg") as target:
                source.write(audio)
                source.flush()
                command = [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    source.name,
                    "-vn",
                    "-acodec",
                    "libopus",
                    "-ar",
                    "48000",
                    "-ac",
                    "1",
                    "-b:a",
                    "48k",
                    target.name,
                ]
                try:
                    subprocess.run(command, check=True, capture_output=True)
                except subprocess.CalledProcessError as exc:
                    stderr = exc.stderr.decode("utf-8", errors="ignore").strip()
                    raise RuntimeError(f"ffmpeg failed to convert audio: {stderr}") from exc
                target.seek(0)
                return target.read()

    @staticmethod
    def _normalize_transcription_text(text: str) -> str:
        words = (text or "").split()
        if not words:
            return ""

        deduped: list[str] = []
        index = 0
        while index < len(words):
            repeated = False
            max_window = min(8, (len(words) - index) // 2)
            for window in range(max_window, 0, -1):
                left = [word.lower() for word in words[index : index + window]]
                right = [word.lower() for word in words[index + window : index + window * 2]]
                if left == right:
                    deduped.extend(words[index : index + window])
                    index += window * 2
                    repeated = True
                    break
            if not repeated:
                deduped.append(words[index])
                index += 1

        half = len(deduped) // 2
        if half > 0 and len(deduped) % 2 == 0:
            if [word.lower() for word in deduped[:half]] == [word.lower() for word in deduped[half:]]:
                deduped = deduped[:half]

        return " ".join(deduped).strip()

    async def transcribe_audio_base64(
        self,
        *,
        audio_base64: str,
        language: str = "ru-RU",
        audio_mime_type: str | None = None,
    ) -> str:
        audio = self._decode_audio(audio_base64)
        audio = self._convert_to_oggopus(audio, audio_mime_type)
        audio_format = self._speechkit_format(audio_mime_type)
        start = time.perf_counter()
        params = {
            "folderId": self._folder_id(),
            "lang": language,
            "format": audio_format,
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
            logger.info(
                "speechkit_stt_ok latency_ms=%.1f language=%s format=%s",
                elapsed_ms,
                language,
                audio_format,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "speechkit_stt_failed latency_ms=%.1f language=%s format=%s error=%s",
                elapsed_ms,
                language,
                audio_format,
                exc,
            )
            raise RuntimeError("SpeechKit STT request failed") from exc

        chunks = data.get("chunks")
        if isinstance(chunks, list) and chunks:
            parts: list[str] = []
            previous = ""
            for chunk in chunks:
                part = str(chunk.get("alternatives", [{}])[0].get("text", "")).strip()
                if not part:
                    continue
                if part.lower() == previous.lower():
                    continue
                parts.append(part)
                previous = part
            text = " ".join(parts)
        else:
            text = str(data.get("result", "")).strip()
        text = self._normalize_transcription_text(text)
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


class VisionOCRClient:
    """Yandex Vision OCR client used to extract text from uploaded images."""

    def __init__(self) -> None:
        self.api_key = os.getenv("ALICE_API_KEY")
        self.iam_token = os.getenv("YANDEX_OCR_IAM_TOKEN")
        self.folder_id = os.getenv("ALICE_FOLDER_ID")
        self.timeout_seconds = 30
        self.api_url = os.getenv("YANDEX_OCR_URL", "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText")
        self.model = os.getenv("YANDEX_OCR_MODEL", "page")
        languages = os.getenv("YANDEX_OCR_LANGUAGES", "ru,en")
        self.language_codes = [item.strip() for item in languages.split(",") if item.strip()]

    def _headers(self) -> dict[str, str]:
        if self.iam_token:
            authorization = f"Bearer {self.iam_token}"
        elif self.api_key:
            authorization = f"Api-Key {self.api_key}"
        else:
            raise RuntimeError("Yandex OCR is not configured: set ALICE_API_KEY or YANDEX_OCR_IAM_TOKEN")

        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json",
        }
        if self.folder_id:
            headers["x-folder-id"] = self.folder_id
        return headers

    async def recognize_text(self, *, content: bytes, mime_type: str) -> str:
        if not content:
            return ""

        payload = {
            "content": base64.b64encode(content).decode("ascii"),
            "mimeType": mime_type,
            "languageCodes": self.language_codes,
            "model": self.model,
        }
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.api_url, headers=self._headers(), json=payload)
                response.raise_for_status()
                data = response.json()
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("yandex_ocr_ok latency_ms=%.1f mime_type=%s", elapsed_ms, mime_type)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("yandex_ocr_failed latency_ms=%.1f mime_type=%s error=%s", elapsed_ms, mime_type, exc)
            raise RuntimeError("Yandex OCR request failed") from exc

        annotation = data.get("textAnnotation") or data.get("result", {}).get("textAnnotation") or {}
        text_value = str(annotation.get("markdown") or annotation.get("fullText") or "").strip()
        if text_value:
            return text_value

        blocks = annotation.get("blocks") or []
        lines: list[str] = []
        for block in blocks:
            for line in block.get("lines") or []:
                line_text = str(line.get("text") or "").strip()
                if line_text:
                    lines.append(line_text)
        return "\n".join(lines).strip()


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
            logger.warning("alice_planner_fallback reason=missing_config")
            return self._plan_local(text)
        if self.model == "poc-rule-based":
            logger.warning("alice_planner_fallback reason=poc_rule_based_model")
            return self._plan_local(text)

        remote_plan = await self._plan_remote(text=text, system_prompt=system_prompt)
        if remote_plan is None:
            logger.warning("alice_planner_fallback reason=remote_plan_failed")
            return self._plan_local(text)
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

    async def synthesize_knowledge_answer(
        self,
        *,
        question: str,
        rag_fragments: list[str],
        system_prompt: str,
    ) -> str | None:
        if not self.api_key or not self.folder_id:
            raise RuntimeError("Alice API is not configured: set ALICE_API_KEY and ALICE_FOLDER_ID")
        if self.model == "poc-rule-based":
            raise RuntimeError("Alice model is not configured: set ALICE_MODEL to real model id")

        fragments_text = "\n".join(f"- {fragment}" for fragment in rag_fragments)
        payload = {
            "modelUri": self._build_model_uri(),
            "completionOptions": {
                "stream": False,
                "temperature": 0.1,
                "maxTokens": "500",
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": f"user_question: {question}\nrag_fragments:\n{fragments_text}"},
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
            logger.info("alice_knowledge_synthesis_ok latency_ms=%.1f model=%s", elapsed_ms, self.model)
            text_reply = self._extract_text_from_response(data)
            if not text_reply:
                return None
            return self._parse_answer_json(text_reply)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning("alice_knowledge_synthesis_failed latency_ms=%.1f model=%s error=%s", elapsed_ms, self.model, exc)
            return None

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

        if self._is_knowledge_request(lowered):
            return PlannedCommand(
                kind="knowledge_base",
                message="Ищу ответ в базе знаний.",
                keywords=self._extract_keywords(normalized),
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
    def _is_knowledge_request(lowered: str) -> bool:
        question_words = (
            "где",
            "когда",
            "куда",
            "кто",
            "как",
            "какой",
            "какая",
            "какое",
            "какие",
            "что",
            "есть ли",
            "можно ли",
            "сколько",
        )
        knowledge_words = (
            "база знаний",
            "регламент",
            "инструкция",
            "расписание",
            "карта",
            "аудитория",
            "кабинет",
            "зал",
            "холл",
            "стойка",
            "регистрация",
            "бейдж",
            "маршрут",
            "документ",
            "файл",
            "скрин",
            "скриншот",
            "пдф",
            "pdf",
        )
        return any(word in lowered for word in knowledge_words) or any(
            lowered.startswith(word) or f" {word} " in f" {lowered} " for word in question_words
        )

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        words = re.findall(r"[\wА-Яа-яЁё]+", text)
        stop_words = {
            "что",
            "где",
            "когда",
            "куда",
            "кто",
            "как",
            "какой",
            "какая",
            "какое",
            "какие",
            "есть",
            "можно",
            "ли",
            "про",
            "это",
            "этот",
            "эта",
            "у",
            "в",
            "на",
            "с",
            "и",
            "по",
            "для",
            "из",
        }
        keywords: list[str] = []
        seen: set[str] = set()
        for word in words:
            lowered = word.lower()
            if len(lowered) < 3 or lowered in stop_words or lowered in seen:
                continue
            seen.add(lowered)
            keywords.append(word)
            if len(keywords) >= 8:
                break
        return keywords

    @staticmethod
    def _extract_title(text: str) -> str:
        sentence = re.split(r"[.!?]", text, maxsplit=1)[0].strip()
        return sentence[:200] or "Операционная задача"

    async def _plan_remote(self, *, text: str, system_prompt: str | None) -> PlannedCommand | None:
        request_prompt = (
            "Верни только JSON без markdown в формате "
            '{"kind":"operational|clarification|informational|knowledge_base|answered",'
            '"target":"create|respond|change_status|null","title":"...|null","description":"...|null",'
            '"assignees":"all|[... ]|null","id":"int|null","status":"...|null",'
            '"keywords":"[...]|null","answer":"...|null","text":"..."}. '
            "text должен быть конкретным и полезным: 2-4 коротких предложения, "
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
        text_field = parsed.get("text")
        message_field = parsed.get("message")
        answer_field = parsed.get("answer")
        message = str(text_field or message_field or answer_field or "Не удалось разобрать ответ модели.")
        target_raw = parsed.get("target")
        target = str(target_raw) if target_raw is not None else None
        title = parsed.get("title")
        description = parsed.get("description")
        assignees_raw = parsed.get("assignees")
        assignees: str | list[str] | None
        if isinstance(assignees_raw, str):
            assignees = assignees_raw
        elif isinstance(assignees_raw, list):
            assignees = [str(item) for item in assignees_raw if str(item).strip()]
        else:
            assignees = None

        ticket_id_raw = parsed.get("id")
        try:
            ticket_id = int(ticket_id_raw) if ticket_id_raw is not None else None
        except Exception:
            ticket_id = None

        status_raw = parsed.get("status")
        status = str(status_raw) if status_raw is not None else None

        keywords_raw = parsed.get("keywords")
        keywords = [str(item) for item in keywords_raw] if isinstance(keywords_raw, list) else None

        if kind not in {"operational", "clarification", "informational", "knowledge_base", "imprecise", "answered"}:
            kind = "answered"
        return PlannedCommand(
            kind=kind,
            message=message,
            target=target,
            title=str(title) if title is not None else None,
            description=str(description) if description is not None else None,
            assignees=assignees,
            ticket_id=ticket_id,
            status=status,
            keywords=keywords,
            answer=str(answer_field) if answer_field is not None else None,
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

    @staticmethod
    def _parse_answer_json(raw_text: str) -> str | None:
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = clean.strip("`")
            clean = clean.replace("json", "", 1).strip()

        try:
            parsed = json.loads(clean)
        except Exception:
            return clean or None

        answer = parsed.get("answer") or parsed.get("text")
        if answer is None:
            return None
        normalized = str(answer).strip()
        return normalized or None

    def _build_model_uri(self) -> str:
        folder_id = self.folder_id or ""
        model = (self.model or "").strip()
        if model.startswith("gpt://"):
            return model
        # For modern model ids (e.g. yandexgpt-5-lite) URI is usually without /latest.
        return f"gpt://{folder_id}/{model}"
