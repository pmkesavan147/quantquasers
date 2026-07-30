"""Regenerate `data/universe.csv` — the hand-curated trading universe.

Market caps come from yfinance at build time and are committed as a snapshot,
so the pipeline never needs the network to know a symbol's cap bucket.

    python -m scripts.build_universe            # refresh caps, keep flags
    python -m scripts.build_universe --offline   # write the seed as-is

Cap buckets: SEBI classifies by market-cap *rank* across all listed companies
(1–100 large, 101–250 mid, 251+ small), which needs the full exchange list.
This file approximates that with thresholds on absolute market cap, and
`micro` (< ₹500 crore) is our own extension, not an official SEBI bucket. Both
facts are stated in the README rather than implied away.

`asm_gsm_flag` is a hand-maintained snapshot of NSE's surveillance lists. It is
not a live feed; refresh it by hand before a demo if it matters.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from ingest.prices import market_cap_cr

# Windows consoles default to cp1252, which cannot encode "₹". Every rupee
# figure this project prints would raise UnicodeEncodeError without this.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "universe.csv"

LARGE_MIN_CR = 100_000.0
MID_MIN_CR = 35_000.0
MICRO_MAX_CR = 500.0

# symbol, company name, seed market cap (₹ crore), surveillance flag
SEED: list[tuple[str, str, float, bool]] = [
    ("RELIANCE", "Reliance Industries", 1_750_000, False),
    ("TCS", "Tata Consultancy Services", 1_240_000, False),
    ("HDFCBANK", "HDFC Bank", 1_420_000, False),
    ("ICICIBANK", "ICICI Bank", 890_000, False),
    ("INFY", "Infosys", 640_000, False),
    ("BHARTIARTL", "Bharti Airtel", 980_000, False),
    ("SBIN", "State Bank of India", 720_000, False),
    ("ITC", "ITC", 545_000, False),
    ("LT", "Larsen & Toubro", 512_000, False),
    ("HINDUNILVR", "Hindustan Unilever", 580_000, False),
    ("SUNPHARMA", "Sun Pharmaceutical", 428_000, False),
    ("MARUTI", "Maruti Suzuki India", 395_000, False),
    ("TATAMOTORS", "Tata Motors", 384_000, False),
    ("AXISBANK", "Axis Bank", 355_000, False),
    ("KOTAKBANK", "Kotak Mahindra Bank", 390_000, False),
    ("BAJFINANCE", "Bajaj Finance", 470_000, False),
    ("ASIANPAINT", "Asian Paints", 275_000, False),
    ("TITAN", "Titan Company", 298_000, False),
    ("NESTLEIND", "Nestle India", 235_000, False),
    ("ADANIPORTS", "Adani Ports & SEZ", 302_000, False),
    ("NTPC", "NTPC", 340_000, False),
    ("POWERGRID", "Power Grid Corporation", 290_000, False),
    ("ONGC", "Oil & Natural Gas Corporation", 310_000, False),
    ("COALINDIA", "Coal India", 246_000, False),
    ("TATASTEEL", "Tata Steel", 195_000, False),
    ("JSWSTEEL", "JSW Steel", 250_000, False),
    ("GRASIM", "Grasim Industries", 175_000, False),
    ("CIPLA", "Cipla", 125_000, False),
    ("TECHM", "Tech Mahindra", 155_000, False),
    ("WIPRO", "Wipro", 268_000, False),
    # Mid and small caps — these are what make the refusal engine visible.
    ("PERSISTENT", "Persistent Systems", 78_000, False),
    ("MPHASIS", "Mphasis", 52_000, False),
    ("FEDERALBNK", "Federal Bank", 48_000, False),
    ("ASHOKLEY", "Ashok Leyland", 62_000, False),
    ("SUZLON", "Suzlon Energy", 72_000, False),
    ("HFCL", "HFCL", 12_000, True),
    ("IDEA", "Vodafone Idea", 45_000, False),
    ("RPOWER", "Reliance Power", 15_000, True),
    ("JPPOWER", "Jaiprakash Power Ventures", 11_000, True),
    ("SOMEMICRO", "Demo Microcap (synthetic)", 340, True),
]


def bucket_for(mcap_cr: float) -> str:
    if mcap_cr >= LARGE_MIN_CR:
        return "large"
    if mcap_cr >= MID_MIN_CR:
        return "mid"
    if mcap_cr > MICRO_MAX_CR:
        return "small"
    return "micro"


def main(offline: bool = False) -> None:
    rows = []
    for symbol, name, seed_cap, asm in SEED:
        mcap = seed_cap
        source = "seed"
        # SOMEMICRO is synthetic — it exists so the demo can show a micro-cap
        # refusal without libelling a real company. Never look it up.
        if not offline and symbol != "SOMEMICRO":
            live = market_cap_cr(symbol)
            if live:
                mcap, source = live, "yfinance"
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "cap_bucket": bucket_for(mcap),
                "mcap_cr": round(mcap, 1),
                "asm_gsm_flag": "1" if asm else "0",
                "mcap_source": source,
            }
        )
        print(f"{symbol:12} {rows[-1]['cap_bucket']:6} ₹{mcap:>12,.0f} Cr  ({source})")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["symbol", "name", "cap_bucket", "mcap_cr",
                        "asm_gsm_flag", "mcap_source"],
        )
        writer.writeheader()
        writer.writerows(rows)

    buckets: dict[str, int] = {}
    for r in rows:
        buckets[r["cap_bucket"]] = buckets.get(r["cap_bucket"], 0) + 1
    print(f"\nwrote {OUT} — {len(rows)} symbols, {buckets}")


if __name__ == "__main__":
    main(offline="--offline" in sys.argv)
