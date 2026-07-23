"""The admin panel: a single-owner inline-keyboard dashboard reachable via `/admin`.

Every screen is one edited message (never a new one) — taps feel instant
and the chat doesn't fill up with panel clutter. `IsAdmin` is applied at
the router level, so every handler below is already owner-only; a
non-admin's `/admin` simply falls through to the core router's generic
fallback reply instead of revealing this exists.
"""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from loguru import logger

from config.settings import get_settings
from database.engine import get_session
from models.enums import ItemStatus
from models.news_item import NewsItem
from telegram.admin.callback_data import (
    AdminNav,
    DeleteBySourcePage,
    DeleteBySourcePick,
    DeleteConfirm,
    DeleteScope,
    SourcesPage,
    SourceToggle,
)
from telegram.admin.filters import IsAdmin
from telegram.admin.keyboards import (
    back_to_menu_keyboard,
    delete_confirm_keyboard,
    delete_scope_keyboard,
    delete_source_picker_keyboard,
    main_menu_keyboard,
    sources_page_keyboard,
)
from telegram.admin.queries import (
    Stats,
    get_deletable_items,
    get_sources_page,
    get_sources_with_published_page,
    get_stats,
    toggle_source,
)

router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

_MENU_TEXT = "🎛 <b>لوحة تحكم البوت</b>\n\nاختر قسماً:"

_SCOPE_LABELS: dict[str, str] = {
    "last10": "آخر 10 أخبار",
    "last50": "آخر 50 خبر",
    "today": "اليوم فقط",
    "3days": "آخر 3 أيام",
    "week": "آخر أسبوع",
    "all": "⚠️ كل الأخبار المنشورة",
    "source": "المصدر المحدد",
}


@router.message(Command("admin"))
async def open_panel(message: Message) -> None:
    await message.answer(_MENU_TEXT, reply_markup=main_menu_keyboard())


