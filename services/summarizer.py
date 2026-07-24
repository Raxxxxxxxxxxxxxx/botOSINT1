"""AI content analysis with a mandatory rule-based fallback.

Phase-2 decision: AI calls go through an external, OpenAI-compatible
API — never a locally loaded model, since Railway's ~512MB RAM ceiling
can't hold one (Phase-1 finding). The same endpoint shape works with
OpenAI directly or with an OpenAI-compatible provider (e.g. OpenRouter)
by changing `AI_API_BASE_URL`/`AI_MODEL` only.

Mirrors the "AI + rule-based fallback" pattern validated in research
(tony-stark-eth/news-aggregator): any failure — feature disabled, missing
key, timeout, non-2xx response, malformed JSON — degrades to rule-based
values instead of blocking publication or leaving the bulletin template's
fields empty.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import aiohttp
from loguru import logger

from config.settings import get_settings
from filters.arabic_normalize import normalize_arabic
from filters.categorize import categorize

_FALLBACK_SENTENCE_COUNT = 2
_MAX_INPUT_CHARS = 4000
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

# صنف الخبر: mirrors filters.categorize's coarse categories, using the
# shorter labels expected in the published bulletin template.
_CATEGORY_TO_CLASSIFICATION = {
    "أمني وعسكري": "أمني",
    "إنساني": "إنساني",
    "خدمات وبنية تحتية": "خدمي",
    "اقتصادي": "اقتصادي",
    "سياسي": "سياسي",
    "عام": "عام",
}
CLASSIFICATIONS = tuple(dict.fromkeys(_CATEGORY_TO_CLASSIFICATION.values()))
NEWS_TYPES = ("إخباري", "إداري", "أمني", "اجتماعي", "اقتصادي")
IMPORTANCE_LEVELS = ("عاجل", "هام", "عادي")

_DEFAULT_NEWS_TYPE = "إخباري"
_DEFAULT_IMPORTANCE = "عادي"


@dataclass(frozen=True)
class NewsAnalysis:
    """Structured fields the published bulletin template needs beyond the raw scrape."""

    summary: str
    classification: str  # صنف الخبر
    news_type: str  # نوع الخبر
    importance: str  # اهمية الخبر


async def analyze(text: str, http_session: aiohttp.ClientSession) -> NewsAnalysis:
    """Return a summary plus classification/type/importance for `text`.

    Never raises: any failure in the AI path falls back to rule-based
    values so a failed AI call never blocks publication.
    """
    settings = get_settings()
    if settings.ai_summary_enabled and settings.ai_api_key:
        try:
            return await _analyze_via_api(text, http_session)
        except Exception as exc:  # noqa: BLE001 - must degrade gracefully, never propagate
            logger.warning("AI analysis failed, using rule-based fallback: {}", exc)
    return _fallback_analysis(text)


async def _analyze_via_api(text: str, http_session: aiohttp.ClientSession) -> NewsAnalysis:
    """Call the configured OpenAI-compatible chat-completions endpoint for structured JSON."""
    settings = get_settings()
    url = f"{settings.ai_api_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    system_prompt = (
        "لخص الخبر التالي بجملتين مختصرتين بالعربية الفصحى دون إبداء رأي، وصنّفه "
        "ضمن كليشة نشرة إخبارية. أعد الرد بصيغة JSON فقط، بدون أي نص أو شرح إضافي، "
        "بالمفاتيح التالية بالضبط:\n"
        '- "summary": الملخص.\n'
        f'- "classification": صنف الخبر، إحدى القيم التالية فقط: {", ".join(CLASSIFICATIONS)}.\n'
        f'- "news_type": نوع الخبر، إحدى القيم التالية فقط: {", ".join(NEWS_TYPES)}.\n'
        f'- "importance": أهمية الخبر، إحدى القيم التالية فقط: {", ".join(IMPORTANCE_LEVELS)}.'
    )
    payload = {
        "model": settings.ai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text[:_MAX_INPUT_CHARS]},
        ],
        "max_tokens": 300,
        "temperature": 0.2,
    }
    timeout = aiohttp.ClientTimeout(total=20)
    async with http_session.post(
        url, json=payload, headers=headers, timeout=timeout
    ) as response:
        response.raise_for_status()
        data = await response.json()
        content = str(data["choices"][0]["message"]["content"])

    parsed = json.loads(_JSON_FENCE_RE.sub("", content.strip()).strip())

    summary = str(parsed.get("summary") or "").strip() or _fallback_summary(text)
    classification = str(parsed.get("classification") or "").strip()
    news_type = str(parsed.get("news_type") or "").strip()
    importance = str(parsed.get("importance") or "").strip()

    if classification not in CLASSIFICATIONS:
        classification = _classify_fallback(text)
    if news_type not in NEWS_TYPES:
        news_type = _DEFAULT_NEWS_TYPE
    if importance not in IMPORTANCE_LEVELS:
        importance = _DEFAULT_IMPORTANCE

    return NewsAnalysis(
        summary=summary,
        classification=classification,
        news_type=news_type,
        importance=importance,
    )


def _fallback_analysis(text: str) -> NewsAnalysis:
    return NewsAnalysis(
        summary=_fallback_summary(text),
        classification=_classify_fallback(text),
        news_type=_DEFAULT_NEWS_TYPE,
        importance=_DEFAULT_IMPORTANCE,
    )


def _classify_fallback(text: str) -> str:
    category = categorize(normalize_arabic(text))
    return _CATEGORY_TO_CLASSIFICATION.get(category, "عام")


def _fallback_summary(text: str) -> str:
    """Naive extractive summary: first N sentences. Cheap, dependency-free."""
    normalized = text.replace("!", ".").replace("؟", ".").replace("\n", ".")
    sentences = [s.strip() for s in normalized.split(".") if s.strip()]
    if not sentences:
        return ""
    return "، ".join(sentences[:_FALLBACK_SENTENCE_COUNT]) + "."
