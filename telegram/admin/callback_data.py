"""Typed callback-data schemas for the admin panel's inline keyboards.

Using `CallbackData` factories (rather than hand-built strings) keeps every
button's payload validated and compact, and keeps routing in `router.py`
declarative — matching `SourceToggle.filter()` instead of parsing strings.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class AdminNav(CallbackData, prefix="anav"):
    """Top-level navigation: which admin screen to show."""

    screen: str  # "menu" | "stats" | "sources" | "delete"


class SourcesPage(CallbackData, prefix="asrcpg"):
    """Move to a different page of the sources list."""

    page: int


class SourceToggle(CallbackData, prefix="asrctgl"):
    """Flip one source's enabled flag, then re-render the same page."""

    source_id: int
    page: int


class DeleteScope(CallbackData, prefix="adelscope"):
    """A one-tap delete filter that goes straight to the confirm screen."""

    scope: str  # "last10" | "last50" | "today" | "3days" | "week" | "all"


class DeleteBySourcePage(CallbackData, prefix="adelsrcpg"):
    """Page through the source picker for the "by source" delete filter."""

    page: int


class DeleteBySourcePick(CallbackData, prefix="adelsrcpick"):
    """A specific source chosen for the "by source" delete filter."""

    source_id: int


class DeleteConfirm(CallbackData, prefix="adelconf"):
    """Confirm or cancel a staged delete filter.

    The filter itself rides along in the callback data — simpler than FSM
    state for a single (scope, source_id) pair that's only ever needed for
    one round trip (preview screen -> this button).
    """

    confirm: bool
    scope: str
    source_id: int = 0  # 0 means "not applicable" (CallbackData needs a concrete type)
