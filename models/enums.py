"""Shared enumerations used across the database models and pipeline stages."""

from __future__ import annotations

import enum


class SourceType(str, enum.Enum):
    """The kind of adapter a :class:`~models.source.Source` record is fetched with."""

    RSS = "rss"
    HTML = "html"
    TELEGRAM = "telegram"
    # Facebook Page posts via the Apify actor (metered, no local browser needed).
    FACEBOOK = "facebook"
    # Facebook Page posts via a local Selenium/Chrome browser (free, but only
    # viable once self-hosted — see scrapers/facebook_selenium_adapter.py).
    FACEBOOK_SELENIUM = "facebook_selenium"
    # Instagram profile posts via the same shared local Selenium/Chrome browser
    # as FACEBOOK_SELENIUM (see scrapers/instagram_selenium_adapter.py) — login
    # bridges off the Facebook session already in that shared browser profile.
    INSTAGRAM_SELENIUM = "instagram_selenium"
    # Reserved for a future phase (Phase-1 research flagged these as legally/technically
    # fragile in 2026); not implemented by any adapter yet, kept here so adding them later
    # is a data migration, not an architecture change.
    INSTAGRAM = "instagram"
    TWITTER = "twitter"


class ItemStatus(str, enum.Enum):
    """Lifecycle state of a single :class:`~models.news_item.NewsItem`."""

    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"
    DELETED = "deleted"  # published, then removed from the channel via the admin panel
