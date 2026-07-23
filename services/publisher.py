"""Centralized Telegram publish queue (Phase-2 architecture, section 6).

A single `asyncio.Queue` feeds every outbound message through one path,
paced by a fixed minimum interval between sends, so Telegram's rate
limits (~1 msg/sec per chat, ~30 msg/sec overall — community-documented
experience, not an official published number, per Phase-1 research) are
respected from a single point instead of multiple concurrent
source-processing tasks racing to send independently.
"""

from __future__ import annotations

import asyncio
from html import escape as escape_html

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from config.settings import get_settings
from database.engine import get_session
from models.enums import ItemStatus
from models.news_item import NewsItem

_PARSE_MODE = "HTML"


class PublishQueue:
    """Serializes outbound Telegram sends behind a simple rate-limited worker."""

    def __init__(self, bot: Bot, chat_id: str) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._queue: asyncio.Queue[NewsItem] = asyncio.Queue()
        self._min_interval = get_settings().publish_min_interval_seconds
        self._worker_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the background worker task that drains the queue."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the background worker (used on graceful shutdown)."""
        if self._worker_task is not None:
            self._worker_task.cancel()
            self._worker_task = None

    async def enqueue(self, item: NewsItem) -> None:
        """Add an accepted item to the outbound queue."""
        await self._queue.put(item)

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                await self._send(item)
            except Exception:  # noqa: BLE001 - one failed send must not kill the worker loop
                logger.exception("Failed to publish item id={} after retries", item.id)
            finally:
                self._queue.task_done()
            await asyncio.sleep(self._min_interval)

    @retry(
        retry=retry_if_exception_type(TelegramAPIError),
        wait=wait_fixed(1),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _send(self, item: NewsItem) -> None:
        text = _format_message(item)
        try:
            if item.image_url:
                message = await self._bot.send_photo(
                    self._chat_id, item.image_url, caption=text, parse_mode=_PARSE_MODE
                )
            else:
                message = await self._bot.send_message(
                    self._chat_id, text, parse_mode=_PARSE_MODE
                )
        except TelegramRetryAfter as exc:
            logger.warning("Hit Telegram flood control; sleeping {}s", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
            raise
        else:
            # Recorded so the admin panel can later delete this exact channel
            # message; item is detached from the session that created it, so
            # this is a fresh, short-lived update by primary key.
            async with get_session() as session:
                db_item = await session.get(NewsItem, item.id)
                if db_item is not None:
                    db_item.status = ItemStatus.PUBLISHED
                    db_item.telegram_message_id = message.message_id
                    await session.commit()


def _format_message(item: NewsItem) -> str:
    """Render a `NewsItem` as a Telegram HTML-formatted message.

    Scraped title/summary text and article URLs (query strings routinely
    contain a bare `&`) are untrusted as far as Telegram's HTML parse mode
    is concerned — an unescaped `<`/`&` makes the whole `sendMessage` call
    fail with "can't parse entities", silently dropping the item after
    exhausting retries.
    """
    lines = [f"📰 <b>{escape_html(item.title)}</b>"]
    if item.summary:
        lines.append(escape_html(item.summary))
    if item.category:
        lines.append(f"🏷 {escape_html(item.category)}")
    lines.append(escape_html(item.url))
    return "\n\n".join(lines)
