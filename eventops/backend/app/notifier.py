"""Async notification queue for Telegram dispatch (PoC-safe)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any


logger = logging.getLogger(__name__)

_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
_worker_task: asyncio.Task[None] | None = None


async def enqueue_notification(payload: dict[str, str]) -> None:
    telegram_id = (payload.get("telegram_id") or "").strip()
    message = (payload.get("message") or "").strip()
    if not telegram_id or not message:
        return
    await _queue.put({"telegram_id": telegram_id, "message": message})


async def _send_via_telegram_bot_api(payload: dict[str, str]) -> None:
    """PoC sender; replace with real Bot API call in notifier owner's branch."""
    logger.info("notification queued for telegram_id=%s: %s", payload["telegram_id"], payload["message"])


async def _worker() -> None:
    while True:
        payload = await _queue.get()
        try:
            await _send_via_telegram_bot_api(payload)
        except Exception:
            logger.exception("Failed to send Telegram notification")
        finally:
            _queue.task_done()


def start_notifier_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker())


async def stop_notifier_worker() -> None:
    global _worker_task
    if _worker_task is None:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _worker_task = None
