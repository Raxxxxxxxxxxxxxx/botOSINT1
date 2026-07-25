"""Shared Selenium/Chrome browser manager for every `*_SELENIUM` source adapter.

One real Chrome process, pointed at one persistent profile directory
(`selenium_chrome_profile_dir`), is shared across every Selenium-based
platform adapter (Facebook, Instagram, ...) rather than each adapter
launching its own — Chrome only allows a single process to hold a given
`--user-data-dir` at a time, and a second process pointed at the same
directory steals or crashes the first one's session (observed directly:
running the Instagram experiment script twice concurrently against the
Facebook adapter's profile produced exactly this crash).

These adapters deliberately share one profile for a second reason beyond
just avoiding that conflict: Instagram login through this profile works by
bridging off an already-logged-in Facebook session in the very same
profile ("Continue with Facebook") rather than a separate username/password
flow — splitting them into separate profiles would break that.

A single `asyncio.Lock` serializes every adapter's use of the one browser
instance, same as facebook_selenium_adapter.py did on its own before this
was extracted.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, TypeVar

from aiogram import Bot
from loguru import logger
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from config.settings import get_settings

T = TypeVar("T")

# URL fragments Facebook/Instagram use for their own login-wall/checkpoint
# pages — a reliable signal that the whole shared session needs a human to
# re-authenticate, as opposed to "this specific page just has no posts
# right now". Confirmed directly in production: Facebook's automation
# checkpoint lands on a `/checkpoint/...` URL.
_LOGGED_OUT_URL_MARKERS = ("/checkpoint/", "/challenge/", "/accounts/login")


def is_logged_out(driver: webdriver.Chrome) -> bool:
    """True if the current page looks like a login wall/checkpoint.

    Used by every `*_SELENIUM` adapter right after navigating, to tell "no
    content on this particular page" (normal, not a failure) apart from
    "the shared session itself is logged out" (a real failure that should
    alert someone, since it silently blocks every source sharing this
    browser until a human re-authenticates).
    """
    if any(marker in driver.current_url for marker in _LOGGED_OUT_URL_MARKERS):
        return True
    return bool(driver.find_elements(By.CSS_SELECTOR, "input[type='password']"))


class SessionLoggedOutError(Exception):
    """Raised by a `*_SELENIUM` adapter when `is_logged_out()` detects a login wall."""


class SeleniumBrowserManager:
    """Owns the one shared Chrome instance used by every Selenium source adapter."""

    def __init__(self, bot: Bot | None = None, admin_id: int = 0) -> None:
        self._driver: webdriver.Chrome | None = None
        self._lock = asyncio.Lock()
        self._bot = bot
        self._admin_id = admin_id
        # Tracks whether the admin has already been told about the *current*
        # logged-out episode, so 98+ sources sharing this one browser send
        # one alert, not one per source per poll — and resets the moment a
        # fetch succeeds again so a *future* episode still alerts.
        self._logged_out_alerted = False

    async def run(self, fn: Callable[[webdriver.Chrome], T]) -> T:
        """Run `fn` against the shared driver, serialized behind the one lock.

        Launches the browser on first use. If `fn` raises a
        `WebDriverException` (the browser/session itself broke, not just
        "no content found"), the driver is discarded so the next call
        launches a fresh one instead of repeatedly failing against a dead
        session. If `fn` raises `SessionLoggedOutError`, the admin is
        alerted once (not once per source) and the error is re-raised so
        the caller's normal per-source failure handling still applies.
        """
        async with self._lock:
            driver = self._driver or self._launch_driver()
            try:
                result = await asyncio.to_thread(fn, driver)
            except SessionLoggedOutError as exc:
                await self._alert_logged_out(str(exc))
                raise
            except WebDriverException:
                logger.warning("Shared Selenium browser hit a WebDriver error; discarding it")
                self._discard_driver()
                raise
            await self._alert_recovered()
            return result

    async def _alert_logged_out(self, detail: str) -> None:
        if self._logged_out_alerted:
            return
        self._logged_out_alerted = True
        logger.warning("Shared Selenium session appears logged out: {}", detail)
        if not (self._bot and self._admin_id):
            return
        try:
            await self._bot.send_message(
                self._admin_id,
                "⚠️ الجلسة المشتركة (فيسبوك/إنستغرام) خرجت من تسجيل الدخول أو حُظرت.\n"
                f"التفاصيل: {detail}\n"
                "راجع السيرفر لإعادة تسجيل الدخول — كل المصادر المشتركة بهذا المتصفح "
                "متوقفة حتى تتم إعادة الدخول.",
            )
        except Exception:  # noqa: BLE001 - alerting must never crash a poll
            logger.exception("Failed to send logged-out alert to admin")

    async def _alert_recovered(self) -> None:
        if not self._logged_out_alerted:
            return
        self._logged_out_alerted = False
        if not (self._bot and self._admin_id):
            return
        try:
            await self._bot.send_message(
                self._admin_id, "✅ الجلسة المشتركة رجعت تعمل بشكل طبيعي."
            )
        except Exception:  # noqa: BLE001 - alerting must never crash a poll
            logger.exception("Failed to send session-recovered alert to admin")

    async def aclose(self) -> None:
        """Quit the shared browser, if one was ever launched. Called on bot shutdown."""
        async with self._lock:
            if self._driver is not None:
                await asyncio.to_thread(self._driver.quit)
                self._driver = None

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
        # Media-heavy timelines (Facebook, Instagram) leave Chrome's disk cache
        # growing unbounded over months of continuous polling (observed
        # ~170MB after a handful of manual test runs). 150MB is plenty to keep
        # sessions warm without the profile directory creeping indefinitely.
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
        logger.info("Launched shared Selenium Chrome instance")
        return driver

    def _discard_driver(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:  # noqa: BLE001 - best-effort cleanup of an already-broken session
                pass
            self._driver = None
