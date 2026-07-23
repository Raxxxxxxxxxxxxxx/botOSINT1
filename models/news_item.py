"""The `NewsItem` model: a single piece of news moving through the pipeline."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from models.enums import ItemStatus
from models.source import Source


class NewsItem(Base):
    """A normalized news item collected from a :class:`~models.source.Source`.

    Attributes:
        url: The canonical article/post URL (or Telegram message link).
        url_hash: SHA-256 hex digest of the normalized URL — indexed and
            unique, giving an O(1) exact-duplicate check before any
            heavier fuzzy comparison is attempted.
        normalized_title: Arabic-normalized title used for fuzzy
            near-duplicate detection (rapidfuzz) across sources.
        status: Where this item is in the pipeline; kept explicit instead
            of inferring "exists = published" so rejections/failures stay
            diagnosable (why was this item rejected — dedup? geo filter?
            publish error?).
    """

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)

    published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False
    )

    status: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus), default=ItemStatus.PENDING, nullable=False, index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Set once the publish queue actually sends this item, so the admin panel
    # can delete the corresponding channel message later. Nullable because
    # every non-PUBLISHED item never gets one.
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False
    )

    source: Mapped[Source] = relationship(back_populates="items")

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<NewsItem id={self.id} status={self.status.value} title={self.title!r}>"
