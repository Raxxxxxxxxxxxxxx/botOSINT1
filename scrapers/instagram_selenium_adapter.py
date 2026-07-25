"""Instagram profile posts adapter using the shared Selenium/Chrome browser.

Validated against a real profile via
`scripts/selenium_instagram_experiment.py` before being promoted here —
same validate-then-promote path `facebook_selenium_adapter.py` took.
Shares its browser instance and Chrome profile with that adapter via
`SeleniumBrowserManager`: Instagram login through this profile works by
bridging off an already-logged-in Facebook session in the very same
profile ("Continue with Facebook"), not a separate username/password flow,
so the two platforms cannot use separate browser instances.

Unlike Facebook's timeline (full post text visible while scrolling),
Instagram's profile grid only shows thumbnails with no caption or date.
This adapter therefore (1) collects post/reel permalinks from the grid,
newest-first, then (2) visits each one individually and reads its
caption, image, and real timestamp from OpenGraph meta tags and a
`<time datetime=...>` element — both are server-rendered for
link-preview purposes and have stayed stable across Instagram's frequent
front-end redesigns, unlike its obfuscated CSS classes.
"""

from __future__ import annotations

import datetime as dt
import re

from loguru import logger
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config.settings import get_settings
from models.source import Source
from scrapers.base import RawItem, SourceAdapter
from scrapers.selenium_browser import SeleniumBrowserManager

# Instagram's og:description reads like:
# 'N likes, M comments - username on Month Day, Year: "actual caption text"'
# — used as a fallback date source when the post page has no <time> element.
_OG_DATE_RE = re.compile(r"\bon\s+([A-Z][a-z]+ \d{1,2}, \d{4})\b")

_DISMISS_LABELS = ("Allow all cookies", "Accept all", "قبول الكل", "Not now", "Not Now", "ليس الآن")


class SeleniumInstagramAdapter(SourceAdapter):
    """Fetches the newest visible posts from a public Instagram profile via Selenium."""

    def __init__(self, browser: SeleniumBrowserManager) -> None:
        self._browser = browser

    async def fetch(self, source: Source) -> list[RawItem]:
        return await self._browser.run(lambda driver: self._fetch_sync(driver, source.url))

    def _fetch_sync(self, driver: webdriver.Chrome, profile_url: str) -> list[RawItem]:
        driver.get(profile_url)
        _dismiss_dialogs(driver)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "a[href*='/p/'], a[href*='/reel/']")
                )
            )
        except TimeoutException:
            logger.warning(
                "Selenium Instagram fetch for {} found no post links (private account, "
                "login wall, or empty grid)",
                profile_url,
            )
            return []

        settings = get_settings()
        post_urls = _collect_post_links(driver, settings.selenium_instagram_max_posts)

        items: list[RawItem] = []
        for post_url in post_urls:
            post = _extract_post(driver, post_url)
            if not post["text"]:
                continue
            items.append(
                RawItem(
                    url=post["url"],
                    title=_first_line(post["text"]),
                    content=post["text"],
                    image_url=post["image_url"],
                    published_at=post["published_at"],
                )
            )
        return items


def _dismiss_dialogs(driver: webdriver.Chrome) -> None:
    for label in _DISMISS_LABELS:
        try:
            driver.find_element(By.XPATH, f"//button[normalize-space()='{label}']").click()
        except Exception:  # noqa: BLE001 - dialog not present, nothing to dismiss
            continue


def _collect_post_links(driver: webdriver.Chrome, max_posts: int) -> list[str]:
    seen: list[str] = []
    for link in driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/'], a[href*='/reel/']"):
        href = link.get_attribute("href") or ""
        if not href:
            continue
        url = href.split("?")[0]
        if url not in seen:
            seen.append(url)
        if len(seen) >= max_posts:
            break
    return seen


def _extract_post(driver: webdriver.Chrome, post_url: str) -> dict:
    driver.get(post_url)
    _dismiss_dialogs(driver)

    description = None
    try:
        description = driver.find_element(
            By.CSS_SELECTOR, "meta[property='og:description']"
        ).get_attribute("content")
    except NoSuchElementException:
        pass

    caption = description
    if description and '"' in description:
        caption = description.split('"', 1)[1].rsplit('"', 1)[0]

    image_url = None
    try:
        image_url = driver.find_element(
            By.CSS_SELECTOR, "meta[property='og:image']"
        ).get_attribute("content")
    except NoSuchElementException:
        pass

    raw_timestamp = None
    try:
        raw_timestamp = driver.find_element(By.CSS_SELECTOR, "time[datetime]").get_attribute(
            "datetime"
        )
    except NoSuchElementException:
        if description:
            match = _OG_DATE_RE.search(description)
            if match:
                raw_timestamp = match.group(1)

    return {
        "url": post_url,
        "text": (caption or "").strip(),
        "image_url": image_url,
        "published_at": _parse_timestamp(raw_timestamp) if raw_timestamp else None,
    }


def _parse_timestamp(raw: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return dt.datetime.strptime(raw, "%B %d, %Y").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _first_line(text: str) -> str:
    return text.splitlines()[0][:200] if text else ""
