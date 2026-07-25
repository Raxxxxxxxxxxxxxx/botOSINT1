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

The actual browser is owned by a shared `SeleniumBrowserManager`
(scrapers/selenium_browser.py), not this adapter — every `*_SELENIUM`
adapter (Facebook, Instagram, ...) runs through the same one Chrome
process and profile, since Chrome only allows one process per profile
directory at a time. At roughly 10-20s per page and a several-minute poll
interval per source, sequential fetches comfortably fit inside the
scheduling window even with several dozen sources configured across
multiple platforms.

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

from loguru import logger
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config.settings import get_settings
from models.source import Source
from scrapers.base import RawItem, SourceAdapter
from scrapers.selenium_browser import SeleniumBrowserManager, SessionLoggedOutError, is_logged_out

POST_URL_MARKERS = ("/posts/", "/videos/", "/photos/", "story_fbid=", "/permalink/", "/reel/")


class SeleniumFacebookAdapter(SourceAdapter):
    """Fetches the newest visible posts from a public Facebook Page/profile via Selenium."""

    def __init__(self, browser: SeleniumBrowserManager) -> None:
        self._browser = browser

    async def fetch(self, source: Source) -> list[RawItem]:
        return await self._browser.run(lambda driver: self._fetch_sync(driver, source.url))

    def _fetch_sync(self, driver: webdriver.Chrome, page_url: str) -> list[RawItem]:
        driver.get(page_url)
        _dismiss_cookie_banner(driver)
        if is_logged_out(driver):
            raise SessionLoggedOutError(f"Facebook fetch for {page_url} hit a login wall")
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='article']"))
            )
        except TimeoutException:
            logger.warning("Selenium Facebook fetch for {} found no posts", page_url)
            return []

        settings = get_settings()
        posts = _extract_posts(driver)[: settings.selenium_facebook_max_posts]
        return [RawItem(url=p["url"], title=_first_line(p["text"]), content=p["text"]) for p in posts]


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
