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
    # Broader Syrian/NE-Syria outlets added on user request (free — no
    # per-source cost like the Facebook/Apify sources below). Existence and
    # reachability checked via HTTP request; several respected outlets
    # (SOHR, North Press, Zaman Al Wasl, Orient Net, Kurdistan24, SDF Press,
    # Al Arabiya, Al Modon, Rai Alyoum, Nedaa Post) return 403/406 to a bare
    # curl request — almost certainly Cloudflare/WAF bot-blocking rather
    # than the site being unreachable, so they're kept, disabled, same as
    # the rest: selector setup requires visiting them in an actual browser
    # anyway, and that may also reveal they need the HTML adapter's
    # User-Agent tuned or that they're unscrapable this way — that's a
    # per-source risk to confirm during selector setup, not before.
    ("North Press Agency (نورث برس)", "https://npasyria.com/", SourceType.HTML),
    ("North Press Agency English", "https://npasyria.com/en/", SourceType.HTML),
    ("Hawar News Agency (ANHA)", "https://hawarnews.com/ar", SourceType.HTML),
    ("Deir Ezzor 24", "https://deirezzor24.net/", SourceType.HTML),
    ("Deir Ezzor 24 English", "https://deirezzor24.net/en/", SourceType.HTML),
    ("Zaman Al Wasl", "https://www.zamanalwsl.net/", SourceType.HTML),
    ("Zaman Al Wasl English", "https://en.zamanalwsl.net/", SourceType.HTML),
    ("Orient Net", "https://orient-news.net/ar", SourceType.HTML),
    ("الحل نت", "https://7al.net/", SourceType.HTML),
    (
        "SOHR - المرصد السوري لحقوق الإنسان",
        "https://www.syriahr.com/",
        SourceType.HTML,
    ),
    ("Syria Direct", "https://syriadirect.org/ar/", SourceType.HTML),
    ("Syria News", "https://syria.news/", SourceType.HTML),
    (
        "عنب بلدي - أخبار الرقة",
        "https://www.enabbaladi.net/archives/tag/%D8%A7%D9%84%D8%B1%D9%82%D8%A9",
        SourceType.HTML,
    ),
    (
        "Enab Baladi English - Raqqa",
        "https://english.enabbaladi.net/archives/category/news/raqqa",
        SourceType.HTML,
    ),
    ("Rozana روزنة", "https://www.rozana.fm/", SourceType.HTML),
    ("Athr Press أثر برس", "https://athrpress.com/", SourceType.HTML),
    ("Rased راصد", "https://rasid.com/", SourceType.HTML),
    ("Sound and Picture صوت وصورة", "https://sound-and-picture.com/", SourceType.HTML),
    ("Al Arabiya - Syria", "https://www.alarabiya.net/syria", SourceType.HTML),
    ("Al Jazeera Arabic - Syria", "https://www.aljazeera.net/where/syria/", SourceType.HTML),
    ("Al Jazeera English - Syria", "https://www.aljazeera.com/where/syria/", SourceType.HTML),
    (
        "Anadolu Agency Arabic - Syria",
        "https://www.aa.com.tr/ar/%D8%B3%D9%88%D8%B1%D9%8A%D8%A7",
        SourceType.HTML,
    ),
    ("Rudaw Arabic", "https://www.rudaw.net/arabic", SourceType.HTML),
    ("Rudaw English", "https://www.rudaw.net/english", SourceType.HTML),
    ("Rai Alyoum رأي اليوم", "https://www.raialyoum.com/", SourceType.HTML),
    ("SDF Press", "https://sdf-press.com/", SourceType.HTML),
    ("Kurdistan24 Arabic", "https://www.kurdistan24.net/ar", SourceType.HTML),
    ("Al Modon المدن", "https://www.almodon.com/", SourceType.HTML),
    ("Baladi News بلدي نيوز", "https://baladi-news.com/", SourceType.HTML),
    ("Euphrates Post بوست الفرات", "https://euphratespost.com/", SourceType.HTML),
    ("Rojava Information Center", "https://rojavainformationcenter.com/", SourceType.HTML),
    ("Shaam Network شبكة شام", "https://www.shaam.org/", SourceType.HTML),
    ("Suwar Magazine سوّر", "https://suwar-magazine.org/", SourceType.HTML),
    ("Watan FM وطن اف ام", "https://www.watanfm.com/", SourceType.HTML),
    ("Al Iqtisadi الاقتصادي", "https://eqtsad.net/", SourceType.HTML),
    (
        "اليوم السابع - سوريا",
        "https://www.youm7.com/Section/%D8%B3%D9%88%D8%B1%D9%8A%D8%A7/319/1",
        SourceType.HTML,
    ),
    ("Sputnik Arabic - Syria", "https://sarabic.ae/syria", SourceType.HTML),
    ("Shafaq News شفق نيوز", "https://shafaq.com/ar", SourceType.HTML),
    ("الوطن سوريا", "https://alwatan.sy/", SourceType.HTML),
    ("نبض Nabd", "https://nabd.com/", SourceType.HTML),
    ("SANA English", "https://sana.sy/en/", SourceType.HTML),
    ("العربي الجديد", "https://www.alaraby.co.uk/syria", SourceType.HTML),
    ("The New Arab", "https://www.newarab.com/syria", SourceType.HTML),
    ("Nedaa Post نداء بوست", "https://nedaa-post.com/", SourceType.HTML),
]

