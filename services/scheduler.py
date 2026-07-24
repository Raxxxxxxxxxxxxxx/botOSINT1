"""Per-source scheduling orchestrator (Phase-2 architecture, sections 2-3).

One APScheduler job per enabled `Source`, running inside the same
asyncio event loop as aiogram (no Celery/Redis — Phase-1 comparison
found that unjustified for this project's scale). Each job is isolated:
one source failing never stops others from being polled in the same
tick, and a per-source circuit breaker backs off after repeated
consecutive failures instead of retrying a broken/blocked site forever.
"""

from __future__ import annotations

import datetime as dt

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlalchemy import select

from config.settings import Settings
from database.engine import get_session
from models.enums import SourceType
from models.news_item import NewsItem
from models.source import Source
from scrapers.base import SourceAdapter
from scrapers.facebook_adapter import FacebookPostsAdapter
from scrapers.facebook_selenium_adapter import SeleniumFacebookAdapter
from scrapers.html_adapter import HTMLSourceAdapter
from scrapers.rss_adapter import RSSSourceAdapter
from services.pipeline import NewsPipeline
from services.publisher import PublishQueue


class SourceScheduler:
    """Owns one APScheduler job per enabled source and runs its poll cycle."""

    def __init__(
        self,
        http_session: aiohttp.ClientSession,
        pipeline: NewsPipeline,
        publish_queue: PublishQueue,
        settings: Settings,
        telegram_adapter: SourceAdapter | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._publish_queue = publish_queue
        self._settings = settings
        self._scheduler = AsyncIOScheduler()
        self._adapters: dict[SourceType, SourceAdapter] = {
            SourceType.RSS: RSSSourceAdapter(http_session),
            SourceType.HTML: HTMLSourceAdapter(http_session),
            SourceType.FACEBOOK: FacebookPostsAdapter(http_session),
        }
        if settings.selenium_facebook_enabled:
            self._adapters[SourceType.FACEBOOK_SELENIUM] = SeleniumFacebookAdapter()
        if telegram_adapter is not None:
            self._adapters[SourceType.TELEGRAM] = telegram_adapter

    async def start(self) -> None:
        """Load enabled sources from the database and schedule one job each."""
        async with get_session() as session:
            result = await session.execute(select(Source).where(Source.enabled.is_(True)))
            sources = list(result.scalars())

        for source in sources:
            self._schedule_source(source)
        self._scheduler.start()
        logger.info("Scheduler started with {} active source(s)", len(sources))

    def stop(self) -> None:
        """Shut down the scheduler without waiting for in-flight jobs."""
        self._scheduler.shutdown(wait=False)

    async def aclose_adapters(self) -> None:
        """Release any adapter-held resources (e.g. a live Selenium browser)."""
        for adapter in self._adapters.values():
            aclose = getattr(adapter, "aclose", None)
            if aclose is not None:
                await aclose()

    def _schedule_source(self, source: Source) -> None:
        trigger = IntervalTrigger(
            seconds=source.poll_interval_seconds,
            jitter=self._settings.scheduler_default_jitter_seconds,
        )
        self._scheduler.add_job(
            self._poll_source,
            trigger=trigger,
            args=[source.id],
            id=f"source-{source.id}",
            max_instances=1,  # never run two polls of the same source concurrently
            coalesce=True,
        )

    async def _poll_source(self, source_id: int) -> None:
        """One poll cycle for a single source: fetch -> pipeline -> publish.

        The network fetch deliberately runs with no DB session held open.
        Adapters can take seconds (a slow site) to tens of seconds (a
        Selenium poll queued behind the shared browser lock), and with 120+
        sources on short intervals, polls land in bursts; holding a pooled
        connection idle for a fetch's whole duration was enough to exhaust
        the pool and time out unrelated sources' polls in production.
        """
        async with get_session() as session:
            source = await session.get(Source, source_id)
            if source is None or not source.enabled:
                return

            if self._is_circuit_open(source):
                logger.debug("Skipping source '{}' (circuit breaker open)", source.name)
                return

            adapter = self._adapters.get(source.type)
            if adapter is None:
                logger.warning("No adapter registered for source type '{}'", source.type.value)
                return

        try:
            raw_items = await adapter.fetch(source)
        except Exception as exc:  # noqa: BLE001 - isolate this source's failure from others
            async with get_session() as session:
                source = await session.merge(source)
                self._record_failure(source, exc)
                await session.commit()
            return

        async with get_session() as session:
            source = await session.merge(source)
            is_first_poll = source.last_success_at is None
            if is_first_poll:
                await self._pipeline.prime_baseline(session, source, raw_items)
                accepted: list[NewsItem] = []
            else:
                accepted = await self._pipeline.process_batch(session, source, raw_items)
            self._record_success(source)
            await session.commit()

        for item in accepted:
            await self._publish_queue.enqueue(item)

    def _is_circuit_open(self, source: Source) -> bool:
        """True if the source is in cooldown and should be skipped this tick."""
        if source.circuit_open_until is None:
            return False
        now = dt.datetime.now(dt.timezone.utc)
        circuit_open_until = source.circuit_open_until
        if circuit_open_until.tzinfo is None:
            circuit_open_until = circuit_open_until.replace(tzinfo=dt.timezone.utc)
        return now < circuit_open_until

    def _record_success(self, source: Source) -> None:
        source.consecutive_failures = 0
        source.circuit_open_until = None
        source.last_success_at = dt.datetime.now(dt.timezone.utc)
        source.last_error = None

    def _record_failure(self, source: Source, exc: Exception) -> None:
        source.consecutive_failures += 1
        source.last_error = str(exc)[:2048]

        if source.consecutive_failures >= self._settings.circuit_breaker_failure_threshold:
            cooldown_seconds = (
                self._settings.circuit_breaker_cooldown_cycles * source.poll_interval_seconds
            )
            source.circuit_open_until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
                seconds=cooldown_seconds
            )
            logger.warning(
                "Source '{}' opened circuit breaker after {} consecutive failures; "
                "cooling down for {}s",
                source.name,
                source.consecutive_failures,
                cooldown_seconds,
            )
        else:
            logger.warning(
                "Source '{}' failed ({} consecutive): {}",
                source.name,
                source.consecutive_failures,
                exc,
            )
