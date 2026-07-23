"""URL/content hashing and normalization helpers used for duplicate detection."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit

# Tracking parameters that don't change the identity of an article — stripping
# them means the same article shared with different UTM tags still hashes
# to the same value.
_TRACKING_PARAM_PREFIXES = ("utm_", "fbclid", "gclid", "ref", "spm")


def normalize_url(url: str) -> str:
    """Normalize a URL for stable duplicate comparison.

    Lowercases the scheme/host, strips the fragment, and drops common
    tracking query parameters, without altering the path.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()

    kept_query = [
        pair
        for pair in parts.query.split("&")
        if pair and not pair.split("=", 1)[0].lower().startswith(_TRACKING_PARAM_PREFIXES)
    ]
    query = "&".join(kept_query)

    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def hash_url(url: str) -> str:
    """Return the SHA-256 hex digest of a normalized URL for fast dedup lookups."""
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def hash_content(content: str) -> str:
    """Return the SHA-256 hex digest of a page body, used for HTML-cache checks."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
