"""Application entrypoint: wires configuration, database, adapters, the
pipeline, the scheduler, the publish queue, and the aiogram bot together.

Everything runs in a single asyncio event loop / single process, per the
Phase-2 architecture decision (no Celery/Redis, no separate services).
"""

from __future__ import annotations

import asyncio

import aiohttp
from loguru import logger

from config.settings import get_settings
from database.engine import dispose_engine
from database.seed import (
    apply_configured_selectors,
    migrate_facebook_sources_to_selenium,
    seed_sources,
)
from scrapers.base import SourceAdapter
from services.pipeline import NewsPipeline
from services.publisher import PublishQueue
from services.scheduler import SourceScheduler
from telegram.bot import create_bot, create_dispatcher
from utils.logging import configure_logging


async def _build_telegram_adapter(
    http_session: aiohttp.ClientSession,
) -> tuple[SourceAdapter | None, object | None]:
    """Create the optional Telethon-based channel adapter, if enabled.

    Returns ``(adapter, telethon_client)`` — the client is returned
    separately so the caller can disconnect it on shutdown. Both are
    ``None`` when `TELETHON_ENABLED` is false (the Phase-2 default: this
    layer is opt-in).
    """
    settings = get_settings()
    if not settings.telethon_enabled:
        return None, None

    from telethon import TelegramClient

    from scrapers.telegram_adapter import TelegramChannelAdapter

    client = TelegramClient(
        settings.telethon_session_name,
        settings.telethon_api_id,
        settings.telethon_api_hash,
    )
    await client.start()  # first run prompts interactively for phone/code
    logger.info("Telethon userbot connected for channel monitoring")
    return TelegramChannelAdapter(client), client


async def main() -> None:
    """Start the bot and run until interrupted."""
    settings = get_settings()
    settings.validate()
    configure_logging()
    logger.info("Starting Raqqa news bot")

    # Also ensures the curated seed sources (Facebook, disabled HTML/RSS
    # placeholders) exist, and applies any verified CSS selectors on top of
    # them; safe on every boot since both skip rows that already match.
    await seed_sources()
    await apply_configured_selectors()
    await migrate_facebook_sources_to_selenium()

    bot = create_bot(settings)
    dispatcher = create_dispatcher()

    async with aiohttp.ClientSession() as http_session:
        telegram_adapter, telethon_client = await _build_telegram_adapter(http_session)

        pipeline = NewsPipeline(http_session, settings)
        publish_queue = PublishQueue(bot, settings.target_chat_id)
        scheduler = SourceScheduler(
            http_session,
            pipeline,
            publish_queue,
            settings,
            telegram_adapter=telegram_adapter,
        )

        publish_queue.start()
        await scheduler.start()

        try:
            await dispatcher.start_polling(bot)
        finally:
            scheduler.stop()
            await scheduler.aclose_adapters()
            await publish_queue.stop()
            if telethon_client is not None:
                await telethon_client.disconnect()
            await dispose_engine()
            logger.info("Raqqa news bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
