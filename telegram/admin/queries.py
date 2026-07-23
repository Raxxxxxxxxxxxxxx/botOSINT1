"""Database queries backing the admin panel screens.

Kept separate from `router.py` so the Telegram-facing handlers stay about
rendering/navigation, not query construction.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import ItemStatus, SourceType
from models.news_item import NewsItem
from models.source import Source

SOURCES_PER_PAGE = 8
DELETE_SOURCE_PICKER_PER_PAGE = 8


@dataclass(slots=True)
class Stats:
    published_today: int
    published_total: int
    pending: int
    rejected: int
    failed: int
    deleted: int
    circuit_open: int
    sources_enabled: int
    sources_total: int


async def get_stats(session: AsyncSession) -> Stats:
    """One-shot snapshot of pipeline/source health for the stats screen."""
    today_start = dt.datetime.now(dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    async def _count_items(*conditions: object) -> int:
        result = await session.execute(
            select(func.count(NewsItem.id)).where(*conditions)  # type: ignore[arg-type]
        )
        return result.scalar_one()

    published_today = await _count_items(
        NewsItem.status == ItemStatus.PUBLISHED, NewsItem.fetched_at >= today_start
    )
    published_total = await _count_items(NewsItem.status == ItemStatus.PUBLISHED)
    pending = await _count_items(NewsItem.status == ItemStatus.PENDING)
    rejected = await _count_items(NewsItem.status == ItemStatus.REJECTED)
    failed = await _count_items(NewsItem.status == ItemStatus.FAILED)
    deleted = await _count_items(NewsItem.status == ItemStatus.DELETED)

    now = dt.datetime.now(dt.timezone.utc)
    circuit_result = await session.execute(
        select(func.count(Source.id)).where(Source.circuit_open_until > now)
    )
    circuit_open = circuit_result.scalar_one()

    sources_enabled_result = await session.execute(
        select(func.count(Source.id)).where(Source.enabled.is_(True))
    )
    sources_enabled = sources_enabled_result.scalar_one()
    sources_total_result = await session.execute(select(func.count(Source.id)))
    sources_total = sources_total_result.scalar_one()

    return Stats(
        published_today=published_today,
        published_total=published_total,
        pending=pending,
        rejected=rejected,
        failed=failed,
        deleted=deleted,
        circuit_open=circuit_open,
        sources_enabled=sources_enabled,
        sources_total=sources_total,
    )


async def get_sources_page(
    session: AsyncSession, page: int
) -> tuple[list[Source], int]:
    """Return one page of sources (ordered by type, then name) and the total count."""
    total_result = await session.execute(select(func.count(Source.id)))
    total = total_result.scalar_one()

    result = await session.execute(
        select(Source)
        .order_by(Source.type, Source.name)
        .offset(page * SOURCES_PER_PAGE)
        .limit(SOURCES_PER_PAGE)
    )
    return list(result.scalars()), total


async def toggle_source(session: AsyncSession, source_id: int) -> bool | None:
    """Flip a source's `enabled` flag. Returns the new value, or None if not found."""
    source = await session.get(Source, source_id)
    if source is None:
        return None
    source.enabled = not source.enabled
    await session.commit()
    return source.enabled


async def get_sources_with_published_page(
    session: AsyncSession, page: int
) -> tuple[list[Source], int]:
    """Sources that have at least one published item — for the delete-by-source picker."""
    base = (
        select(Source.id)
        .join(NewsItem, NewsItem.source_id == Source.id)
        .where(NewsItem.status == ItemStatus.PUBLISHED)
        .distinct()
    )
    total_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar_one()

    ids_result = await session.execute(
        base.order_by(Source.id)
        .offset(page * DELETE_SOURCE_PICKER_PER_PAGE)
        .limit(DELETE_SOURCE_PICKER_PER_PAGE)
    )
    ids = [row[0] for row in ids_result.all()]
    if not ids:
        return [], total

    sources_result = await session.execute(select(Source).where(Source.id.in_(ids)))
    by_id = {s.id: s for s in sources_result.scalars()}
    return [by_id[i] for i in ids if i in by_id], total


async def get_deletable_items(
    session: AsyncSession, scope: str, source_id: int | None = None
) -> list[NewsItem]:
    """Published, still-on-channel items matching a delete scope.

    `scope` is one of "last10", "last50", "today", "3days", "week", "all",
    or "source" (requires `source_id`).
    """
    query = select(NewsItem).where(
        NewsItem.status == ItemStatus.PUBLISHED,
        NewsItem.telegram_message_id.is_not(None),
    )

    now = dt.datetime.now(dt.timezone.utc)
    if scope == "last10":
        query = query.order_by(NewsItem.fetched_at.desc()).limit(10)
    elif scope == "last50":
        query = query.order_by(NewsItem.fetched_at.desc()).limit(50)
    elif scope == "today":
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.where(NewsItem.fetched_at >= today_start)
    elif scope == "3days":
        query = query.where(NewsItem.fetched_at >= now - dt.timedelta(days=3))
    elif scope == "week":
        query = query.where(NewsItem.fetched_at >= now - dt.timedelta(days=7))
    elif scope == "source":
        if source_id is None:
            return []
        query = query.where(NewsItem.source_id == source_id)
    elif scope != "all":
        return []

    result = await session.execute(query.order_by(NewsItem.fetched_at.desc()))
    return list(result.scalars())


SOURCE_TYPE_LABELS: dict[SourceType, str] = {
    SourceType.HTML: "🌐",
    SourceType.RSS: "📡",
    SourceType.TELEGRAM: "✈️",
    SourceType.FACEBOOK: "📘",
    SourceType.INSTAGRAM: "📷",
    SourceType.TWITTER: "🐦",
}
