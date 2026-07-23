"""The `Source` model: a configured news source, stored as data (not code).

Adding a new Raqqa news source to the bot means inserting a row here —
never editing adapter or pipeline code. This is what makes the "easy to
add new sources" requirement from the research phase concrete.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from models.enums import SourceType

if TYPE_CHECKING:
    from models.news_item import NewsItem


class Source(Base):
    """A single configured source the bot polls for news items.

    Attributes:
        name: Human-readable label shown in logs (e.g. "SANA - الرقة").
        type: Which adapter (:class:`~scrapers.base.SourceAdapter` subclass)
            knows how to fetch this source.
        url: RSS feed URL, article-listing page URL, or Telegram channel
            username, depending on ``type``.
        enabled: Toggle without deleting the row or touching code.
        poll_interval_seconds: How often the scheduler polls this source.
        etag / last_modified: HTTP conditional-GET cache validators
            (RSS/HTML adapters only) so unchanged feeds aren't re-downloaded.
        last_content_hash: Hash of the last successfully fetched page body,
            used to skip re-parsing unchanged HTML pages.
        consecutive_failures / last_success_at / last_error: Circuit-breaker
            bookkeeping so a broken source backs off instead of being
            retried forever on every scheduler tick.
    """

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)

    # HTTP/content caching (Phase-1 finding: ETag/Last-Modified avoid wasted
    # bandwidth and reduce the risk of being blocked by the source site).
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # HTML adapter configuration (CSS selectors, per-source — data, not code,
    # so a new HTML site is "insert a row", never "write a new scraper").
    list_selector: Mapped[str | None] = mapped_column(String(512), nullable=True)
    fetch_full_article: Mapped[bool] = mapped_column(default=False, nullable=False)
    content_selector: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_selector: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Circuit breaker bookkeeping.
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_success_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    circuit_open_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False
    )

    items: Mapped[list["NewsItem"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<Source id={self.id} name={self.name!r} type={self.type.value}>"
