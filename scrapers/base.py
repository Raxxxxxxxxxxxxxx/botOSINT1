"""The Source Adapter contract (Phase-2 architecture: extensibility model).

Every source *type* (RSS, HTML, Telegram, and — later, if reactivated —
Facebook/Instagram/X) implements this interface once. Every source
*instance* is just a `Source` database row; adding one never requires
touching adapter or orchestrator code.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass

from models.source import Source


@dataclass(slots=True)
class RawItem:
    """A single unprocessed item as returned by any adapter.

    Deliberately source-agnostic: an RSS entry, a scraped `<article>`, and
    a Telegram message all end up shaped like this before entering the
    normalization stage.
    """

    url: str
    title: str
    published_at: dt.datetime | None = None
    content: str | None = None
    image_url: str | None = None


class SourceAdapter(ABC):
    """Base class every source-type adapter implements."""

    @abstractmethod
    async def fetch(self, source: Source) -> list[RawItem]:
        """Fetch and return new raw items for the given source.

        Implementations may mutate caching fields on ``source`` in place
        (``etag``, ``last_modified``, ``last_content_hash``) — the caller
        is responsible for persisting those changes. Transient failures
        must be raised, not swallowed, so the orchestrator's circuit
        breaker can track them.
        """
        raise NotImplementedError