@router.callback_query(AdminNav.filter(F.screen == "noop"))
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(AdminNav.filter(F.screen == "menu"))
async def show_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(_MENU_TEXT, reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(AdminNav.filter(F.screen == "stats"))
async def show_stats(callback: CallbackQuery) -> None:
    async with get_session() as session:
        stats = await get_stats(session)
    await callback.message.edit_text(
        _format_stats(stats), reply_markup=back_to_menu_keyboard()
    )
    await callback.answer()


def _format_stats(stats: Stats) -> str:
    return (
        "📊 <b>الإحصائيات</b>\n\n"
        f"📨 منشور اليوم: {stats.published_today}\n"
        f"📨 منشور (الإجمالي): {stats.published_total}\n"
        f"⏳ قيد الانتظار: {stats.pending}\n"
        f"🚫 مرفوض: {stats.rejected}\n"
        f"❌ فشل: {stats.failed}\n"
        f"🗑 محذوف: {stats.deleted}\n\n"
        f"🔌 مصادر متوقفة مؤقتاً (circuit breaker): {stats.circuit_open}\n"
        f"🗂 المصادر المفعّلة: {stats.sources_enabled}/{stats.sources_total}"
    )


@router.callback_query(SourcesPage.filter())
async def show_sources_page(callback: CallbackQuery, callback_data: SourcesPage) -> None:
    async with get_session() as session:
        sources, total = await get_sources_page(session, callback_data.page)
    if not sources and callback_data.page > 0:
        await callback.answer("لا توجد صفحة أخرى.", show_alert=False)
        return
    await callback.message.edit_text(
        f"🗂 <b>المصادر</b> ({total})\n\nاضغط على مصدر لتفعيله/تعطيله:",
        reply_markup=sources_page_keyboard(sources, callback_data.page, total),
    )
    await callback.answer()


@router.callback_query(SourceToggle.filter())
async def toggle_source_handler(callback: CallbackQuery, callback_data: SourceToggle) -> None:
    async with get_session() as session:
        new_state = await toggle_source(session, callback_data.source_id)
        if new_state is None:
            await callback.answer("هذا المصدر لم يعد موجوداً.", show_alert=True)
            return
        sources, total = await get_sources_page(session, callback_data.page)
    await callback.message.edit_text(
        f"🗂 <b>المصادر</b> ({total})\n\nاضغط على مصدر لتفعيله/تعطيله:",
        reply_markup=sources_page_keyboard(sources, callback_data.page, total),
    )
    await callback.answer("تم التفعيل ✅" if new_state else "تم التعطيل ❌")


@router.callback_query(AdminNav.filter(F.screen == "delete"))
async def show_delete_scopes(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🗑 <b>حذف أخبار من القناة</b>\n\nاختر نطاق الحذف:",
        reply_markup=delete_scope_keyboard(),
    )
    await callback.answer()


@router.callback_query(DeleteBySourcePage.filter())
async def show_delete_source_picker(
    callback: CallbackQuery, callback_data: DeleteBySourcePage
) -> None:
    async with get_session() as session:
        sources, total = await get_sources_with_published_page(session, callback_data.page)
    if not sources:
        await callback.answer("لا توجد مصادر لديها أخبار منشورة.", show_alert=True)
        return
    await callback.message.edit_text(
        "🗑 اختر المصدر الذي تريد حذف أخباره:",
        reply_markup=delete_source_picker_keyboard(sources, callback_data.page, total),
    )
    await callback.answer()


@router.callback_query(DeleteScope.filter())
async def preview_delete_scope(callback: CallbackQuery, callback_data: DeleteScope) -> None:
    async with get_session() as session:
        items = await get_deletable_items(session, callback_data.scope)
    await callback.message.edit_text(
        _format_preview(callback_data.scope, items),
        reply_markup=(
            delete_confirm_keyboard(callback_data.scope) if items else back_to_menu_keyboard()
        ),
    )
    await callback.answer()


@router.callback_query(DeleteBySourcePick.filter())
async def preview_delete_source(
    callback: CallbackQuery, callback_data: DeleteBySourcePick
) -> None:
    async with get_session() as session:
        items = await get_deletable_items(session, "source", source_id=callback_data.source_id)
    await callback.message.edit_text(
        _format_preview("source", items),
        reply_markup=(
            delete_confirm_keyboard("source", callback_data.source_id)
            if items
            else back_to_menu_keyboard()
        ),
    )
    await callback.answer()


def _format_preview(scope: str, items: list[NewsItem]) -> str:
    label = _SCOPE_LABELS.get(scope, scope)
    if not items:
        return f"🗑 <b>{label}</b>\n\nلا توجد رسائل مطابقة لهذا النطاق."
    sample_titles = "\n".join(f"{i + 1}. {item.title[:70]}" for i, item in enumerate(items[:5]))
    more = f"\n… و{len(items) - 5} أخرى" if len(items) > 5 else ""
    return (
        f"🗑 <b>{label}</b>\n\n"
        f"عدد الرسائل المطابقة: <b>{len(items)}</b>\n\n"
        f"{sample_titles}{more}\n\n"
        "⚠️ هذا الإجراء نهائي ولا يمكن التراجع عنه."
    )


@router.callback_query(DeleteConfirm.filter(F.confirm.is_(False)))
async def cancel_delete(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🗑 <b>حذف أخبار من القناة</b>\n\nاختر نطاق الحذف:",
        reply_markup=delete_scope_keyboard(),
    )
    await callback.answer("تم الإلغاء")


@router.callback_query(DeleteConfirm.filter(F.confirm.is_(True)))
async def confirm_delete(callback: CallbackQuery, callback_data: DeleteConfirm) -> None:
    await callback.answer("جارٍ الحذف...")
    settings = get_settings()
    source_id = callback_data.source_id or None
    async with get_session() as session:
        items = await get_deletable_items(session, callback_data.scope, source_id=source_id)
        deleted, failed = await _delete_items(callback, settings.target_chat_id, items)
        for item in items:
            item.status = ItemStatus.DELETED
        await session.commit()

    result_text = (
        f"🗑 <b>تم تنفيذ الحذف</b>\n\n"
        f"✅ تم حذف: {deleted}\n"
        f"❌ فشل الحذف: {failed}"
    )
    await callback.message.edit_text(result_text, reply_markup=back_to_menu_keyboard())


async def _delete_items(
    callback: CallbackQuery, chat_id: str, items: list[NewsItem]
) -> tuple[int, int]:
    """Delete each item's channel message, pacing calls to respect rate limits."""
    deleted = 0
    failed = 0
    for item in items:
        try:
            await callback.bot.delete_message(chat_id, item.telegram_message_id)
            deleted += 1
        except TelegramAPIError as exc:
            logger.warning(
                "Failed to delete channel message {} for item id={}: {}",
                item.telegram_message_id,
                item.id,
                exc,
            )
            failed += 1
        await asyncio.sleep(0.2)
    return deleted, failed
