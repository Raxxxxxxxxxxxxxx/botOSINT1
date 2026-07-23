"""aiogram Bot/Dispatcher factory functions."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import Settings
from telegram.admin import admin_router
from telegram.handlers import router as core_router


def create_bot(settings: Settings) -> Bot:
    """Build the aiogram `Bot` instance from application settings."""
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Build the aiogram `Dispatcher` with all routers registered."""
    dispatcher = Dispatcher()
    # Admin router first: a non-admin's /admin (or any admin-only callback)
    # simply doesn't match IsAdmin and falls through to core_router's
    # catch-all, instead of the admin panel ever being reachable by them.
    dispatcher.include_router(admin_router)
    dispatcher.include_router(core_router)
    return dispatcher
