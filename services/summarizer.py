"""AI summarization with a mandatory rule-based fallback.

Phase-2 decision: AI summarization calls an external, OpenAI-compatible
API — never a locally loaded model, since Railway's ~512MB RAM ceiling
can't hold one (Phase-1 finding). The same endpoint shape works with
OpenAI directly or with an OpenAI-compatible provider (e.g. OpenRouter)
by changing `AI_API_BASE_URL`/`AI_MODEL` only.

Mirrors the "AI + rule-based fallback" pattern validated in research
(tony-stark-eth/news-aggregator): any failure — feature disabled, missing
key, timeout, non-2xx response — degrades to a simple extractive summary
instead of blocking publication of the item.
"""

from __future__ import annotations

import aiohttp
from loguru import logger

from config.settings import get_settings

_FALLBACK_SENTENCE_COUNT = 2
_MAX_INPUT_CHARS = 4000


async def summarize(text: str, http_session: aiohttp.ClientSession) -> str:
    """Return a short Arabic summary of ``text``.

    Never raises: any failure in the AI path falls back to
    :func:`_fallback_summary` so a failed summarization never prevents
    an item from being published.
    """
    settings = get_settings()
    if settings.ai_summary_enabled and settings.ai_api_key:
        try:
            return await _summarize_via_api(text, http_session)
        except Exception as exc:  # noqa: BLE001 - must degrade gracefully, never propagate
            logger.warning("AI summarization failed, using rule-based fallback: {}", exc)
    return _fallback_summary(text)


async def _summarize_via_api(text: str, http_session: aiohttp.ClientSession) -> str:
    """Call the configured OpenAI-compatible chat-completions endpoint."""
    settings = get_settings()
    url = f"{settings.ai_api_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.ai_model,
        "messages": [
            {
                "role": "system",
                "content": "لخص الخبر التالي بجملتين مختصرتين بالعربية الفصحى دون إبداء رأي.",
            },
            {"role": "user", "content": text[:_MAX_INPUT_CHARS]},
        ],
        "max_tokens": 200,
        "temperature": 0.2,
    }
    timeout = aiohttp.ClientTimeout(total=20)
    async with http_session.post(
        url, json=payload, headers=headers, timeout=timeout
    ) as response:
        response.raise_for_status()
        data = await response.json()
        return str(data["choices"][0]["message"]["content"]).strip()


def _fallback_summary(text: str) -> str:
    """Naive extractive summary: first N sentences. Cheap, dependency-free."""
    normalized = text.replace("!", ".").replace("؟", ".").replace("\n", ".")
    sentences = [s.strip() for s in normalized.split(".") if s.strip()]
    if not sentences:
        return ""
    return "، ".join(sentences[:_FALLBACK_SENTENCE_COUNT]) + "."
