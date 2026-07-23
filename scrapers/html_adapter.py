"""Generic HTML-listing scraper adapter.

Configured per-source via CSS selectors stored on the `Source` row
(`list_selector`, and optionally `content_selector`/`image_selector` when
`fetch_full_article` is enabled) — adding a new Raqqa news website means
inserting selectors as data, not writing a new scraper class.

Uses `selectolax` rather than BeautifulSoup: Phase-1 benchmarks showed
5-30x faster HTML parsing, which matters on Railway's limited CPU.

Known trade-off (documented, not accidental): when `fetch_full_article`
is enabled, each item on the listing page triggers a second request for
its article page, *before* the pipeline's URL-based dedup check runs.
For a single-governorate news volume with small listing pages, this is
an acceptable, bounded cost rather than a scalability risk — revisit if
a configured source's listing page grows very large.
"""

from __future__ import annotations

from urllib.parse import urljoin

import aiohttp
from loguru import logger
from selectolax.parser import HTMLParser

from config.settings import get_settings
from models.source import Source
from scrapers.base import RawItem, SourceAdapter
from utils.hashing import hash_content
from utils.retry import http_retry


class HTMLSourceAdapter(SourceAdapter):
    """Scrapes an article-listing page using per-source CSS selectors."""

    def __init__(self, http_session: aiohttp.ClientSession) -> None:
        self._http = http_session

    async def fetch(self, source: Source) -> list[RawItem]:
        if not source.list_selector:
            logger.warning(
                "HTML source '{}' has no list_selector configured; skipping.", source.name
            )
            return []

        body = await self._fetch_text(source.url)
        content_hash = hash_content(body)
        if content_hash == source.last_content_hash:
            logger.debug("HTML source '{}' unchanged (same content hash)", source.name)
            return []
        source.last_content_hash = content_hash

        tree = HTMLParser(body)
        items: list[RawItem] = []
        for node in tree.css(source.list_selector):
            href = node.attributes.get("href") or node.css_first("a")
            if href is None:
                continue
            if isinstance(href, str):
                url = urljoin(source.url, href)
            else:
                link_attr = href.attributes.get("href")
                if not link_attr:
                    continue
                url = urljoin(source.url, link_attr)

            title = node.text(strip=True)
            if not url or not title:
                continue

            content: str | None = None
            image_url: str | None = None
            if source.fetch_full_article:
                content, image_url = await self._fetch_article_details(source, url)

            items.append(RawItem(url=url, title=title, content=content, image_url=image_url))
        return items

    @http_retry()
    async def _fetch_text(self, url: str) -> str:
        settings = get_settings()
        headers = {"User-Agent": settings.http_user_agent}
        timeout = aiohttp.ClientTimeout(total=settings.http_timeout_seconds)
        async with self._http.get(url, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            return await response.text()

    async def _fetch_article_details(
        self, source: Source, article_url: str
    ) -> tuple[str | None, str | None]:
        """Fetch a single article page and extract its content/image, if configured."""
        try:
            body = await self._fetch_text(article_url)
        except Exception as exc:  # noqa: BLE001 - isolate one article's failure
            logger.warning("Failed to fetch article page {}: {}", article_url, exc)
            return None, None

        tree = HTMLParser(body)
        content = None
        if source.content_selector:
            node = tree.css_first(source.content_selector)
            content = node.text(strip=True) if node else None

        image_url = None
        if source.image_selector:
            node = tree.css_first(source.image_selector)
            if node is not None:
                image_url = node.attributes.get("src") or node.attributes.get("data-src")
                if image_url:
                    image_url = urljoin(article_url, image_url)

        return content, image_url
