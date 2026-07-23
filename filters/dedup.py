"""Two-tier duplicate detection (Phase-2 architecture decision).

Tier 1 — exact URL match: a SHA-256 hash lookup against the database.
Cheapest possible check, rejects re-shares of the same link instantly.

Tier 2 — near-duplicate titles: when multiple outlets publish the same
story with different wording, `RecentTitleWindow` compares the
normalized title against only a short rolling window (recent items),
using rapidfuzz — not the full historical table, and not SimHash/MinHash,
per the Phase-1 finding that the added complexity isn't justified for a
single-governorate news volume.
"""

from __future__ import annotations

import datetime as dt
from collections import deque

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.news_item import NewsItem


async def is_duplicate_url(session: AsyncSession, url_hash: str) -> bool:
    """Return True if an item with this exact URL hash already exists."""
    result = await session.execute(
        select(NewsItem.id).where(NewsItem.url_hash == url_hash).limit(1)
    )
    return result.scalar_one_or_none() is not None


class RecentTitleWindow:
    """A bounded, in-memory rolling window of recently seen normalized titles.

    Bounding by both age and count keeps the fuzzy-match cost roughly
    constant regardless of how long the bot has been running — a
    deliberate choice to fit Railway's limited CPU budget.
    """

    def __init__(self, max_items: int = 500, max_age_hours: int = 48) -> None:
        self._max_items = max_items
        self._max_age = dt.timedelta(hours=max_age_hours)
        self._entries: deque[tuple[dt.datetime, str]] = deque(maxlen=max_items)

    def _prune_expired(self) -> None:
        cutoff = dt.datetime.now(dt.timezone.utc) - self._max_age
        while self._entries and self._entries[0][0] < cutoff:
            self._entries.popleft()

    def add(self, normalized_title: str) -> None:
        """Record a title as seen, timestamped now."""
        self._prune_expired()
        self._entries.append((dt.datetime.now(dt.timezone.utc), normalized_title))

    def is_near_duplicate(self, normalized_title: str, threshold: int = 88) -> bool:
        """Return True if a sufficiently similar title was seen recently."""
        self._prune_expired()
        return any(
            fuzz.token_set_ratio(normalized_title, seen_title) >= threshold
            for _, seen_title in self._entries
        )
