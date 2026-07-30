"""Pre-fetch everything the demo needs, so the demo itself touches no network.

    python -m scripts.warm_cache                 # prices + headlines
    python -m scripts.warm_cache --with-gemma    # also pre-score every headline

Run it once on venue Wi-Fi (or at home), then run the app with `OFFLINE=1` and
nothing reaches out. Prices land in `data/cache/prices/*.parquet`, headlines in
`data/cache/news/*.json`, model responses in `data/cache/gemma/*.json`.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gemma import client as gemma_client
from ingest.news import headlines_for
from ingest.prices import INDEX_SYMBOL, history
from selection.pipeline import score_symbol
from selection.universe import company_name, universe

ROOT = Path(__file__).resolve().parent.parent


def main(with_gemma: bool = False, limit: int | None = None) -> None:
    symbols = sorted(universe())
    if limit:
        symbols = symbols[:limit]

    print(f"index: {INDEX_SYMBOL}", flush=True)
    index = history(INDEX_SYMBOL)
    print(f"  {len(index)} sessions", flush=True)

    ok_prices = ok_news = 0
    for i, symbol in enumerate(symbols, 1):
        df = history(symbol)
        news = headlines_for(symbol, company_name(symbol))
        origins = {h.origin for h in news}
        if not df.empty:
            ok_prices += 1
        if any(o != "fixture" for o in origins):
            ok_news += 1
        print(
            f"[{i:>3}/{len(symbols)}] {symbol:12} prices={len(df):>4} "
            f"news={len(news):>2} ({','.join(sorted(origins)) or 'none'})",
            flush=True,
        )

    print(f"\nprices cached for {ok_prices}/{len(symbols)}, "
          f"live news for {ok_news}/{len(symbols)}")

    if with_gemma:
        status = gemma_client.status()
        print(f"\nscoring headlines via {status['backend']} ({status['model']})")
        if status["backend"] == "stub":
            print("  no model reachable — nothing to cache, scoring stays "
                  "deterministic keyword fallback")
            return
        now = datetime.now()
        for i, symbol in enumerate(symbols, 1):
            sentiment, items = score_symbol(symbol, now=now)
            print(
                f"[{i:>3}/{len(symbols)}] {symbol:12} "
                f"score={sentiment.score:+.2f} conf={sentiment.confidence:.2f} "
                f"n={sentiment.n_articles}",
                flush=True,
            )
        print(f"\ncached responses: {gemma_client.status()['cached_responses']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = None
    for a in args:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    main(with_gemma="--with-gemma" in args, limit=limit)