# Facebook Pages/profiles supplied directly by the user (resolved from
# facebook.com/share/... redirect links) — independent journalists and news
# pages that post about Raqqa regularly. Unlike the HTML sources above,
# these need no per-source selector setup (Apify does the scraping), so
# they're inserted already enabled. Poll interval is 15 minutes: the
# user's explicit choice, made after being warned it maximizes Apify
# free-credit burn (the actor's `onlyPostsNewerThan` filter only has
# day-level granularity, so every poll within the same day re-scrapes,
# and is billed for, today's posts again — cost scales with poll
# frequency x source count regardless of dedup at the pipeline level).
_FACEBOOK_POLL_INTERVAL_SECONDS = 900

_FACEBOOK_SEED_SOURCES: list[tuple[str, str]] = [
    ("FB Profile 100078811247728", "https://www.facebook.com/profile.php?id=100078811247728"),
    ("mohamad.alothman.129", "https://www.facebook.com/mohamad.alothman.129"),
    ("Ahmad991Saleh", "https://www.facebook.com/Ahmad991Saleh"),
    ("raqqatoday4news", "https://www.facebook.com/raqqatoday4news"),
    ("Raqqa.Network.News", "https://www.facebook.com/Raqqa.Network.News"),
    ("Soheb903", "https://www.facebook.com/Soheb903"),
    ("Raqqa.Tabqa.2019", "https://www.facebook.com/Raqqa.Tabqa.2019"),
    ("raqqaourfamily", "https://www.facebook.com/raqqaourfamily"),
    ("Raqqa.Sl", "https://www.facebook.com/Raqqa.Sl"),
    ("منصة الرقة", "https://www.facebook.com/people/%D9%85%D9%86%D8%B5%D8%A9-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61589476030775"),
    ("أخبار الرقة نيوز", "https://www.facebook.com/people/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D9%86%D9%8A%D9%88%D8%B2/61579558192150"),
    ("kalid21", "https://www.facebook.com/kalid21"),
    ("ابو حسين الرقاوي", "https://www.facebook.com/people/%D8%A7%D8%A8%D9%88-%D8%AD%D8%B3%D9%8A%D9%86-%D8%A7%D9%84%D8%B1%D9%82%D8%A7%D9%88%D9%8A/61584998623074"),
    ("Lenardodecabrio", "https://www.facebook.com/Lenardodecabrio"),
    ("الرقة مدينة الرشيد24", "https://www.facebook.com/people/%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D9%85%D8%AF%D9%8A%D9%86%D8%A9-%D8%A7%D9%84%D8%B1%D8%B4%D9%8A%D8%AF24/61583628511125"),
    ("عين الفرات", "https://www.facebook.com/people/%D8%B9%D9%8A%D9%86-%D8%A7%D9%84%D9%81%D8%B1%D8%A7%D8%AA/61586249651210"),
    ("raqqaheke", "https://www.facebook.com/raqqaheke"),
    ("أرشيف صور مدينة الطبقة", "https://www.facebook.com/people/%D8%A3%D8%B1%D8%B4%D9%8A%D9%81-%D8%B5%D9%88%D8%B1-%D9%85%D8%AF%D9%8A%D9%86%D8%A9-%D8%A7%D9%84%D8%B7%D8%A8%D9%82%D8%A9/100082036123343"),
    ("raqqaphot0", "https://www.facebook.com/raqqaphot0"),
    ("albouhma", "https://www.facebook.com/albouhma"),
    ("raqqa.2019", "https://www.facebook.com/raqqa.2019"),
    ("1.Furati.Event", "https://www.facebook.com/1.Furati.Event"),
    ("المرصد الإخباري", "https://www.facebook.com/people/%D8%A7%D9%84%D9%85%D8%B1%D8%B5%D8%AF-%D8%A7%D9%84%D8%A5%D8%AE%D8%A8%D8%A7%D8%B1%D9%8A/61579898276722"),
    ("صدى معدان", "https://www.facebook.com/people/%D8%B5%D8%AF%D9%89-%D9%85%D8%B9%D8%AF%D8%A7%D9%86/61561252153879"),
    ("مكافحة الفساد في الرقة", "https://www.facebook.com/people/%D9%85%D9%83%D8%A7%D9%81%D8%AD%D8%A9-%D8%A7%D9%84%D9%81%D8%B3%D8%A7%D8%AF-%D9%81%D9%8A-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/100070980434555"),
    ("يوميات رقاوية", "https://www.facebook.com/people/%D9%8A%D9%88%D9%85%D9%8A%D8%A7%D8%AA-%D8%B1%D9%82%D8%A7%D9%88%D9%8A%D8%A9/100080370769691"),
    ("الرقة بقلوب اهلها", "https://www.facebook.com/people/%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D8%A8%D9%82%D9%84%D9%88%D8%A8-%D8%A7%D9%87%D9%84%D9%87%D8%A7/100067580763642"),
    ("على شو عم تدور بالرقة", "https://www.facebook.com/people/%D8%B9%D9%84%D9%89-%D8%B4%D9%88-%D8%B9%D9%85-%D8%AA%D8%AF%D9%88%D8%B1-%D8%A8%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61567677030348"),
    ("تريند الفرات", "https://www.facebook.com/people/%D8%AA%D8%B1%D9%8A%D9%86%D8%AF-%D8%A7%D9%84%D9%81%D8%B1%D8%A7%D8%AA/100075824599818"),
    ("euphratesheritage", "https://www.facebook.com/euphratesheritage"),
    ("YOUTH.OF.AJEEL", "https://www.facebook.com/YOUTH.OF.AJEEL"),
    ("البوحمد نيوز", "https://www.facebook.com/people/%D8%A7%D9%84%D8%A8%D9%88%D8%AD%D9%85%D8%AF-%D9%86%D9%8A%D9%88%D8%B2/100064753808637"),
    ("21raqqa", "https://www.facebook.com/21raqqa"),
    ("tabqa55", "https://www.facebook.com/tabqa55"),
    ("رقاويات", "https://www.facebook.com/people/%D8%B1%D9%82%D8%A7%D9%88%D9%8A%D8%A7%D8%AA/100070308968838"),
    ("صراحة_الرقة", "https://www.facebook.com/people/%D8%B5%D8%B1%D8%A7%D8%AD%D8%A9_%D8%A7%D9%84%D8%B1%D9%82%D8%A9/100071485346339"),
    ("alrqqa2019", "https://www.facebook.com/alrqqa2019"),
    ("مرسال الرقة", "https://www.facebook.com/people/%D9%85%D8%B1%D8%B3%D8%A7%D9%84-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61552770621362"),
    ("FB Profile 100066847051018", "https://www.facebook.com/profile.php?id=100066847051018"),
    ("freeraqqa1", "https://www.facebook.com/freeraqqa1"),
    ("الرقة دراما", "https://www.facebook.com/people/%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D8%AF%D8%B1%D8%A7%D9%85%D8%A7/100066737251009"),
    ("m.alraqqa", "https://www.facebook.com/m.alraqqa"),
    ("تراث الرقة", "https://www.facebook.com/people/%D8%AA%D8%B1%D8%A7%D8%AB-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/100063664871695"),
    ("الرقة واهلها", "https://www.facebook.com/people/%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D9%88%D8%A7%D9%87%D9%84%D9%87%D8%A7/100069238986552"),
    ("alraqqa.n", "https://www.facebook.com/alraqqa.n"),
    ("صراحة الرقة وريفها", "https://www.facebook.com/people/%D8%B5%D8%B1%D8%A7%D8%AD%D8%A9-%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D9%88%D8%B1%D9%8A%D9%81%D9%87%D8%A7/100077087110852"),
    ("m000m000m123", "https://www.facebook.com/m000m000m123"),
    ("ALTBQA.CITY", "https://www.facebook.com/ALTBQA.CITY"),
    ("معدان السبخة الرقة", "https://www.facebook.com/people/%D9%85%D8%B9%D8%AF%D8%A7%D9%86-%D8%A7%D9%84%D8%B3%D8%A8%D8%AE%D8%A9-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61559545700542"),
    ("الرقة لان", "https://www.facebook.com/people/%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D9%84%D8%A7%D9%86/100069878091878"),
    ("Snabel.Madaan", "https://www.facebook.com/Snabel.Madaan"),
    ("اخبار الرقة الحبيبة", "https://www.facebook.com/people/%D8%A7%D8%AE%D8%A8%D8%A7%D8%B1-%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D8%A7%D9%84%D8%AD%D8%A8%D9%8A%D8%A8%D8%A9/100082299022147"),
    ("1turathalfurat", "https://www.facebook.com/1turathalfurat"),
    ("معدان جديد", "https://www.facebook.com/people/%D9%85%D8%B9%D8%AF%D8%A7%D9%86-%D8%AC%D8%AF%D9%8A%D8%AF/100085686234848"),
    ("RaqqaHealthDir", "https://www.facebook.com/RaqqaHealthDir"),
    ("أخبار الحمرات", "https://www.facebook.com/people/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D8%A7%D9%84%D8%AD%D9%85%D8%B1%D8%A7%D8%AA/100089620732508"),
    ("الجزيرة خط الفرات", "https://www.facebook.com/people/%D8%A7%D9%84%D8%AC%D8%B2%D9%8A%D8%B1%D8%A9-%D8%AE%D8%B7-%D8%A7%D9%84%D9%81%D8%B1%D8%A7%D8%AA/100091281610775"),
    ("احنا شلون بدنا نعيش بالرقة", "https://www.facebook.com/people/%D8%A7%D8%AD%D9%86%D8%A7-%D8%B4%D9%84%D9%88%D9%86-%D8%A8%D8%AF%D9%86%D8%A7-%D9%86%D8%B9%D9%8A%D8%B4-%D8%A8%D8%A7%D9%84%D8%B1%D9%82%D8%A9-/61572018233817"),
    ("TA News تل أبيض", "https://www.facebook.com/people/TA-News-%D8%AA%D9%84-%D8%A3%D8%A8%D9%8A%D8%B6/61576274625062"),
    ("alraqqa.watn", "https://www.facebook.com/alraqqa.watn"),
    ("مركز الرقة الإعلامي Rmc", "https://www.facebook.com/people/%D9%85%D8%B1%D9%83%D8%B2-%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D8%A7%D9%84%D8%A5%D8%B9%D9%84%D8%A7%D9%85%D9%8A-Rmc/61570021479768"),
    ("raqqawall", "https://www.facebook.com/raqqawall"),
    ("هنيدة بلدنا", "https://www.facebook.com/people/%D9%87%D9%86%D9%8A%D8%AF%D8%A9-%D8%A8%D9%84%D8%AF%D9%86%D8%A7/100083108696085"),
    ("اخبار فرات هجين", "https://www.facebook.com/people/%D8%A7%D8%AE%D8%A8%D8%A7%D8%B1-%D9%81%D8%B1%D8%A7%D8%AA-%D9%87%D8%AC%D9%8A%D9%86/61571231345199"),
    ("furat.newspaper", "https://www.facebook.com/furat.newspaper"),
    ("AinIssa.City", "https://www.facebook.com/AinIssa.City"),
    ("Majlsss1979", "https://www.facebook.com/Majlsss1979"),
    ("الطبقة عاجل A M", "https://www.facebook.com/people/%D8%A7%D9%84%D8%B7%D8%A8%D9%82%D8%A9-%D8%B9%D8%A7%D8%AC%D9%84-A-M/61556944525027"),
    ("مرصد الرقة", "https://www.facebook.com/people/%D9%85%D8%B1%D8%B5%D8%AF-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61581238744244"),
    ("الرقة بلدنا", "https://www.facebook.com/people/%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D8%A8%D9%84%D8%AF%D9%86%D8%A7/100082712566746"),
    ("صوت الفرات M", "https://www.facebook.com/people/%D8%B5%D9%88%D8%AA-%D8%A7%D9%84%D9%81%D8%B1%D8%A7%D8%AA-M/61578749666896"),
    ("ARRAQQAH.GATE", "https://www.facebook.com/ARRAQQAH.GATE"),
    ("الرقة بقلوب أهلها", "https://www.facebook.com/people/%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D8%A8%D9%82%D9%84%D9%88%D8%A8-%D8%A3%D9%87%D9%84%D9%87%D8%A7/61554918910482"),
    ("مديرية أوقاف الرقة", "https://www.facebook.com/people/%D9%85%D8%AF%D9%8A%D8%B1%D9%8A%D8%A9-%D8%A3%D9%88%D9%82%D8%A7%D9%81-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61584368254949"),
    ("raqqa.mc", "https://www.facebook.com/raqqa.mc"),
    ("اتحاد عمال محافظة الرقة", "https://www.facebook.com/people/%D8%A7%D8%AA%D8%AD%D8%A7%D8%AF-%D8%B9%D9%85%D8%A7%D9%84-%D9%85%D8%AD%D8%A7%D9%81%D8%B8%D8%A9-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61586965781075"),
    ("RaqqaWaterDir", "https://www.facebook.com/RaqqaWaterDir"),
    ("RaqqaMD", "https://www.facebook.com/RaqqaMD"),
    ("RBA.araqqa", "https://www.facebook.com/RBA.araqqa"),
    ("نقابة المحامين فرع الرقة", "https://www.facebook.com/people/%D9%86%D9%82%D8%A7%D8%A8%D8%A9-%D8%A7%D9%84%D9%85%D8%AD%D8%A7%D9%85%D9%8A%D9%86-%D9%81%D8%B1%D8%B9-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61571684250362"),
    ("عين على المنصورة الرقة", "https://www.facebook.com/people/%D8%B9%D9%8A%D9%86-%D8%B9%D9%84%D9%89-%D8%A7%D9%84%D9%85%D9%86%D8%B5%D9%88%D8%B1%D8%A9-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61570542247072"),
    ("نهضة الرقة", "https://www.facebook.com/people/%D9%86%D9%87%D8%B6%D8%A9-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/100069948596673"),
    ("ترند الرقة", "https://www.facebook.com/people/%D8%AA%D8%B1%D9%86%D8%AF-%D8%A7%D9%84%D8%B1%D9%82%D8%A9/61578631111420"),
    ("ALRaqqaTV", "https://www.facebook.com/ALRaqqaTV"),
    ("سلوك أهلنا", "https://www.facebook.com/people/%D8%B3%D9%84%D9%88%D9%83-%D8%A3%D9%87%D9%84%D9%86%D8%A7/100067114474072"),
    ("filterRaqqa", "https://www.facebook.com/filterRaqqa"),
    ("AinissaPlus", "https://www.facebook.com/AinissaPlus"),
    ("MaadanNewsOfficial", "https://www.facebook.com/MaadanNewsOfficial"),
    ("raqqa.sy", "https://www.facebook.com/raqqa.sy"),
    ("شبكة أخبار الرقة الأن", "https://www.facebook.com/people/%D8%B4%D8%A8%D9%83%D8%A9-%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D8%A7%D9%84%D8%B1%D9%82%D8%A9-%D8%A7%D9%84%D8%A3%D9%86/100093256452202"),
    ("rakkanews21", "https://www.facebook.com/rakkanews21"),
    ("talabyad.mc", "https://www.facebook.com/talabyad.mc"),
    ("suluk.city", "https://www.facebook.com/suluk.city"),
    ("TaqbaRegionalOffice", "https://www.facebook.com/TaqbaRegionalOffice"),
    ("m.t.alrakka", "https://www.facebook.com/m.t.alrakka"),
    ("TalAbyadCity", "https://www.facebook.com/TalAbyadCity"),
    ("RaqqaElectricDir", "https://www.facebook.com/RaqqaElectricDir"),
    ("mansoura.mc", "https://www.facebook.com/mansoura.mc"),
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

        fb_inserted = 0
        for name, url in _FACEBOOK_SEED_SOURCES:
            exists = await session.execute(select(Source.id).where(Source.url == url))
            if exists.scalar_one_or_none() is not None:
                continue
            session.add(
                Source(
                    name=name,
                    type=SourceType.FACEBOOK,
                    url=url,
                    enabled=True,
                    poll_interval_seconds=_FACEBOOK_POLL_INTERVAL_SECONDS,
                )
            )
            fb_inserted += 1

        await session.commit()
        logger.info(
            "Seeded {} new HTML/RSS source(s) (disabled pending selector setup) "
            "and {} new Facebook source(s) (enabled)",
            inserted,
            fb_inserted,
        )


# CSS selectors verified by fetching each site's live HTML and inspecting its
# actual article-listing markup (see html_adapter.py for how list_selector is
# used). Enabling a source is just filling in its entry here — no scraper
# code changes needed. Sites confirmed to sit behind a JS/Cloudflare bot
# challenge (no selector can fix that — the HTML adapter does a plain HTTP
# GET, no headless browser, per the Phase-2 resource-budget decision) are
# deliberately left out and stay disabled: North Press Agency (npasyria.com),
# هذا اليوم (hathalyoum.net), تلفزيون سوريا (syria.tv), راصد (rasid.com — this
# one is actually a parked-domain redirect, not a real news site anymore).
_CONFIGURED_SELECTORS: dict[str, dict[str, object]] = {
    "https://7al.net/": {"list_selector": "a.card", "enabled": True},
    "https://deirezzor24.net/": {"list_selector": ".jeg_post_title", "enabled": True},
    "https://sana.sy/governorates/alrakkah/": {"list_selector": ".entry-title", "enabled": True},
    "https://english.enabbaladi.net/": {"list_selector": ".one-post", "enabled": True},
    "https://syria.news/": {"list_selector": ".search-title", "enabled": True},
    "https://alikhbariah.com/news_location/%D8%A7%D9%84%D8%B1%D9%82%D8%A9/": {
        "list_selector": "article",
        "enabled": True,
    },
}


async def apply_configured_selectors() -> None:
    """Apply verified `list_selector`/`enabled` settings to existing sources.

    Safe to call on every startup: only touches rows whose current value
    differs from the configured one, so re-running is a no-op once applied.
    """
    async with get_session() as session:
        updated = 0
        for url, config in _CONFIGURED_SELECTORS.items():
            result = await session.execute(select(Source).where(Source.url == url))
            source = result.scalar_one_or_none()
            if source is None:
                continue
            changed = False
            for field, value in config.items():
                if getattr(source, field) != value:
                    setattr(source, field, value)
                    changed = True
            if changed:
                updated += 1
        await session.commit()
        if updated:
            logger.info("Applied verified selectors to {} source(s)", updated)


async def _seed_and_configure() -> None:
    await seed_sources()
    await apply_configured_selectors()


if __name__ == "__main__":
    asyncio.run(_seed_and_configure())
