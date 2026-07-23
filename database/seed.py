"""Seeds the database with the Raqqa news sources identified during Phase-1 research.

Every seeded source is inserted **disabled** (`enabled=False`) with no
`list_selector` set. Phase-1 research confirmed these sites exist and
publish Raqqa-related content, but did **not** verify a working RSS feed
or determine each site's HTML structure — that requires visiting each
page directly, which is a technical-discovery step, not a research one.

Before enabling a source: open its URL, find the CSS selector that
matches each article link on the listing page, set `list_selector`
accordingly (and `content_selector`/`image_selector` if
`fetch_full_article` is wanted), then set `enabled=True`.

Run with: ``python -m database.seed``
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import select

from database.engine import get_session, init_db
from models.enums import SourceType
from models.source import Source

# (name, url, type) — URLs as found during Phase-1 research; selectors
# intentionally left unset (see module docstring).
_SEED_SOURCES: list[tuple[str, str, SourceType]] = [
    ("SANA - محافظة الرقة", "https://sana.sy/governorates/alrakkah/", SourceType.HTML),
    ("عنب بلدي (Enab Baladi)", "https://english.enabbaladi.net/", SourceType.HTML),
    ("الرقة تذبح بصمت", "https://www.raqqa-sl.com/", SourceType.HTML),
    (
        "تلفزيون سوريا - أخبار الرقة",
        "https://www.syria.tv/tag/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D8%A7%D9%84%D8%B1%D9%82%D8%A9",
        SourceType.HTML,
    ),
    (
        "الإخبارية السورية - الرقة",
        "https://alikhbariah.com/news_location/%D8%A7%D9%84%D8%B1%D9%82%D8%A9/",
        SourceType.HTML,
    ),
    (
        "هذا اليوم - أخبار الرقة",
        "https://hathalyoum.net/news/%D8%A7%D9%84%D8%B1%D9%82%D8%A9",
        SourceType.HTML,
    ),
]


async def seed_sources() -> None:
    """Insert the seed sources if they aren't already present (by URL)."""
    await init_db()
    async with get_session() as session:
        inserted = 0
        for name, url, source_type in _SEED_SOURCES:
            exists = await session.execute(select(Source.id).where(Source.url == url))
            if exists.scalar_one_or_none() is not None:
                continue
            session.add(
                Source(
                    name=name,
                    type=source_type,
                    url=url,
                    enabled=False,
                    poll_interval_seconds=900,
                )
            )
            inserted += 1
        await session.commit()
        logger.info(
            "Seeded {} new source(s); all inserted disabled pending selector setup", inserted
        )


if __name__ == "__main__":
    asyncio.run(seed_sources())
