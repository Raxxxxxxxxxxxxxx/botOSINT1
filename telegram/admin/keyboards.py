"""Inline keyboard builders for every admin panel screen."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from models.source import Source
from telegram.admin.callback_data import (
    AdminNav,
    DeleteBySourcePage,
    DeleteBySourcePick,
    DeleteConfirm,
    DeleteScope,
    SourcesPage,
    SourceToggle,
)
from telegram.admin.queries import (
    DELETE_SOURCE_PICKER_PER_PAGE,
    SOURCE_TYPE_LABELS,
    SOURCES_PER_PAGE,
)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 الإحصائيات", callback_data=AdminNav(screen="stats"))
    builder.button(text="🗂 المصادر", callback_data=SourcesPage(page=0))
    builder.button(text="🗑 حذف أخبار", callback_data=AdminNav(screen="delete"))
    builder.button(text="🔄 تحديث", callback_data=AdminNav(screen="menu"))
    builder.adjust(2, 2)
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ القائمة الرئيسية", callback_data=AdminNav(screen="menu"))
    return builder.as_markup()


def sources_page_keyboard(sources: list[Source], page: int, total: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for source in sources:
        status_icon = "✅" if source.enabled else "❌"
        type_icon = SOURCE_TYPE_LABELS.get(source.type, "")
        label = f"{status_icon} {type_icon} {source.name}"[:64]
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=SourceToggle(source_id=source.id, page=page).pack(),
            )
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(text="◀️ السابق", callback_data=SourcesPage(page=page - 1).pack())
        )
    total_pages = max(1, (total + SOURCES_PER_PAGE - 1) // SOURCES_PER_PAGE)
    nav_row.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=AdminNav(screen="noop").pack())
    )
    if (page + 1) * SOURCES_PER_PAGE < total:
        nav_row.append(
            InlineKeyboardButton(text="التالي ▶️", callback_data=SourcesPage(page=page + 1).pack())
        )
    builder.row(*nav_row)
    builder.row(
        InlineKeyboardButton(text="⬅️ القائمة الرئيسية", callback_data=AdminNav(screen="menu").pack())
    )
    return builder.as_markup()


def delete_scope_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="آخر 10 أخبار", callback_data=DeleteScope(scope="last10"))
    builder.button(text="آخر 50 خبر", callback_data=DeleteScope(scope="last50"))
    builder.button(text="اليوم فقط", callback_data=DeleteScope(scope="today"))
    builder.button(text="آخر 3 أيام", callback_data=DeleteScope(scope="3days"))
    builder.button(text="آخر أسبوع", callback_data=DeleteScope(scope="week"))
    builder.button(text="حسب مصدر محدد", callback_data=DeleteBySourcePage(page=0))
    builder.button(text="⚠️ كل الأخبار المنشورة", callback_data=DeleteScope(scope="all"))
    builder.button(text="⬅️ القائمة الرئيسية", callback_data=AdminNav(screen="menu"))
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def delete_source_picker_keyboard(
    sources: list[Source], page: int, total: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for source in sources:
        type_icon = SOURCE_TYPE_LABELS.get(source.type, "")
        builder.row(
            InlineKeyboardButton(
                text=f"{type_icon} {source.name}"[:64],
                callback_data=DeleteBySourcePick(source_id=source.id).pack(),
            )
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="◀️ السابق", callback_data=DeleteBySourcePage(page=page - 1).pack()
            )
        )
    total_pages = max(1, (total + DELETE_SOURCE_PICKER_PER_PAGE - 1) // DELETE_SOURCE_PICKER_PER_PAGE)
    nav_row.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=AdminNav(screen="noop").pack())
    )
    if (page + 1) * DELETE_SOURCE_PICKER_PER_PAGE < total:
        nav_row.append(
            InlineKeyboardButton(
                text="التالي ▶️", callback_data=DeleteBySourcePage(page=page + 1).pack()
            )
        )
    builder.row(*nav_row)
    builder.row(
        InlineKeyboardButton(text="⬅️ رجوع", callback_data=AdminNav(screen="delete").pack())
    )
    return builder.as_markup()


def delete_confirm_keyboard(scope: str, source_id: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ تأكيد الحذف",
        callback_data=DeleteConfirm(confirm=True, scope=scope, source_id=source_id),
    )
    builder.button(
        text="❌ إلغاء",
        callback_data=DeleteConfirm(confirm=False, scope=scope, source_id=source_id),
    )
    builder.adjust(2)
    return builder.as_markup()
