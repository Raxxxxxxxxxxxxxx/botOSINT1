"""Command handlers for the bot's own chat (not the publish target channel).

Kept intentionally minimal: this bot's job is pushing Raqqa news out, not
holding a conversation (mirrors the `welel/breaking-news-bot` pattern
found during research — a single `/start` reply, everything else gets a
short explanatory notice instead of being silently ignored).
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="core")

_START_MESSAGE = (
    "أهلاً بك 👋\n"
    "هذا البوت ينشر تلقائياً أخبار محافظة الرقة في القناة المخصصة، "
    "ولا يستقبل أو يرد على الرسائل."
)
_FALLBACK_MESSAGE = "هذا البوت يقوم فقط بنشر الأخبار ولا يستقبل الرسائل."


@router.message(Command("start"))
async def handle_start(message: Message) -> None:
    """Reply with a short explanation when a user starts a chat with the bot."""
    await message.answer(_START_MESSAGE)


@router.message()
async def handle_fallback(message: Message) -> None:
    """Catch-all for anything that isn't `/start` — the bot doesn't converse."""
    await message.answer(_FALLBACK_MESSAGE)
