"""Headlines per symbol: Google News RSS, a disk cache, and committed fixtures.

Resolution order is deliberate:

1. **Cache** for this symbol, if fresh — RSS is slow and rate-limited.
2. **RSS**, when the network is up.
3. **Stale cache**, at any age, because a day-old headline is still a real one.
4. **`data/headlines.json`** — committed fixtures, so the pipeline produces the
   same demo with the Wi-Fi unplugged.

Nothing here scores anything. Sentiment is `gemma/scorers.py`; aggregation is
`selection/sentiment.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE_DIR = Path(os.getenv("NEWS_CACHE_DIR", DATA / "cache" / "news"))
FIXTURE_PATH = DATA / "headlines.json"

RSS_URL = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)
CACHE_TTL = timedelta(minutes=int(os.getenv("NEWS_CACHE_TTL_MIN", "90")))
MAX_PER_SYMBOL = int(os.getenv("NEWS_MAX_PER_SYMBOL", "8"))
TIMEOUT = float(os.getenv("NEWS_TIMEOUT_S", "6"))


class Headline(BaseModel):
    id: str
    symbol: str
    title: str
    source: str
    url: str
    published_at: datetime
    origin: str = "rss"        # rss | cache | fixture


def _hid(symbol: str, title: str) -> str:
    return hashlib.sha1(f"{symbol}|{title}".encode()).hexdigest()[:12]


def _cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol.upper()}.json"


def _write_cache(symbol: str, items: list[Headline]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(symbol).write_text(
            json.dumps([h.model_dump(mode="json") for h in items], indent=1),
            encoding="utf-8",
        )
    except OSError:
        pass


def _read_cache(symbol: str) -> list[Headline]:
    path = _cache_path(symbol)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Headline.model_validate({**h, "origin": "cache"}) for h in raw]
    except Exception:
        return []


def _cache_fresh(symbol: str) -> bool:
    path = _cache_path(symbol)
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age < CACHE_TTL


def _fetch_rss(symbol: str, company: str) -> list[Headline]:
    query = urllib.parse.quote_plus(f"{company} stock NSE")
    url = RSS_URL.format(query=query)

    # feedparser is the documented path but is not required to run — urllib
    # plus its own parser keeps this working on a machine without the package.
    try:
        import feedparser

        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            feed = feedparser.parse(resp.read())
        entries = feed.entries[:MAX_PER_SYMBOL]
    except Exception:
        return []

    out: list[Headline] = []
    for e in entries:
        title = (getattr(e, "title", "") or "").strip()
        if not title:
            continue
        published = getattr(e, "published_parsed", None)
        when = (
            datetime(*published[:6], tzinfo=timezone.utc).astimezone()
            if published
            else datetime.now()
        )
        source = ""
        if getattr(e, "source", None) is not None:
            source = getattr(e.source, "title", "") or ""
        out.append(
            Headline(
                id=_hid(symbol, title),
                symbol=symbol.upper(),
                title=title,
                source=source or "Google News",
                url=getattr(e, "link", "") or "",
                published_at=when,
                origin="rss",
            )
        )
    return out


_FIXTURES: dict | None = None


def _fixtures() -> dict:
    global _FIXTURES
    if _FIXTURES is None:
        try:
            _FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _FIXTURES = {}
    return _FIXTURES


def _fixture_headlines(symbol: str, now: datetime | None = None) -> list[Headline]:
    """Fixture headlines, rebased so their ages are realistic at demo time.

    `age_hours` in the file is relative, not absolute — a committed timestamp
    would be days stale by the time anyone runs this, and the recency weighting
    would quietly zero everything out.
    """
    now = now or datetime.now()
    rows = _fixtures().get(symbol.upper(), [])
    out = []
    for row in rows:
        title = row["title"]
        out.append(
            Headline(
                id=_hid(symbol, title),
                symbol=symbol.upper(),
                title=title,
                source=row.get("source", "fixture"),
                url=row.get("url", ""),
                published_at=now - timedelta(hours=float(row.get("age_hours", 6))),
                origin="fixture",
            )
        )
    return out


def headlines_for(
    symbol: str,
    company: str | None = None,
    *,
    allow_network: bool = True,
    now: datetime | None = None,
) -> list[Headline]:
    """Newest first, at most `MAX_PER_SYMBOL`."""
    symbol = symbol.upper()

    if _cache_fresh(symbol):
        cached = _read_cache(symbol)
        if cached:
            return cached[:MAX_PER_SYMBOL]

    if allow_network and os.getenv("OFFLINE") != "1":
        fetched = _fetch_rss(symbol, company or symbol)
        if fetched:
            _write_cache(symbol, fetched)
            return fetched[:MAX_PER_SYMBOL]

    stale = _read_cache(symbol)
    if stale:
        return stale[:MAX_PER_SYMBOL]

    return _fixture_headlines(symbol, now)[:MAX_PER_SYMBOL]


def source_mix(items: list[Headline]) -> dict[str, int]:
    """How many headlines came from where — surfaced in `/api/health` so nobody
    demos fixture data believing it is live."""
    mix: dict[str, int] = {}
    for h in items:
        mix[h.origin] = mix.get(h.origin, 0) + 1
    return mix
