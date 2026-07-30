"""Process-wide engine holder.

One Engine per process. It rebuilds every desk's book by replaying the
journal at construction, so restarting the API never orphans a position.

Quotes: Kite LTPs when a valid token exists (real prices, no orders placed),
otherwise deterministic mock prices seeded from the fixture universe.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.contracts import Candidate
from trading.engine.core import Engine, load_fixture_candidates
from trading.execution.quotes import KiteQuoteSource, MockQuoteSource

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"

_engine: Engine | None = None
_quote_backend = "mock"


def fixture_candidates(now: datetime | None = None) -> dict[str, list[Candidate]]:
    return load_fixture_candidates(FIXTURES, rebase_to=now or datetime.now())


def _build_quotes():
    global _quote_backend
    from trading.execution.kite import load_kite

    kite = load_kite()
    if kite is not None:
        _quote_backend = "kite"
        return KiteQuoteSource(kite)

    _quote_backend = "mock"
    cands = fixture_candidates()
    base = {c.symbol: c.quant.ltp for lst in cands.values() for c in lst}
    return MockQuoteSource(base)


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine(_build_quotes())
    return _engine


def quote_backend() -> str:
    engine()
    return _quote_backend


def reset():
    """Test hook only."""
    global _engine
    _engine = None
