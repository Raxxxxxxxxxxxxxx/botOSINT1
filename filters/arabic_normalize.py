"""Arabic text normalization.

Uses `pyarabic` (lightweight, pure-Python) rather than `camel-tools`
(Phase-1 decision: camel-tools' ML models are too heavy for Railway's
512MB RAM ceiling). Normalization runs once, right after a raw item is
fetched, so every later stage (dedup, geo-filter, categorization)
compares text on equal footing regardless of the source's original
spelling conventions.
"""

from __future__ import annotations

import re

import pyarabic.araby as araby

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text for comparison purposes (not for display).

    Applies, in order: diacritics removal, alef/alef-maksura/teh-marbuta
    unification, tatweel removal, and whitespace collapsing. The result
    is meant for hashing/fuzzy-matching, not for showing to end users.
    """
    if not text:
        return ""

    normalized = araby.strip_tashkeel(text)
    normalized = araby.strip_tatweel(normalized)
    normalized = araby.normalize_alef(normalized)
    normalized = araby.normalize_hamza(normalized)
    normalized = araby.normalize_ligature(normalized)
    normalized = normalized.replace("ة", "ه")  # teh marbuta -> heh
    normalized = normalized.replace("ى", "ي")  # alef maksura -> yeh
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized.lower()
