"""Facebook Page posts adapter, via the Apify "Facebook Posts Scraper" actor.

Reactivates the `SourceType.FACEBOOK` slot that Phase-2 reserved but
deliberately left unimplemented (direct Facebook scraping is fragile and
frequently blocked). Apify runs the actual scraping infrastructure; this
adapter just calls its `run-sync-get-dataset-items` API endpoint, which
starts a run, waits (up to 300s) for it to finish, and returns the
resulting posts in one HTTP call — same shape as the RSS/HTML adapters'
single-request `fetch()`.

Each call is a metered Apify usage-credit spend (unlike RSS/HTML, which
only cost bandwidth), so this adapter deliberately narrows scope on every
request via `resultsLimit` and `onlyPostsNewerThan`, rather than pulling
everything and relying on the pipeline's dedup stage to discard repeats.
"""

from __future__ import annotations

import datetime as dt

import aiohttp
from loguru import logger

from config.settings import get_settings
from models.source import Source
from scrapers.base import RawItem, SourceAdapter
from utils.retry import http_retry


class FacebookPostsAdapter(SourceAdapter):
    """Fetches recent posts from a public Facebook Page via Apify.

    ``source.url`` holds the Facebook Page URL (e.g.
    ``https://www.facebook.com/somepage/``), same convention as the HTML
    adapter's listing-page URL.
    """

    def __init__(self, http_session: aiohttp.ClientSession) -> None:
        self._http = http_session

    async def fetch(self, source: Source) -> list[RawItem]:
        settings = get_settings()
        if not settings.apify_api_token:
            logger.warning(
                "Facebook source '{}' skipped: APIFY_API_TOKEN not configured", source.name
            )
            return []

        payload: dict[str, object] = {
            "startUrls": [{"url": source.url}],
            "resultsLimit": settings.apify_facebook_results_limit,
            "onlyPostsNewerThan": _since_expression(
                source.last_success_at, settings.apify_facebook_initial_lookback_days
            ),
        }

        raw_posts = await self._run_actor(payload)

        items: list[RawItem] = []
        for post in raw_posts:
            url = post.get("url") or post.get("topLevelUrl")
            text = post.get("text")
            if not url or not text:
                continue
            items.append(
                RawItem(
                    url=url,
                    title=text.splitlines()[0][:200],
                    published_at=_parse_time(post.get("time")),
                    content=text,
                    image_url=_extract_image(post.get("media")),
                )
            )
        return items

    @http_retry()
    async def _run_actor(self, payload: dict[str, object]) -> list[dict]:
        settings = get_settings()
        url = (
            f"https://api.apify.com/v2/acts/{settings.apify_facebook_actor_id}"
            "/run-sync-get-dataset-items"
        )
        headers = {"Authorization": f"Bearer {settings.apify_api_token}"}
        timeout = aiohttp.ClientTimeout(total=settings.apify_run_timeout_seconds)
        async with self._http.post(
            url, json=payload, headers=headers, timeout=timeout
        ) as response:
            response.raise_for_status()
            return await response.json()


def _since_expression(last_success_at: dt.datetime | None, lookback_days: int) -> str:
    """Date the actor should only return posts newer than.

    Bounds cost: without this, every poll would re-scrape the page's
    entire recent history instead of just what's new since the last
    successful run.
    """
    if last_success_at is None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)
    else:
        cutoff = last_success_at
    return cutoff.strftime("%Y-%m-%d")


def _parse_time(raw: object) -> dt.datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_image(media: object) -> str | None:
    if not isinstance(media, list) or not media:
        return None
    first = media[0]
    if not isinstance(first, dict):
        return None
    return first.get("thumbnail") or first.get("url")
