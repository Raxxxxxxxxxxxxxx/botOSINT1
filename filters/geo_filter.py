"""Geographic relevance filter: is this news item actually about Raqqa?

Phase-1 research finding this exists to address: several configured
sources (Al Jazeera, CNN Arabic, tag pages on general Syrian outlets)
publish mixed content, not Raqqa exclusively — so every item, even from
a source that looks "dedicated", is checked here before being accepted.

The keyword list below covers the governorate's city/town names that I
could confirm with reasonable confidence during research (Raqqa city,
Tabqa/Al-Thawrah, Tell Abyad, Ain Issa, Ma'adan). It is intentionally a
plain, editable list (not hardcoded logic) — extend `RAQQA_KEYWORDS`
as needed; no code changes required elsewhere.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from filters.arabic_normalize import normalize_arabic

RAQQA_KEYWORDS: list[str] = [
    "الرقة",
    "محافظة الرقة",
    "الطبقة",
    "الثورة",  # historical alternate name for Tabqa
    "تل أبيض",
    "عين عيسى",
    "معدان",
    "سد الفرات",
    "مطار الطبقة",
]

_NORMALIZED_KEYWORDS: list[str] = [normalize_arabic(kw) for kw in RAQQA_KEYWORDS]


def is_about_raqqa(normalized_text: str, threshold: int = 85) -> bool:
    """Return True if the (already-normalized) text is likely about Raqqa.

    Checks for an exact substring match first (cheap, catches the common
    case), then falls back to a fuzzy partial-ratio match per keyword to
    tolerate OCR/typo-like variation, matching the Phase-1 recommendation
    to prefer rapidfuzz over a full SimHash pipeline at this project's scale.
    """
    if not normalized_text:
        return False

    if any(keyword in normalized_text for keyword in _NORMALIZED_KEYWORDS):
        return True

    best_score = max(
        (fuzz.partial_ratio(keyword, normalized_text) for keyword in _NORMALIZED_KEYWORDS),
        default=0,
    )
    return best_score >= threshold
