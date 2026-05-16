"""Async notification queue for Telegram dispatch."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org"
TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_SAFE_CHUNK_SIZE = 3900


@dataclass(slots=True)
class Notification:
    message: str
    telegram_id: str | None = None
    disable_notification: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Notification":
        return cls(
            message=str(payload["message"]),
            telegram_id=payload.get("telegram_id"),
            disable_notification=bool(payload.get("disable_notification", False)),
        )


notification_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
_worker_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None


def format_task_notification(*, ticket_id: int, title: str, description: str | None = None) -> str:
    message = f"Новая задача #{ticket_id}: {title}"
    if description:
        message += f"\n{description}"
    return message


async def enqueue_notification(payload: dict[str, Any]) -> None:
    if not payload.get("message"):
        raise ValueError("Notification payload must include message")
    await notification_queue.put(payload)
    logger.info(
        "Queued Telegram notification: telegram_id=%s queue_size=%s",
        payload.get("telegram_id"),
        notification_queue.qsize(),
    )


async def send_telegram(
    client: httpx.AsyncClient,
    token: str,
    telegram_id: str,
    message: str,
    disable_notification: bool = False,
) -> None:
    chunks = _split_telegram_message(message)
    for chunk in chunks:
        logger.info("Sending Telegram message: telegram_id=%s length=%s", telegram_id, len(chunk))
        response = await client.post(
            f"{TELEGRAM_API_URL}/bot{token}/sendMessage",
            json={
                "chat_id": telegram_id,
                "text": chunk,
                "disable_notification": disable_notification,
            },
        )
        if response.is_error:
            logger.error(
                "Telegram API HTTP error: telegram_id=%s status_code=%s response=%s",
                telegram_id,
                response.status_code,
                response.text,
            )
            response.raise_for_status()

        body = response.json()
        if body.get("ok") is not True:
            logger.error(
                "Telegram API rejected message: telegram_id=%s response=%s",
                telegram_id,
                body,
            )
            raise RuntimeError(body)

        result = body.get("result") or {}
        logger.info(
            "Telegram message sent: telegram_id=%s message_id=%s",
            telegram_id,
            result.get("message_id"),
        )


def _split_telegram_message(message: str) -> list[str]:
    if len(message) <= TELEGRAM_MESSAGE_LIMIT:
        return [message]

    chunks: list[str] = []
    remaining = message
    while remaining:
        chunk = remaining[:TELEGRAM_SAFE_CHUNK_SIZE]
        split_at = max(chunk.rfind("\n"), chunk.rfind(". "))
        if split_at > TELEGRAM_SAFE_CHUNK_SIZE // 2:
            chunk = remaining[: split_at + 1]
        chunks.append(chunk.strip())
        remaining = remaining[len(chunk) :].strip()
    return chunks


async def notification_worker(stop_event: asyncio.Event | None = None) -> None:
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")

    async with httpx.AsyncClient(timeout=15) as client:
        while stop_event is None or not stop_event.is_set():
            try:
                payload = await asyncio.wait_for(notification_queue.get(), timeout=1)
            except TimeoutError:
                continue

            notification = Notification.from_payload(payload)
            try:
                if not telegram_token:
                    logger.warning("Telegram notification skipped: TELEGRAM_BOT_TOKEN is not configured")
                    continue
                if not notification.telegram_id:
                    logger.warning("Telegram notification skipped: telegram_id is missing")
                    continue

                await send_telegram(
                    client,
                    telegram_token,
                    notification.telegram_id,
                    notification.message,
                    notification.disable_notification,
                )
            except Exception:
                logger.exception(
                    "Failed to send Telegram notification: telegram_id=%s",
                    notification.telegram_id,
                )
            finally:
                notification_queue.task_done()


def start_notifier_worker() -> None:
    global _stop_event, _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(notification_worker(_stop_event))


async def stop_notifier_worker() -> None:
    global _stop_event, _worker_task
    if _worker_task is None:
        return
    if _stop_event is not None:
        _stop_event.set()
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _stop_event = None
    _worker_task = None
