"""One-off script: log in interactively and save the Telethon session file
at the path the app expects (config.settings.telethon_session_name).

Run once locally:
    .venv/bin/python scripts/make_telethon_session.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient

from config.settings import get_settings


async def main() -> None:
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.telethon_session_name) or ".", exist_ok=True)

    client = TelegramClient(
        settings.telethon_session_name,
        settings.telethon_api_id,
        settings.telethon_api_hash,
    )
    await client.start()  # prompts for phone number + login code on first run
    me = await client.get_me()
    print(f"✅ Session saved to {settings.telethon_session_name}.session")
    print(f"   Logged in as: {me.first_name or ''} {me.last_name or ''} (@{me.username})".strip())
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
