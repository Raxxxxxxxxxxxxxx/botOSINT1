"""Standalone experiment: scrape a public Facebook Page's posts with Selenium.

This is NOT part of the bot's Source Adapter architecture and is never
imported by the running bot. `scrapers/facebook_adapter.py` (Apify-based)
is what's actually wired into the scheduler — Phase 2 deliberately ruled
out headless browsers to keep the deployed process light enough for
Railway. This script exists purely to test, locally, whether Selenium can
pull posts at all and how the result compares to the Apify adapter's
output (coverage, cost, reliability) before deciding whether it's worth
building for real.

Setup:
    .venv/bin/pip install -r scripts/requirements-selenium.txt
    Chrome or Chromium must be installed locally.
    Optionally set FB_SELENIUM_EMAIL / FB_SELENIUM_PASSWORD in .env — most
    Page content is hidden from logged-out sessions, so a login is needed
    for anything beyond the first post or two. Use a throwaway/secondary
    Facebook account, not a primary one: automated login is against
    Facebook's Terms of Service and the account used can be checkpointed
    or banned.

Usage:
    .venv/bin/python scripts/selenium_facebook_experiment.py <page_url>
    .venv/bin/python scripts/selenium_facebook_experiment.py <page_url> --max-scrolls 15
    .venv/bin/python scripts/selenium_facebook_experiment.py <page_url> --headless

Run headed (the default) the first time — Facebook frequently interrupts
login with a checkpoint/2FA/"is this you" prompt that only a human can
clear. The script pauses and waits for Enter after opening the browser so
you can solve it by hand; the session is then cached in a local Chrome
profile under data/selenium_chrome_profile/ so subsequent runs (including
--headless ones) can reuse it without logging in again.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
import os

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "data" / "selenium_chrome_profile"
LAST_SENT_STATE_PATH = PROJECT_ROOT / "data" / "selenium_facebook_last_sent.json"
POST_URL_MARKERS = ("/posts/", "/videos/", "/photos/", "story_fbid=", "/permalink/", "/reel/")


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


def dismiss_cookie_banner(driver: webdriver.Chrome) -> None:
    for label in ("Allow all cookies", "قبول الكل", "السماح بجميع الكوكيز"):
        try:
            driver.find_element(By.XPATH, f"//div[@aria-label='{label}']").click()
            return
        except Exception:
            continue


def login(driver: webdriver.Chrome, email: str, password: str, headless: bool) -> None:
    driver.get("https://www.facebook.com/")
    dismiss_cookie_banner(driver)

    try:
        email_field = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.ID, "email"))
        )
    except TimeoutException:
        print("[*] No login form found — likely already logged in via the cached profile.")
        return

    email_field.send_keys(email)
    driver.find_element(By.ID, "pass").send_keys(password)
    driver.find_element(By.NAME, "login").click()
    time.sleep(4)

    if "checkpoint" in driver.current_url or "login" in driver.current_url:
        if headless:
            raise RuntimeError(
                "Facebook is asking for extra verification (checkpoint/2FA). "
                "Rerun without --headless so you can solve it by hand once; "
                "the session will then be cached for future --headless runs."
            )
        print(
            "[!] Facebook is asking for extra verification. Solve it in the "
            "opened browser window (checkpoint / 2FA / 'is this you'), then "
            "come back here and press Enter to continue..."
        )
        input()


def extract_posts(driver: webdriver.Chrome) -> list[dict]:
    posts = []
    for article in driver.find_elements(By.CSS_SELECTOR, "div[role='article']"):
        try:
            text = article.text.strip()
            if not text:
                continue
            url = None
            timestamp_label = None
            for link in article.find_elements(By.TAG_NAME, "a"):
                href = link.get_attribute("href") or ""
                if "comment_id=" in href:
                    continue  # comment permalink, not the post itself — role="article" covers both
                if any(marker in href for marker in POST_URL_MARKERS):
                    url = href.split("&__tn__")[0].split("?__cft__")[0]
                    timestamp_label = link.get_attribute("aria-label")
                    break
            if not url:
                continue
            posts.append({"url": url, "text": text, "timestamp_label": timestamp_label})
        except Exception:
            continue
    return posts


def scrape(driver: webdriver.Chrome, page_url: str, max_scrolls: int) -> list[dict]:
    driver.get(page_url)
    dismiss_cookie_banner(driver)
    time.sleep(3)

    seen: dict[str, dict] = {}
    last_height = driver.execute_script("return document.body.scrollHeight")

    for i in range(max_scrolls):
        for post in extract_posts(driver):
            existing = seen.get(post["url"])
            if not existing or len(post["text"]) > len(existing["text"]):
                seen[post["url"]] = post
        print(f"[*] scroll {i + 1}/{max_scrolls} — {len(seen)} unique posts so far")

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(2.5, 4.5))

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("[*] page height stopped growing — stopping early")
                break
        last_height = new_height

    return list(seen.values())


def load_last_sent_state() -> dict[str, str]:
    if LAST_SENT_STATE_PATH.exists():
        return json.loads(LAST_SENT_STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_last_sent_state(state: dict[str, str]) -> None:
    LAST_SENT_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def send_to_telegram(bot_token: str, chat_id: str, post: dict) -> None:
    text = post["text"]
    if len(text) > 3500:
        text = text[:3500].rsplit(" ", 1)[0] + "…"
    message = f"{text}\n\n{post['url']}"

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    request = urllib.request.Request(api_url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram API HTTP error {exc.code}: {exc.read().decode()}") from exc

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    print(f"[+] Sent to Telegram (message_id={result['result']['message_id']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("page_url", help="Public Facebook Page URL, e.g. https://www.facebook.com/somepage/")
    parser.add_argument("--max-scrolls", type=int, default=10)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--send-latest",
        action="store_true",
        help=(
            "Skip the full scroll-and-dump. Grab only the newest post on the "
            "page and send it to the bot's Telegram chat (BOT_TOKEN / "
            "TARGET_CHAT_ID from .env — same ones the real bot uses). Remembers "
            "the last-sent post per page in data/selenium_facebook_last_sent.json "
            "so reruns don't resend it."
        ),
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    email = os.getenv("FB_SELENIUM_EMAIL")
    password = os.getenv("FB_SELENIUM_PASSWORD")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    driver = build_driver(args.headless)
    try:
        if email and password:
            login(driver, email, password, args.headless)
        else:
            print(
                "[!] FB_SELENIUM_EMAIL / FB_SELENIUM_PASSWORD not set — continuing "
                "logged out. Most Pages show little to nothing without a login."
            )

        if args.send_latest:
            bot_token = os.getenv("BOT_TOKEN")
            chat_id = os.getenv("TARGET_CHAT_ID")
            if not bot_token or not chat_id:
                raise SystemExit("BOT_TOKEN / TARGET_CHAT_ID must be set in .env to use --send-latest")

            driver.get(args.page_url)
            dismiss_cookie_banner(driver)
            time.sleep(3)
            posts = extract_posts(driver)
            if not posts:
                time.sleep(3)
                posts = extract_posts(driver)
            if not posts:
                print("[!] No post found on the page.")
                return

            newest = posts[0]
            state = load_last_sent_state()
            if state.get(args.page_url) == newest["url"]:
                print("[*] Newest post was already sent on a previous run — nothing new.")
                return

            send_to_telegram(bot_token, chat_id, newest)
            state[args.page_url] = newest["url"]
            save_last_sent_state(state)
            return

        posts = scrape(driver, args.page_url, args.max_scrolls)
    finally:
        driver.quit()

    output_path = args.output or (
        PROJECT_ROOT / "data" / f"selenium_facebook_experiment_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    )
    output_path.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[+] {len(posts)} unique posts extracted -> {output_path}")
    for post in posts[:3]:
        preview = post["text"][:120].replace("\n", " ")
        print(f"  - {preview}...")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(1)
    main()
