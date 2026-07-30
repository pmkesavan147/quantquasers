"""A committed snapshot of the market, for deployments that cannot fetch one.

A serverless instance starts with an empty disk and a request budget measured in
seconds. Fetching a year of prices for 40 symbols and eight headlines each would
take minutes and time out — every single cold start. So the deployed build reads
a snapshot committed to the repo: real prices, real headlines, captured by
`python -m scripts.build_snapshot` on a machine that *can* take its time.

This is not a mock. Every number in the snapshot was fetched from yfinance and
every headline came from Google News; the provenance in each API response says
`snapshot` rather than `live`, so nobody mistakes one for the other.

Snapshot mode turns itself on when there is no network to rely on:

    SNAPSHOT=1     force it
    SNAPSHOT=0     force it off
    (unset)        on when running on Vercel, off on a laptop
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = Path(os.getenv("SNAPSHOT_DIR", ROOT / "data" / "snapshot"))
QUANT_FILE = SNAPSHOT_DIR / "quant.json"
NEWS_FILE = SNAPSHOT_DIR / "news.json"


def enabled() -> bool:
    flag = os.getenv("SNAPSHOT", "").lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    # Vercel sets VERCEL=1 in every runtime environment.
    return bool(os.getenv("VERCEL"))


@lru_cache(maxsize=1)
def _load(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def quant_metrics() -> dict:
    """`{symbol: QuantMetrics-shaped dict}` from the snapshot."""
    return _load(str(QUANT_FILE)).get("symbols", {})


def news_for(symbol: str, now: datetime | None = None) -> list[dict]:
    """Snapshot headlines for one symbol, with ages rebased to now.

    Published timestamps are stored as an age in hours rather than an absolute
    date. A committed absolute timestamp goes stale within a day, and the
    recency weighting in `selection/sentiment.py` would quietly zero out every
    headline in the snapshot.
    """
    now = now or datetime.now()
    rows = _load(str(NEWS_FILE)).get("symbols", {}).get(symbol.upper(), [])
    out = []
    for row in rows:
        out.append(
            {
                **row,
                "published_at": (
                    now - timedelta(hours=float(row.get("age_hours", 6)))
                ).isoformat(),
                "origin": "snapshot",
            }
        )
    return out


def captured_at() -> str | None:
    """When the snapshot was taken — reported in /api/health so a stale one is
    visible rather than presented as today's market."""
    return _load(str(QUANT_FILE)).get("captured_at")


def summary() -> dict:
    quant = _load(str(QUANT_FILE))
    news = _load(str(NEWS_FILE))
    return {
        "enabled": enabled(),
        "captured_at": quant.get("captured_at"),
        "symbols": len(quant.get("symbols", {})),
        "headlines": sum(len(v) for v in news.get("symbols", {}).values()),
    }
