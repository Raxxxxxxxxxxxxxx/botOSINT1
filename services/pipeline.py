"""The per-item processing pipeline (Phase-2 architecture, section 4).

Normalize -> Dedup -> Geo-filter -> Categorize -> Enrich -> Persist.

Every item gets a persisted, explicit `status` — including rejected
ones — so *why* an item didn't get published stays diagnosable later
(dedup? not about Raqqa? publish failure?) instead of only ever seeing
"it's not there" (Phase-2 decision, section 5).
"""

from __future__ import annotations

import datetime as dt

import aiohttp
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings, get_settings
from filters.arabic_normalize import normalize_arabic
from filters.categorize import categorize
from filters.dedup import RecentTitleWindow, is_duplicate_url
from filters.geo_filter import is_about_raqqa
from models.enums import ItemStatus
from models.news_item import NewsItem
from models.source import Source
from scrapers.base import RawItem
from services.summarizer import summarize
from utils.hashing import hash_url


class NewsPipeline:
    """Turns raw items from one source poll into persisted `NewsItem` rows.

    One instance is shared across the process lifetime so its
    `RecentTitleWindow` (Tier-2 dedup) keeps state across polling cycles,
    not just within a single batch.
    """

    def __init__(
        self, http_session: aiohttp.ClientSession, settings: Settings | None = None
    ) -> None:
        self._http = http_session
        self._settings = settings or get_settings()
        self._recent_titles = RecentTitleWindow(
            max_items=self._settings.dedup_window_max_items,
            max_age_hours=self._settings.dedup_window_hours,
        )

    async def prime_baseline(
        self, session: AsyncSession, source: Source, raw_items: list[RawItem]
    ) -> None:
        """Record a newly-enabled source's current items as already-seen, unpublished.

        Only called for a source's very first poll (``source.last_success_at
        is None``). Without this, "have we seen this URL before" is
        trivially false for everything on a freshly-enabled source's
        current listing page — for a site with a deep archive (an HTML
        listing has no date filter at all, unlike the Facebook adapter),
        that means the entire backlog, however old, gets published in one
        burst. Priming establishes a baseline silently instead: nothing
        from this first poll is published, but every URL is recorded so
        future polls only surface items that appear after it.
        """
        for raw in raw_items:
            url_hash = hash_url(raw.url)
            if await is_duplicate_url(session, url_hash):
                continue
            item = NewsItem(
                source_id=source.id,
                url=raw.url,
                url_hash=url_hash,
                title=raw.title,
                normalized_title=normalize_arabic(raw.title),
                content=None,
                published_at=raw.published_at,
                fetched_at=dt.datetime.now(dt.timezone.utc),
                status=ItemStatus.REJECTED,
                rejection_reason="baseline_priming",
            )
            session.add(item)
        logger.info(
            "Primed baseline for new source '{}': {} item(s) recorded, none published",
            source.name,
            len(raw_items),
        )

    async def process_batch(
        self, session: AsyncSession, source: Source, raw_items: list[RawItem]
    ) -> list[NewsItem]:
        """Process raw items for one source.

        Every item (accepted or rejected) is added to ``session`` — the
        caller commits once per source poll. Returns only the newly
        *accepted* (PENDING) items, ready for the publish queue.
        """
        accepted: list[NewsItem] = []
        for raw in raw_items:
            item = await self._process_one(session, source, raw)
            if item is not None and item.status is ItemStatus.PENDING:
                accepted.append(item)
        return accepted

    async def _process_one(
        self, session: AsyncSession, source: Source, raw: RawItem
    ) -> NewsItem | None:
        url_hash = hash_url(raw.url)

        # Tier 1 dedup: exact URL, already judged (published OR rejected) before.
        if await is_duplicate_url(session, url_hash):
            return None

        normalized_title = normalize_arabic(raw.title)
        normalized_content = normalize_arabic(raw.content or "")
        combined_text = f"{normalized_title} {normalized_content}"

        if not is_about_raqqa(combined_text, threshold=self._settings.geo_fuzzy_threshold):
            return self._persist_rejected(
                session, source, raw, url_hash, normalized_title, "not_about_raqqa"
            )

        # Tier 2 dedup: near-duplicate title within a short rolling window,
        # catching the same story republished by multiple outlets.
        if self._recent_titles.is_near_duplicate(
            normalized_title, threshold=self._settings.dedup_fuzzy_threshold
        ):
            return self._persist_rejected(
                session, source, raw, url_hash, normalized_title, "near_duplicate_title"
            )
        self._recent_titles.add(normalized_title)

        category = categorize(combined_text)

        # Enrichment is best-effort: a failure here must never drop the item.
        summary: str | None = None
        if raw.content:
            try:
                summary = await summarize(raw.content, self._http)
            except Exception as exc:  # noqa: BLE001 - graceful degradation, not a hard failure
                logger.warning("Summarization failed for {}: {}", raw.url, exc)

        item = NewsItem(
            source_id=source.id,
            url=raw.url,
            url_hash=url_hash,
            title=raw.title,
            normalized_title=normalized_title,
            content=raw.content,
            summary=summary,
            image_url=raw.image_url,
            category=category,
            published_at=raw.published_at,
            fetched_at=dt.datetime.now(dt.timezone.utc),
            status=ItemStatus.PENDING,
        )
        session.add(item)
        return item

    @staticmethod
    def _persist_rejected(
        session: AsyncSession,
        source: Source,
        raw: RawItem,
        url_hash: str,
        normalized_title: str,
        reason: str,
    ) -> None:
        """Persist a rejected item (for diagnosability) and signal "not accepted"."""
        item = NewsItem(
            source_id=source.id,
            url=raw.url,
            url_hash=url_hash,
            title=raw.title,
            normalized_title=normalized_title,
            content=None,
            published_at=raw.published_at,
            fetched_at=dt.datetime.now(dt.timezone.utc),
            status=ItemStatus.REJECTED,
            rejection_reason=reason,
        )
        session.add(item)
        logger.debug("Rejected item '{}' from '{}': {}", raw.url, source.name, reason)
        return None
