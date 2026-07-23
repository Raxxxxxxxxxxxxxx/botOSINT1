"""Access control for the admin panel: the bot owner only, via `ADMIN_ID`."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from config.settings import get_settings


class IsAdmin(BaseFilter):
    """True only for the configured `ADMIN_ID`; fails closed if unset (0)."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        admin_id = get_settings().admin_id
        user = event.from_user
        return bool(admin_id) and user is not None and user.id == admin_id
