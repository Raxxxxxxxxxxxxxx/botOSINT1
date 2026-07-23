"""Shared tenacity retry policies.

Phase-1 research finding, applied here: retry only on connection errors
and 408/425/429/5xx responses, with exponential backoff + jitter, and
never retry on 404 (pointless) or 403 (retrying just gets you blocked
harder). Retries are scoped to a single HTTP call — never wrapped
around an entire pipeline run — so one slow source can't stall others.
"""

from __future__ import annotations

import aiohttp
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _is_retryable_error(exc: BaseException) -> bool:
    """Return True only for transient network errors or retryable HTTP statuses."""
    if isinstance(exc, aiohttp.ClientResponseError):
        return exc.status in _RETRYABLE_STATUS_CODES
    return isinstance(exc, (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError))


def http_retry():  # type: ignore[no-untyped-def]
    """Tenacity decorator for a single outbound HTTP call (RSS/HTML fetch)."""
    return retry(
        retry=retry_if_exception(_is_retryable_error),
        wait=wait_random_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
