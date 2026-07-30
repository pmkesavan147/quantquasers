"""End-to-end on fixtures: candidates -> orders -> verdicts -> fills -> journal.

No network, no LLM, no Kite. This is the 6-hour integration checkpoint,
runnable as a test.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from trading.config import RiskLimits, load_desks
from trading.engine.core import Engine, load_fixture_candidates
from trading.execution.quotes import MockQuoteSource
from trading.journal.store import Journal

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
NOW = datetime(2026, 7, 30, 10, 30)

LIMITS = RiskLimits(
    max_capital=100_000,
    max_position_pct=10,
    daily_loss_limit_pct=2,
    max_orders_per_day=50,
    allow_intraday=True,
    allowlist=tuple(
        line.strip().upper()
        for line in (ROOT / "trading" / "allowlist.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ),
)


@pytest.fixture
def cands():
    return load_fixture_candidates(FIXTURES, rebase_to=NOW)


@pytest.fixture
def engine(tmp_path, cands, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    prices = {c.symbol: c.quant.ltp for lst in cands.values() for c in lst}
    return Engine(
        MockQuoteSource(prices),
        journal=Journal(tmp_path / "j.sqlite3"),
        limits=LIMITS,
        desks=load_desks(),
    )


# ── fixtures are valid ───────────────────────────────────────────────────
def test_fixtures_parse_and_cover_all_three_horizons(cands):
    assert set(cands) == {"day", "swing", "long_term"}
    assert all(len(v) > 0 for v in cands.values())


def test_fixtures_include_a_hard_refusal(cands):
    blocked = [c for c in cands["day"] if c.verdict.level == "OUTSIDE_MANDATE"]
    assert blocked, "the day fixtures must include the refusal demo case"
    assert len(blocked[0].verdict.reasons) >= 2
    assert all(r.value is not None for r in blocked[0].verdict.reasons)


def test_rebasing_makes_the_newest_headline_current(cands):
    newest = max(c.sentiment.as_of for c in cands["day"])
    assert abs((newest - NOW).total_seconds()) < 1


# ── the engine runs paper by default ─────────────────────────────────────
def test_engine_is_paper_and_the_gate_is_shut(engine):
    assert engine.mode == "paper"
    assert engine.gate_reasons


def test_day_desk_trades_only_what_survives_the_sentiment_gate(engine, cands):
    run = engine.run_desk("day", cands["day"], now=NOW)
    filled = {f.symbol for f in run.fills}
    skipped = {s.symbol: s.reason for s in run.skips}

    # positive, fresh, liquid, well-covered => in
    assert "TATAMOTORS" in filled

    # ranked highest on composite score, but the news is negative => out
    assert skipped["RELIANCE"].startswith("sentiment_below_threshold")

    # positive aggregate sitting on a promoter pledge => out
    assert skipped["ADANIPORTS"] == "blocked_event:promoter_pledge"

    # already ran 5.2% today, day cap is 3% => out
    assert skipped["ITC"].startswith("sentiment_already_priced")

    # micro cap, thin, under surveillance, day trading on => hard refusal
    assert skipped["SOMEMICRO"].startswith("mandate_blocked")


def test_stretch_candidate_enters_smaller_than_a_suitable_one(engine, cands):
    run = engine.run_desk("day", cands["day"], now=NOW)
    by_symbol = {f.symbol: f for f in run.fills}
    if "TITAN" in by_symbol and "TATAMOTORS" in by_symbol:
        titan = by_symbol["TITAN"].qty * by_symbol["TITAN"].price
        tata = by_symbol["TATAMOTORS"].qty * by_symbol["TATAMOTORS"].price
        assert titan < tata


def test_swing_desk_rejects_stale_and_low_confidence(engine, cands):
    run = engine.run_desk("swing", cands["swing"], now=NOW)
    skipped = {s.symbol: s.reason for s in run.skips}
    assert skipped["INFY"].startswith("sentiment_stale")
    assert skipped["WIPRO"].startswith("confidence_below_threshold")
    assert {"TCS", "HDFCBANK"} <= {f.symbol for f in run.fills}


def test_long_desk_rejects_thin_coverage(engine, cands):
    run = engine.run_desk("long_term", cands["long_term"], now=NOW)
    skipped = {s.symbol: s.reason for s in run.skips}
    assert skipped["COALINDIA"].startswith("insufficient_coverage")


def test_max_positions_is_respected(engine, cands):
    run = engine.run_desk("day", cands["day"], now=NOW)
    assert len(engine.brokers["day"].positions()) <= engine.desks["day"].max_positions
    if any(s.reason == "no_free_slot" for s in run.skips):
        assert len(run.fills) == engine.desks["day"].max_positions


# ── the journal is the source of truth ───────────────────────────────────
def test_every_step_is_journaled(engine, cands):
    engine.run_desk("day", cands["day"], now=NOW)
    for kind in ("proposal", "verdict", "fill", "skip"):
        assert engine.journal.recent(100, kind=kind), f"nothing journaled for {kind}"


def test_book_survives_a_restart_by_replaying_the_journal(tmp_path, cands, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    prices = {c.symbol: c.quant.ltp for lst in cands.values() for c in lst}
    db = tmp_path / "j.sqlite3"
    desks = load_desks()

    e1 = Engine(MockQuoteSource(prices), journal=Journal(db), limits=LIMITS, desks=desks)
    e1.run_desk("day", cands["day"], now=NOW)
    before = e1.brokers["day"].positions()
    cash_before = round(e1.brokers["day"].cash(), 2)
    assert before, "expected at least one position to replay"

    e2 = Engine(MockQuoteSource(prices), journal=Journal(db), limits=LIMITS, desks=desks)
    assert e2.brokers["day"].positions() == before
    assert round(e2.brokers["day"].cash(), 2) == cash_before


def test_fills_carry_itemised_costs(engine, cands):
    run = engine.run_desk("day", cands["day"], now=NOW)
    assert run.fills
    assert all(f.costs > 0 for f in run.fills)


def test_day_desk_uses_mis_and_others_use_cnc(engine, cands):
    day = engine.run_desk("day", cands["day"], now=NOW)
    swing = engine.run_desk("swing", cands["swing"], now=NOW)
    assert all(f.product == "MIS" for f in day.fills)
    assert all(f.product == "CNC" for f in swing.fills)


# ── the demo checks ──────────────────────────────────────────────────────
def test_a_day_entry_after_square_off_is_vetoed(engine, cands):
    at_close = NOW.replace(hour=15, minute=20)
    run = engine.run_desk("day", cands["day"], now=at_close)
    # the entry window closes at 14:30, so the desk declines before the CRO
    reasons = {s.reason for s in run.skips}
    assert "outside_entry_window" in reasons
    assert not [f for f in run.fills if f.side == "BUY"]


def test_position_opened_then_squared_off_the_same_day(engine, cands):
    """The full intraday round trip, including the mechanical exit."""
    engine.run_desk("day", cands["day"], now=NOW)
    held = set(engine.brokers["day"].positions())
    assert held

    at_close = NOW.replace(hour=15, minute=20)
    run = engine.run_desk("day", cands["day"], now=at_close)
    sells = [f for f in run.fills if f.side == "SELL"]
    assert sells, "square-off must close intraday positions"
    assert all("square_off" in f.reason for f in sells)
    assert not engine.brokers["day"].positions()


def test_sentiment_reversal_closes_a_swing_position(engine, cands):
    engine.run_desk("swing", cands["swing"], now=NOW)
    held = set(engine.brokers["swing"].positions())
    assert "TCS" in held

    # The thesis breaks: coverage turns negative, three days later.
    later = NOW + timedelta(days=3)
    for c in cands["swing"]:
        if c.symbol == "TCS":
            c.sentiment.score = -0.40
            c.sentiment.as_of = later - timedelta(hours=1)
            for h in c.sentiment.drivers:
                h.published_at = later - timedelta(hours=2)

    run = engine.run_desk("swing", cands["swing"], now=later)
    sells = [f for f in run.fills if f.symbol == "TCS" and f.side == "SELL"]
    assert sells, "a sentiment reversal must close the position"
    assert "sentiment_reversal" in sells[0].reason


def test_daily_loss_kill_switch_halts_the_firm(engine, cands):
    engine.run_desk("day", cands["day"], now=NOW)
    # Mark the book down hard: -40% on every held name.
    for sym in list(engine.brokers["day"].positions()):
        engine.quotes.set(sym, engine.brokers["day"].avg_price(sym) * 0.6)

    engine.run_desk("swing", cands["swing"], now=NOW)
    assert engine.risk.halted is True
    assert "daily loss" in (engine.risk.halt_reason or "")

    alerts = [e["payload"] for e in engine.journal.recent(50, kind="alert")]
    assert any(a.get("event") == "halt" for a in alerts)


def test_portfolio_snapshot_is_internally_consistent(engine, cands):
    engine.run_all(cands, now=NOW)
    p = engine.portfolio()
    assert p.mode == "paper"
    assert len(p.desks) == 3
    assert p.deployed == pytest.approx(sum(d.deployed for d in p.desks), abs=0.05)
    assert p.deployed <= p.capital
