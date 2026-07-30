"""OHLCV for NSE symbols, cached to parquet.

`history()` is the only function that touches the network. Everything
downstream reads its DataFrame, so `selection/quant.py` stays a pure function
of price data and can be tested without yfinance installed.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.getenv("PRICE_CACHE_DIR", ROOT / "data" / "cache" / "prices"))

INDEX_SYMBOL = "^NSEI"          # Nifty 50, the beta benchmark
DEFAULT_PERIOD = "1y"

# yfinance rate-limits aggressively and the demo re-runs the pipeline often.
# Anything fetched within this window is served from parquet.
CACHE_TTL = timedelta(hours=int(os.getenv("PRICE_CACHE_TTL_HOURS", "12")))


# NSE symbols that no longer resolve on Yahoo under their old name. Without
# this, the demerged names silently return an empty DataFrame and every metric
# for them degrades to the fixture value.
#   TATAMOTORS: demerged; the passenger-vehicle entity trades as TMPV.
ALIASES = {"TATAMOTORS": "TMPV"}


def yahoo_symbol(symbol: str) -> str:
    """`RELIANCE` -> `RELIANCE.NS`. Indices (`^NSEI`) pass through."""
    s = symbol.strip().upper()
    if s.startswith("^") or "." in s:
        return s
    return f"{ALIASES.get(s, s)}.NS"


def _cache_path(symbol: str, period: str) -> Path:
    safe = yahoo_symbol(symbol).replace("^", "IDX_").replace(".", "_")
    return CACHE_DIR / f"{safe}_{period}.parquet"


def _read_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def _fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age < CACHE_TTL


def history(
    symbol: str, period: str = DEFAULT_PERIOD, *, allow_network: bool = True
) -> pd.DataFrame:
    """Daily OHLCV, newest last. Empty DataFrame if there is neither network
    nor cache — callers must handle that rather than assume prices exist.
    """
    path = _cache_path(symbol, period)

    if _fresh(path):
        cached = _read_cache(path)
        if cached is not None and not cached.empty:
            return cached

    if allow_network and os.getenv("OFFLINE") != "1":
        try:
            import yfinance as yf

            df = yf.Ticker(yahoo_symbol(symbol)).history(
                period=period, auto_adjust=True
            )
            if not df.empty:
                df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    df.to_parquet(path)
                except Exception:
                    pass  # a cache write failure must not fail the fetch
                return df
        except Exception:
            pass  # fall through to a stale cache

    stale = _read_cache(path)
    return stale if stale is not None else pd.DataFrame()


def market_cap_cr(symbol: str) -> float | None:
    """Market cap in ₹ crore, or None. Only used when building the universe
    snapshot — the pipeline reads the committed CSV, not this."""
    if os.getenv("OFFLINE") == "1":
        return None
    try:
        import yfinance as yf

        raw = yf.Ticker(yahoo_symbol(symbol)).info.get("marketCap")
        return round(float(raw) / 1e7, 1) if raw else None
    except Exception:
        return None


def cached_symbols() -> list[str]:
    if not CACHE_DIR.exists():
        return []
    return sorted({p.stem.rsplit("_", 1)[0] for p in CACHE_DIR.glob("*.parquet")})
