"""Process-wide engine holder.

One Engine per process. It rebuilds every desk's book by replaying the
journal at construction, so restarting the API never orphans a position.

Quotes: Kite LTPs when a valid token exists (real prices, no orders placed),
otherwise deterministic mock prices seeded from the fixture universe.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.contracts import Candidate, RiskProfile
from trading.allocation import allocate, risk_band
from trading.engine.core import Engine, load_fixture_candidates
from trading.execution.quotes import KiteQuoteSource, MockQuoteSource

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"

_engine: Engine | None = None
_quote_backend = "mock"
_profile: RiskProfile | None = None


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
        _engine = Engine(_build_quotes(), profile=_profile)
    return _engine


def profile() -> RiskProfile | None:
    return _profile


def set_profile(p: RiskProfile) -> Engine:
    """Account creation. Rebuilds the engine so the new capital and the new
    desk split take effect immediately.

    The journal is untouched — it is append-only and every book replays from
    it, so changing the allocation never rewrites trading history.
    """
    global _profile, _engine
    _profile = p
    _engine = Engine(_build_quotes(), profile=p)
    _engine.journal.append(
        "note",
        {
            "event": "account_created",
            "capital": p.capital,
            "risk_band": risk_band(p),
            "allocation_pct": allocate(p),
            "day_trading": p.day_trading,
            "sip_amount": p.sip_amount,
            "sip_frequency": p.sip_frequency,
        },
    )
    return _engine


def quote_backend() -> str:
    engine()
    return _quote_backend


def reset():
    """Test hook only."""
    global _engine, _profile
    _engine = None
    _profile = None
