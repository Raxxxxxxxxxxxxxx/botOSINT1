"""Source Adapters package: one adapter class per source type (Phase-2 pattern)."""

from scrapers.base import RawItem, SourceAdapter
from scrapers.facebook_adapter import FacebookPostsAdapter
from scrapers.html_adapter import HTMLSourceAdapter
from scrapers.rss_adapter import RSSSourceAdapter
from scrapers.telegram_adapter import TelegramChannelAdapter

__all__ = [
    "RawItem",
    "SourceAdapter",
    "RSSSourceAdapter",
    "HTMLSourceAdapter",
    "TelegramChannelAdapter",
    "FacebookPostsAdapter",
]
