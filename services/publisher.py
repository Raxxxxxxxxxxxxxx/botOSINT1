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
import datetime as dt
from html import escape as escape_html

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from loguru import logger
from sqlalchemy import select
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from config.settings import get_settings
from database.engine import get_session
from models.enums import ItemStatus, SourceType
from models.news_item import NewsItem
from models.source import Source

_PARSE_MODE = "HTML"
_TELEGRAM_CAPTION_LIMIT = 1024

try:
    from zoneinfo import ZoneInfo

    _LOCAL_TZ: dt.tzinfo = ZoneInfo("Asia/Damascus")
except Exception:  # pragma: no cover - missing tzdata on a minimal system image
    _LOCAL_TZ = dt.timezone(dt.timedelta(hours=3))

_GOVERNORATE = "الرقة"
_OPEN_SOURCE_LABEL = "مصادر مفتوحة"
_DEFAULT_CLASSIFICATION = "عام"
_DEFAULT_NEWS_TYPE = "إخباري"
_DEFAULT_IMPORTANCE = "عادي"

# اليوم: Python's `weekday()` is Monday=0..Sunday=6, matched 1:1 here.
_ARABIC_WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

_PLATFORM_LABELS = {
    SourceType.FACEBOOK: "فيسبوك",
    SourceType.FACEBOOK_SELENIUM: "فيسبوك",
    SourceType.TELEGRAM: "تيليجرام",
    SourceType.RSS: "موقع إلكتروني",
    SourceType.HTML: "موقع إلكتروني",
    SourceType.INSTAGRAM: "إنستغرام",
    SourceType.TWITTER: "تويتر",
}


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

    async def enqueue_pending_from_db(self) -> int:
        """Re-enqueue any item stuck at PENDING from a previous run.

        The in-memory queue isn't persisted — if the process restarts
        before an accepted item's turn to send comes up, that item
        silently vanishes from the queue while its row stays PENDING
        forever, since nothing else ever revisits it. Confirmed in
        production: 173 items stuck this way, some over 3 days old, after
        a run of frequent deploy-triggered restarts. Called once on
        startup, oldest first.
        """
        async with get_session() as session:
            result = await session.execute(
                select(NewsItem)
                .where(NewsItem.status == ItemStatus.PENDING)
                .order_by(NewsItem.created_at.asc())
            )
            items = list(result.scalars())
        for item in items:
            await self.enqueue(item)
        return len(items)

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
        text = await _format_message(item)
        try:
            # A photo caption longer than Telegram's 1024-char limit fails the
            # send outright; the bulletin template runs well past the old
            # short snippet, so fall back to a plain text message (still
            # carrying the full report) rather than dropping the item after
            # retries exhaust on an unfixable "caption too long" error.
            if item.image_url and len(text) <= _TELEGRAM_CAPTION_LIMIT:
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


async def _format_message(item: NewsItem) -> str:
    """Render a `NewsItem` as the required fielded bulletin template.

    Scraped title/summary text and article URLs (query strings routinely
    contain a bare `&`) are untrusted as far as Telegram's HTML parse mode
    is concerned — an unescaped `<`/`&` makes the whole `sendMessage` call
    fail with "can't parse entities", silently dropping the item after
    exhausting retries. Every dynamic value below is escaped for that
    reason, not because HTML tags are expected in it.
    """
    source = await _load_source(item.source_id)

    local_dt = _to_local(item.published_at or item.fetched_at)
    location = (source.default_location if source else None) or _GOVERNORATE
    outlet = (source.display_name if source else None) or (source.name if source else "")
    platform = _PLATFORM_LABELS.get(source.type, "") if source else ""
    details = item.summary or item.title

    lines = [
        f"المحافظة: {_GOVERNORATE}",
        f"الموقع: {escape_html(location)}",
        f"صنف الخبر: {escape_html(item.classification or _DEFAULT_CLASSIFICATION)}",
        f"نوع الخبر: {escape_html(item.news_type or _DEFAULT_NEWS_TYPE)}",
        f"اهمية الخبر: {escape_html(item.importance or _DEFAULT_IMPORTANCE)}",
    ]
    if outlet:
        lines.append(f"مصدر الخبر: {escape_html(outlet)}")
    lines.append(f"المنصة: {escape_html(platform)}")
    lines.append(f"تاريخ الخبر: {local_dt.day}/{local_dt.month}/{local_dt.year}")
    lines.append(f"اليوم: {_ARABIC_WEEKDAYS[local_dt.weekday()]}")
    lines.append(f"الوقت: {_format_time_of_day(local_dt)}")
    lines.append(f"رابط المنشور: {escape_html(item.url)}")
    lines.append(f"مصدر الخبر: {_OPEN_SOURCE_LABEL}")
    lines.append("تفاصيل الخبر:")
    lines.append(f"#{_GOVERNORATE}")
    lines.append(escape_html(details))
    return "\n".join(lines)


async def _load_source(source_id: int) -> Source | None:
    """Fetch the owning `Source` in its own short-lived session.

    `item` is detached from the session that created it by the time this
    runs (queued, then drained later by the publish worker), so the
    `source` relationship can't be lazy-loaded off it directly.
    """
    async with get_session() as session:
        return await session.get(Source, source_id)


def _to_local(moment: dt.datetime) -> dt.datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(_LOCAL_TZ)


def _format_time_of_day(local_dt: dt.datetime) -> str:
    hour = local_dt.hour
    if hour < 12:
        period = "صباحاً"
    elif hour < 16:
        period = "ظهراً"
    elif hour < 19:
        period = "عصراً"
    else:
        period = "مساءً"
    hour_12 = hour % 12 or 12
    return f"الساعة {hour_12}:{local_dt.minute:02d} {period}"
