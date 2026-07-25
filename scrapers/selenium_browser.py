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

from loguru import logger
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options

from config.settings import get_settings

T = TypeVar("T")


class SeleniumBrowserManager:
    """Owns the one shared Chrome instance used by every Selenium source adapter."""

    def __init__(self) -> None:
        self._driver: webdriver.Chrome | None = None
        self._lock = asyncio.Lock()

    async def run(self, fn: Callable[[webdriver.Chrome], T]) -> T:
        """Run `fn` against the shared driver, serialized behind the one lock.

        Launches the browser on first use. If `fn` raises a
        `WebDriverException` (the browser/session itself broke, not just
        "no content found"), the driver is discarded so the next call
        launches a fresh one instead of repeatedly failing against a dead
        session.
        """
        async with self._lock:
            driver = self._driver or self._launch_driver()
            try:
                return await asyncio.to_thread(fn, driver)
            except WebDriverException:
                logger.warning("Shared Selenium browser hit a WebDriver error; discarding it")
                self._discard_driver()
                raise

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
