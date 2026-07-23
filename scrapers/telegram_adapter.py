"""Optional Telegram-channel monitoring adapter (Telethon userbot).

Phase-1 research finding this exists to address: aiogram (Bot API)
cannot read messages from a channel it isn't an admin of. Telethon,
authenticated as a regular user account via MTProto, was the only
stable pattern found for monitoring other public Raqqa-related Telegram
channels (validated against real projects: streaming_overseer,
Python-Telegram-Auto-Forwarder).

Disabled by default (`TELETHON_ENABLED=false`) per the Phase-2 default
scope decision. Runs inside the same asyncio event loop as the rest of
the bot — no separate process/service.
"""

from __future__ import annotations

from loguru import logger
from telethon import TelegramClient

from models.source import Source
from scrapers.base import RawItem, SourceAdapter


class TelegramChannelAdapter(SourceAdapter):
    """Reads recent messages from a public Telegram channel via Telethon."""

    #: How many recent messages to inspect per poll; the pipeline's
    #: URL-hash dedup stage cheaply discards ones already seen.
    _MESSAGE_LIMIT = 20

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def fetch(self, source: Source) -> list[RawItem]:
        """``source.url`` holds the channel username (e.g. ``some_channel``)."""
        channel_username = source.url.lstrip("@").strip()
        items: list[RawItem] = []
        try:
            async for message in self._client.iter_messages(
                channel_username, limit=self._MESSAGE_LIMIT
            ):
                if not message.text:
                    continue
                url = f"https://t.me/{channel_username}/{message.id}"
                title = message.text.splitlines()[0][:200]
                items.append(
                    RawItem(
                        url=url,
                        title=title,
                        published_at=message.date,
                        content=message.text,
                    )
                )
        except Exception:
            logger.exception(
                "Failed to fetch messages from Telegram channel '{}'", channel_username
            )
            raise
        return items
