"""Facebook Page posts adapter using a local Selenium/Chrome browser.

Alternative to `facebook_adapter.py` (Apify-based): no per-poll metered
cost, but requires a real Chrome/Chromium install and a one-time manual
login. The extraction logic and login/profile approach were validated in
`scripts/selenium_facebook_experiment.py` before being promoted here; both
point at the same Chrome profile directory (`selenium_chrome_profile_dir`),
so a login done once via that script is reused automatically — this
adapter never needs to see a password.

Only usable on infrastructure with enough RAM for a real browser process:
the Phase-2 "no headless browser" rule was scoped to Railway's free tier
and no longer applies once self-hosted.

One Chrome instance is shared across every FACEBOOK_SELENIUM source (not
launched per-source or per-poll) — an `asyncio.Lock` serializes concurrent
polls onto it instead of paying for a separate browser process per source.
At roughly 10-20s per page and a several-minute poll interval per source,
sequential fetches comfortably fit inside the scheduling window even with
several dozen sources configured.

Deliberately does not scroll or paginate: it grabs whatever posts are
already visible on load (newest-first on a Page/profile timeline) and lets
the pipeline's existing baseline-priming + URL dedup decide what's new,
the same contract every other adapter follows. This keeps each poll fast
and low-footprint, at the cost of only ever catching up to
`selenium_facebook_max_posts` new posts between two polls of the same
source — acceptable at a several-minute poll interval, but a page that
bursts more posts than that between polls will silently miss the excess.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config.settings import get_settings
from models.source import Source
from scrapers.base import RawItem, SourceAdapter

POST_URL_MARKERS = ("/posts/", "/videos/", "/photos/", "story_fbid=", "/permalink/", "/reel/")


class SeleniumFacebookAdapter(SourceAdapter):
    """Fetches the newest visible posts from a public Facebook Page/profile via Selenium."""

    def __init__(self) -> None:
        self._driver: webdriver.Chrome | None = None
        self._lock = asyncio.Lock()

    async def fetch(self, source: Source) -> list[RawItem]:
        async with self._lock:
            return await asyncio.to_thread(self._fetch_sync, source.url)

    async def aclose(self) -> None:
        """Quit the shared browser, if one was ever launched. Called on bot shutdown."""
        async with self._lock:
            if self._driver is not None:
                await asyncio.to_thread(self._driver.quit)
                self._driver = None

    def _fetch_sync(self, page_url: str) -> list[RawItem]:
        driver = self._driver or self._launch_driver()
        try:
            driver.get(page_url)
            _dismiss_cookie_banner(driver)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='article']"))
            )
        except TimeoutException:
            logger.warning(
                "Selenium Facebook fetch for {} found no posts (login wall, empty page, "
                "or Facebook served a checkpoint)",
                page_url,
            )
            return []
        except WebDriverException as exc:
            logger.warning(
                "Selenium Facebook fetch for {} hit a WebDriver error, recreating the "
                "browser before re-raising: {}",
                page_url,
                exc,
            )
            self._discard_driver()
            raise

        settings = get_settings()
        posts = _extract_posts(driver)[: settings.selenium_facebook_max_posts]
        return [RawItem(url=p["url"], title=_first_line(p["text"]), content=p["text"]) for p in posts]

    def _launch_driver(self) -> webdriver.Chrome:
        settings = get_settings()
        profile_dir = Path(settings.selenium_chrome_profile_dir).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)

        options = Options()
        if settings.selenium_chrome_binary:
            options.binary_location = settings.selenium_chrome_binary
        if settings.selenium_facebook_headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1280,1600")
        options.add_argument("--lang=ar")
        options.add_argument(f"--user-data-dir={profile_dir}")
        # Facebook's timeline is media-heavy; left uncapped, Chrome's disk cache
        # grows unbounded over months of continuous polling (observed ~170MB
        # after a handful of manual test runs). 150MB is plenty to keep the
        # session warm without the profile directory creeping indefinitely.
        options.add_argument("--disk-cache-size=157286400")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
        self._driver = driver
        logger.info("Launched shared Selenium Chrome instance for Facebook polling")
        return driver

    def _discard_driver(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:  # noqa: BLE001 - best-effort cleanup of an already-broken session
                pass
            self._driver = None


def _dismiss_cookie_banner(driver: webdriver.Chrome) -> None:
    for label in ("Allow all cookies", "قبول الكل", "السماح بجميع الكوكيز"):
        try:
            driver.find_element(By.XPATH, f"//div[@aria-label='{label}']").click()
            return
        except Exception:  # noqa: BLE001 - banner not present, nothing to dismiss
            continue


def _extract_posts(driver: webdriver.Chrome) -> list[dict]:
    posts = []
    for article in driver.find_elements(By.CSS_SELECTOR, "div[role='article']"):
        try:
            text = _clean_post_text(article.text.strip())
            if not text:
                continue
            url = None
            for link in article.find_elements(By.TAG_NAME, "a"):
                href = link.get_attribute("href") or ""
                if "comment_id=" in href:
                    continue  # comment permalink, not the post itself — role="article" covers both
                if any(marker in href for marker in POST_URL_MARKERS):
                    url = href.split("&__tn__")[0].split("?__cft__")[0]
                    break
            if not url:
                continue
            posts.append({"url": url, "text": text})
        except Exception:  # noqa: BLE001 - one malformed post must not break the whole page
            continue
    return posts


# Facebook prefixes each post's text with the author name and a relative
# timestamp, separated from the actual body by a lone "·" line, and
# suffixes it with engagement chrome (reaction counts, Like/Comment/Share).
# Neither is real content — stripping both keeps `title`/`content` focused
# on what the post actually says instead of "<Page name>\n3h\n·\n...".
_TRAILING_UI_MARKERS = {"All reactions:", "Like", "Comment", "Share", "View more comments", "See more"}


def _clean_post_text(raw_text: str) -> str:
    lines = raw_text.splitlines()

    body_start = 0
    for i, line in enumerate(lines[:5]):
        if line.strip() in ("·", "•"):
            body_start = i + 1
            break

    body_lines: list[str] = []
    for line in lines[body_start:]:
        if line.strip() in _TRAILING_UI_MARKERS:
            break
        body_lines.append(line)

    cleaned = "\n".join(body_lines).strip()
    return cleaned or raw_text.strip()


def _first_line(text: str) -> str:
    return text.splitlines()[0][:200] if text else ""
