"""Rule-based categorization (Phase-2 decision: AI categorization is deferred;
keyword rules are the v1 baseline, mirroring the "AI + rule-based fallback"
pattern validated in the tony-stark-eth/news-aggregator project during research).
"""

from __future__ import annotations

from filters.arabic_normalize import normalize_arabic

# Ordered: first matching category wins, so put more specific categories first.
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "أمني وعسكري",
        ["اشتباك", "قصف", "عملية عسكرية", "انفجار", "مسلحين", "قسد", "الجيش", "عبوة ناسفة"],
    ),
    (
        "إنساني",
        ["نازحين", "مساعدات", "إغاثة", "مخيم", "لاجئين", "منظمة إنسانية"],
    ),
    (
        "خدمات وبنية تحتية",
        ["كهرباء", "مياه", "سد الفرات", "طرق", "بلدية", "خدمات"],
    ),
    (
        "اقتصادي",
        ["أسعار", "سوق", "زراعة", "قمح", "اقتصاد", "عملة"],
    ),
    (
        "سياسي",
        ["اجتماع", "وفد", "مفاوضات", "تصريح", "اتفاق"],
    ),
]

_DEFAULT_CATEGORY = "عام"


def categorize(normalized_text: str) -> str:
    """Assign a coarse category based on keyword matches.

    Returns :data:`_DEFAULT_CATEGORY` ("عام"/general) when nothing matches,
    rather than leaving the field empty, so downstream consumers always
    have a value to filter/group on.
    """
    for category, keywords in _CATEGORY_KEYWORDS:
        normalized_keywords = (normalize_arabic(kw) for kw in keywords)
        if any(kw in normalized_text for kw in normalized_keywords):
            return category
    return _DEFAULT_CATEGORY
