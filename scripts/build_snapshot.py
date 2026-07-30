"""Capture the market into `data/snapshot/`, for the deployed build to serve.

    python -m scripts.build_snapshot            # prices + headlines
    python -m scripts.build_snapshot --gemma    # also copy cached model answers

Run it on a machine with a network and some patience. The deployed instance then
answers every request from these files instead of waiting on yfinance and RSS,
which it has neither the time nor the disk to do.

What lands in the snapshot is real: metrics computed by `selection/quant.py`
from a year of yfinance prices, and headlines fetched from Google News. It is a
photograph, not a mock — and every API response says `snapshot` rather than
`live` so nobody confuses the two.

Re-run it before the demo. `/api/health` reports `captured_at`, so a stale
snapshot is visible rather than presented as today's market.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gemma import client as gemma_client
from ingest.news import headlines_for
from ingest.prices import INDEX_SYMBOL, history
from selection import quant
from selection.universe import company_name, universe

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "snapshot"


def build(with_gemma: bool = False, limit: int | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = sorted(universe())[: limit or len(universe())]
    now = datetime.now()

    print(f"index {INDEX_SYMBOL}: {len(history(INDEX_SYMBOL))} sessions", flush=True)

    metrics: dict[str, dict] = {}
    news: dict[str, list[dict]] = {}

    for i, symbol in enumerate(symbols, 1):
        m = quant.fetch(symbol)
        if m is not None:
            metrics[symbol] = m.model_dump(mode="json")

        rows = []
        for h in headlines_for(symbol, company_name(symbol), now=now):
            # Age, not an absolute timestamp: a committed date goes stale within
            # a day and the recency weighting would zero the whole snapshot out.
            age_hours = max(
                0.0,
                (now - h.published_at.replace(tzinfo=None)).total_seconds() / 3600,
            )
            rows.append(
                {
                    "id": h.id,
                    "symbol": h.symbol,
                    "title": h.title,
                    "source": h.source,
                    "url": h.url,
                    "age_hours": round(age_hours, 1),
                }
            )
        if rows:
            news[symbol] = rows

        print(
            f"[{i:>3}/{len(symbols)}] {symbol:12} "
            f"quant={'ok' if symbol in metrics else 'MISSING':7} "
            f"headlines={len(rows)}",
            flush=True,
        )

    stamp = now.isoformat(timespec="seconds")
    (OUT / "quant.json").write_text(
        json.dumps({"captured_at": stamp, "symbols": metrics}, indent=1),
        encoding="utf-8",
    )
    (OUT / "news.json").write_text(
        json.dumps({"captured_at": stamp, "symbols": news}, indent=1),
        encoding="utf-8",
    )

    print(
        f"\nwrote {OUT}\n  quant.json  {len(metrics)}/{len(symbols)} symbols"
        f"\n  news.json   {sum(len(v) for v in news.values())} headlines"
    )

    if with_gemma:
        src = gemma_client.CACHE_DIR
        dst = OUT / "gemma"
        if not src.exists():
            print(f"\nno model cache at {src} — run scripts.warm_cache --with-gemma")
            return
        dst.mkdir(parents=True, exist_ok=True)
        copied = 0
        for path in src.glob("*.json"):
            shutil.copy2(path, dst / path.name)
            copied += 1
        print(f"  gemma/      {copied} cached model responses")
        print(
            "\nSet GEMMA_CACHE_DIR=data/snapshot/gemma on the deployment so it "
            "replays these instead of calling the API on every request."
        )


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = next(
        (int(a.split("=", 1)[1]) for a in args if a.startswith("--limit=")), None
    )
    build(with_gemma="--gemma" in args, limit=limit)
