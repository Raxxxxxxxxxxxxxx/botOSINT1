"""RSS/Atom feed adapter.

Honors HTTP conditional GET (ETag / Last-Modified) as documented by the
feedparser project — skipping unchanged feeds saves bandwidth for us
and for the publisher, and reduces the risk of being rate-limited or
blocked (Phase-1 research finding).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import aiohttp
import feedparser
from loguru import logger

from config.settings import get_settings
from models.source import Source
from scrapers.base import RawItem, SourceAdapter
from utils.retry import http_retry


class RSSSourceAdapter(SourceAdapter):
    """Fetches and parses an RSS/Atom feed for one :class:`Source`."""

    def __init__(self, http_session: aiohttp.ClientSession) -> None:
        self._http = http_session

    async def fetch(self, source: Source) -> list[RawItem]:
        body, new_etag, new_last_modified = await self._fetch_bytes(source)

        if body is None:
            logger.debug("RSS source '{}' unchanged (304 Not Modified)", source.name)
            return []

        source.etag = new_etag
        source.last_modified = new_last_modified

        parsed = feedparser.parse(body)
        items: list[RawItem] = []
        for entry in parsed.entries:
            url = entry.get("link")
            title = entry.get("title")
            if not url or not title:
                continue
            items.append(
                RawItem(
                    url=url,
                    title=title,
                    published_at=_extract_published(entry),
                    content=_extract_content(entry),
                    image_url=_extract_image(entry),
                )
            )
        return items

    @http_retry()
    async def _fetch_bytes(
        self, source: Source
    ) -> tuple[bytes | None, str | None, str | None]:
        """Conditionally GET the feed; returns ``(None, ...)`` on HTTP 304."""
        settings = get_settings()
        headers = {"User-Agent": settings.http_user_agent}
        if source.etag:
            headers["If-None-Match"] = source.etag
        if source.last_modified:
            headers["If-Modified-Since"] = source.last_modified

        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)
        async with self._http.get(source.url, headers=headers, timeout=timeout) as response:
            if response.status == 304:
                return None, source.etag, source.last_modified
            response.raise_for_status()
            body = await response.read()
            return body, response.headers.get("ETag"), response.headers.get("Last-Modified")


def _extract_published(entry: Any) -> dt.datetime | None:
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed_time:
        return None
    return dt.datetime(*parsed_time[:6], tzinfo=dt.timezone.utc)


def _extract_content(entry: Any) -> str | None:
    if entry.get("summary"):
        return str(entry.summary)
    content_list = entry.get("content")
    if content_list:
        return str(content_list[0].get("value"))
    return None


def _extract_image(entry: Any) -> str | None:
    media = entry.get("media_content") or entry.get("media_thumbnail")
    if media:
        return media[0].get("url")
    for link in entry.get("links", []):
        if str(link.get("type", "")).startswith("image/"):
            return link.get("href")
    return None
