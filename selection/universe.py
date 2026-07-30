"""The traded universe, read from `data/universe.csv`.

Cap buckets and surveillance flags come from here, not from a live feed —
committed data means the refusal engine gives the same verdict offline as
online. Regenerate with `python -m scripts.build_universe`.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from core.contracts import CapBucket

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_CSV = ROOT / "data" / "universe.csv"


class UniverseRow(BaseModel):
    symbol: str
    name: str
    cap_bucket: CapBucket
    mcap_cr: float
    asm_gsm_flag: bool


@lru_cache(maxsize=1)
def universe() -> dict[str, UniverseRow]:
    rows: dict[str, UniverseRow] = {}
    if not UNIVERSE_CSV.exists():
        return rows
    with UNIVERSE_CSV.open(newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            symbol = raw["symbol"].strip().upper()
            rows[symbol] = UniverseRow(
                symbol=symbol,
                name=raw["name"].strip(),
                cap_bucket=raw["cap_bucket"].strip(),  # type: ignore[arg-type]
                mcap_cr=float(raw["mcap_cr"]),
                asm_gsm_flag=raw["asm_gsm_flag"].strip() in ("1", "true", "True"),
            )
    return rows


def row(symbol: str) -> UniverseRow | None:
    return universe().get(symbol.strip().upper())


def symbols(bucket: CapBucket | None = None) -> list[str]:
    if bucket is None:
        return sorted(universe())
    return sorted(s for s, r in universe().items() if r.cap_bucket == bucket)


def company_name(symbol: str) -> str:
    r = row(symbol)
    return r.name if r else symbol
