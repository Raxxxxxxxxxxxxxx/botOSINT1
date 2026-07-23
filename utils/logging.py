"""Centralized loguru configuration.

Call :func:`configure_logging` exactly once, at process startup
(``main.py``), before any other module logs anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from config.settings import get_settings


def configure_logging() -> None:
    """Configure loguru sinks: colored console output + a rotating log file.

    Rotation/retention are enabled so log files don't grow unbounded on
    Railway's limited disk (1GB on the free/trial tier).
    """
    settings = get_settings()
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()  # drop loguru's default handler so we control format/level once

    logger.add(
        sys.stderr,
        level=settings.log_level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
        backtrace=False,
        diagnose=False,
    )
    logger.add(
        log_dir / "bot.log",
        level=settings.log_level,
        rotation="10 MB",
        retention=5,
        compression="zip",
        encoding="utf-8",
        enqueue=True,  # async-safe writes from multiple coroutines
        backtrace=False,
        diagnose=False,
    )

    if settings.sentry_dsn:
        _configure_sentry(settings.sentry_dsn)


def _configure_sentry(dsn: str) -> None:
    """Wire loguru errors into Sentry, if the optional dependency is installed.

    Sentry is intentionally optional (Phase-2 decision): the bot must run
    with zero external monitoring dependencies by default.
    """
    try:
        import sentry_sdk
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but the 'sentry-sdk' package is not installed; "
            "skipping Sentry integration."
        )
        return

    sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0)
    logger.add(_sentry_sink, level="ERROR")


def _sentry_sink(message) -> None:  # type: ignore[no-untyped-def]
    """loguru sink that forwards ERROR+ records to Sentry."""
    import sentry_sdk

    record = message.record
    if record["exception"] is not None:
        sentry_sdk.capture_exception(record["exception"].value)
    else:
        sentry_sdk.capture_message(record["message"], level=record["level"].name.lower())
