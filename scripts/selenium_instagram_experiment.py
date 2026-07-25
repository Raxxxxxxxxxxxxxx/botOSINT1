"""Standalone experiment: scrape a public Instagram profile's posts with Selenium.

Mirrors scripts/selenium_facebook_experiment.py's validate-before-promote
approach: this is NOT part of the bot's Source Adapter architecture and is
never imported by the running bot. It exists to test, against a real
profile, whether the extraction strategy below actually works before
writing scrapers/instagram_selenium_adapter.py for real.

Extraction strategy: Instagram's profile grid only shows thumbnails (no
caption text, no reliable date), so this script (1) collects post/reel
permalinks from the profile grid, newest-first, then (2) visits each
individual post page and reads its caption + timestamp from the page's
OpenGraph meta tags and its `<time datetime=...>` element. Both are
server-rendered for link-preview purposes and have stayed stable across
Instagram's frequent front-end redesigns, unlike its obfuscated CSS class
names — the same reason facebook_selenium_adapter.py keys off
`div[role='article']` rather than a generated class.

Setup:
    .venv/bin/pip install -r scripts/requirements-selenium.txt
    Chrome or Chromium must be installed locally.
    Reuses FB_SELENIUM_EMAIL / FB_SELENIUM_PASSWORD from .env (same account
    used for the Facebook adapter, per the project owner) — set
    INSTAGRAM_SELENIUM_EMAIL / INSTAGRAM_SELENIUM_PASSWORD instead if a
    different account should be used for Instagram specifically.

    IMPORTANT: this MUST be run wherever the bot's real Chrome profile lives
    (data/selenium_chrome_profile/) — logging in from a different
    machine/browser does not help the deployed bot at all, since the session
    cookies are tied to that one profile directory, not to the account.

Usage:
    .venv/bin/python scripts/selenium_instagram_experiment.py <profile_url>
    .venv/bin/python scripts/selenium_instagram_experiment.py <profile_url> --max-posts 5
    .venv/bin/python scripts/selenium_instagram_experiment.py <profile_url> --headless

Run headed (the default) the first time — Instagram frequently challenges a
login from a new device/IP with an email/SMS verification code or a
"confirm it's you" prompt that only a human can clear. The script pauses
and waits for Enter after opening the browser so you can solve it by hand;
the session is then cached in the shared Chrome profile so subsequent runs
(including --headless ones, and the real bot later) can reuse it without
logging in again.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "data" / "selenium_chrome_profile"

# Instagram's og:description reads like:
# 'N likes, M comments - username on Month Day, Year: "actual caption text"'
_OG_DATE_RE = re.compile(r"\bon\s+([A-Z][a-z]+ \d{1,2}, \d{4})\b")


def build_driver(headless: bool) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,1600")
    options.add_argument("--lang=ar")
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
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
    return driver


def dismiss_dialogs(driver: webdriver.Chrome) -> None:
    """Instagram shows a cookie banner, then (post-login) 'Save info?'/'Notifications?' dialogs."""
    labels = (
        "Allow all cookies",
        "Accept all",
        "قبول الكل",
        "السماح بجميع ملفات تعريف الارتباط",
        "Not now",
        "Not Now",
        "ليس الآن",
    )
    for label in labels:
        try:
            driver.find_element(By.XPATH, f"//button[normalize-space()='{label}']").click()
            time.sleep(0.5)
        except Exception:  # noqa: BLE001 - dialog not present, nothing to dismiss
            continue


_CONTINUE_WITH_FACEBOOK_XPATHS = [
    "//button[contains(., 'Continue with Facebook')]",
    "//div[@role='button'][contains(., 'Continue with Facebook')]",
    "//button[contains(., 'متابعة') and contains(., 'فيسبوك')]",
    "//div[@role='button'][contains(., 'متابعة') and contains(., 'فيسبوك')]",
]


def click_continue_with_facebook(driver: webdriver.Chrome) -> bool:
    """Instagram sometimes bridges login through an existing Facebook session in the
    same Chrome profile ("<Name>, continue with your Facebook account") instead of
    showing a username/password form. Clicking it logs into Instagram using that
    linked identity — no separate credentials needed for this path at all.

    Polls for a few seconds rather than checking once: this bridge screen is
    injected client-side after the initial page load, so a single immediate
    check can race it and miss a real click (observed directly — the dialog
    was still on-screen in a screenshot after this function had already
    returned False for that run).
    """
    for xpath in _CONTINUE_WITH_FACEBOOK_XPATHS:
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            ).click()
            return True
        except TimeoutException:
            continue
    return False


def login(driver: webdriver.Chrome, username: str | None, password: str | None, headless: bool) -> None:
    driver.get("https://www.instagram.com/")
    dismiss_dialogs(driver)

    if click_continue_with_facebook(driver):
        print("[*] Found the 'Continue with Facebook' bridge screen — clicked it.")
        time.sleep(4)
        dismiss_dialogs(driver)
    else:
        try:
            username_field = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
        except TimeoutException:
            print("[*] No login form found — likely already logged in via the cached profile.")
            return

        if not (username and password):
            print(
                "[!] A username/password form is showing but no credentials were provided — "
                "can't proceed. Set INSTAGRAM_SELENIUM_EMAIL/_PASSWORD (or "
                "FB_SELENIUM_EMAIL/_PASSWORD) and rerun."
            )
            return

        username_field.send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(4)
        dismiss_dialogs(driver)

    current_url = driver.current_url
    if "challenge" in current_url or "two_factor" in current_url or "accounts/login" in current_url:
        if headless:
            raise RuntimeError(
                "Instagram is asking for extra verification (checkpoint/2FA/suspicious "
                "login). Rerun without --headless so you can solve it by hand once; the "
                "session will then be cached for future --headless runs."
            )
        print(
            "[!] Instagram is asking for extra verification. Solve it in the opened "
            "browser window (email/SMS code, 'confirm it's you', 2FA), then come back "
            "here and press Enter to continue..."
        )
        input()
        dismiss_dialogs(driver)


def collect_post_links(driver: webdriver.Chrome, profile_url: str, max_posts: int) -> list[str]:
    driver.get(profile_url)
    dismiss_dialogs(driver)
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/p/'], a[href*='/reel/']"))
        )
    except TimeoutException:
        print("[!] No post links found on the profile grid (private account, login wall, or empty).")
        return []

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


def extract_post(driver: webdriver.Chrome, post_url: str) -> dict:
    driver.get(post_url)
    dismiss_dialogs(driver)
    time.sleep(1.5)

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

    timestamp = None
    try:
        timestamp = driver.find_element(By.CSS_SELECTOR, "time[datetime]").get_attribute("datetime")
    except NoSuchElementException:
        if description:
            match = _OG_DATE_RE.search(description)
            if match:
                timestamp = match.group(1)

    return {"url": post_url, "text": caption or "", "image_url": image_url, "timestamp": timestamp}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "profile_url", help="Public Instagram profile URL, e.g. https://www.instagram.com/someaccount/"
    )
    parser.add_argument("--max-posts", type=int, default=12)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    username = os.getenv("INSTAGRAM_SELENIUM_EMAIL") or os.getenv("FB_SELENIUM_EMAIL")
    password = os.getenv("INSTAGRAM_SELENIUM_PASSWORD") or os.getenv("FB_SELENIUM_PASSWORD")

    if not (username and password):
        print(
            "[!] No Instagram credentials found in .env (checked "
            "INSTAGRAM_SELENIUM_EMAIL/_PASSWORD, then FB_SELENIUM_EMAIL/_PASSWORD) — "
            "will still try the 'Continue with Facebook' bridge (needs no password), "
            "but can't fall back to typing a username/password if that's not offered."
        )

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    driver = build_driver(args.headless)
    posts: list[dict] = []
    try:
        # Always attempt login — the Facebook-bridge path needs no credentials
        # at all, only the username/password fallback inside it does.
        login(driver, username, password, args.headless)

        post_links = collect_post_links(driver, args.profile_url, args.max_posts)
        for url in post_links:
            print(f"[*] fetching {url}")
            posts.append(extract_post(driver, url))
            time.sleep(1.5)
    finally:
        driver.quit()

    if not posts:
        return

    output_path = args.output or (
        PROJECT_ROOT / "data" / f"selenium_instagram_experiment_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    )
    output_path.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[+] {len(posts)} post(s) extracted -> {output_path}")
    for post in posts[:3]:
        preview = (post["text"] or "(no caption found)")[:120].replace("\n", " ")
        print(f"  - [{post['timestamp']}] {preview}...")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(1)
    main()
