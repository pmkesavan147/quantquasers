"""Every risk rule fires, and none of them can be relaxed at runtime."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from trading.config import RiskLimits, load_desks
from trading.journal.store import Journal
from trading.models import ProposedOrder
from trading.risk.manager import PortfolioState, RiskManager

DESKS = load_desks()
NOW = datetime(2026, 7, 30, 10, 30)

LIMITS = RiskLimits(
    max_capital=100_000,
    max_position_pct=10,
    daily_loss_limit_pct=2,
    max_orders_per_day=10,
    allow_intraday=True,
    allowlist=("TATAMOTORS", "TCS", "RELIANCE"),
)


@pytest.fixture
def rm(tmp_path):
    return RiskManager(LIMITS, Journal(tmp_path / "j.sqlite3"))


def order(**kw) -> ProposedOrder:
    base = dict(desk="swing", symbol="TATAMOTORS", side="BUY", qty=5,
                product="CNC", reason="test")
    base.update(kw)
    return ProposedOrder(**base)


# ── limits are immutable ─────────────────────────────────────────────────
def test_limits_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        LIMITS.max_position_pct = 100  # type: ignore[misc]


def test_risk_manager_exposes_no_way_to_relax_a_limit():
    names = [n for n in dir(RiskManager) if not n.startswith("_")]
    for banned in ("set_limits", "update_limits", "disable", "override"):
        assert banned not in names


# ── the gauntlet, rule by rule ───────────────────────────────────────────
def test_halted_engine_approves_nothing(rm):
    rm.halt("manual")
    v = rm.evaluate(order(), PortfolioState(), quote=1000)
    assert v.decision == "veto" and "halted" in v.rule_fired


def test_resume_clears_the_halt(rm):
    rm.halt("manual")
    rm.resume()
    assert rm.evaluate(order(), PortfolioState(), 1000).decision == "approve"


def test_daily_loss_limit_trips_the_halt_and_vetoes(rm):
    state = PortfolioState(day_pnl=-2_500)      # limit is 2% of 100k = 2,000
    v = rm.evaluate(order(), state, quote=1000)
    assert v.decision == "veto" and v.rule_fired == "daily_loss_limit"
    assert rm.halted is True                     # stays halted for the session


def test_loss_just_inside_the_limit_still_trades(rm):
    v = rm.evaluate(order(), PortfolioState(day_pnl=-1_999), quote=1000)
    assert v.decision == "approve" and rm.halted is False


def test_max_orders_per_day_backstop(rm):
    v = rm.evaluate(order(), PortfolioState(orders_today=10), quote=1000)
    assert v.decision == "veto" and v.rule_fired == "max_orders_per_day"


def test_allowlist_vetoes_however_good_the_signal(rm):
    v = rm.evaluate(order(symbol="SOMEMICRO"), PortfolioState(), quote=88)
    assert v.decision == "veto" and v.rule_fired == "allowlist"


def test_no_quote_no_order(rm):
    v = rm.evaluate(order(), PortfolioState(), quote=0)
    assert v.decision == "veto" and v.rule_fired == "no_valid_quote"


# ── SELL side ────────────────────────────────────────────────────────────
def test_cannot_sell_what_is_not_held(rm):
    v = rm.evaluate(order(side="SELL"), PortfolioState(), quote=1000)
    assert v.decision == "veto" and v.rule_fired == "no_position_to_sell"


def test_sell_is_capped_at_held_quantity(rm):
    state = PortfolioState(positions={"TATAMOTORS": 3},
                           position_value={"TATAMOTORS": 3000})
    v = rm.evaluate(order(side="SELL", qty=10), state, quote=1000)
    assert v.decision == "resize" and v.final_qty == 3
    assert v.rule_fired == "sell_capped_at_held"


# ── BUY sizing ───────────────────────────────────────────────────────────
def test_per_position_cap_resizes(rm):
    """10% of 100k = 10,000 => at ₹1,000 the cap is 10 shares."""
    v = rm.evaluate(order(qty=25), PortfolioState(), quote=1000)
    assert v.decision == "resize" and v.final_qty == 10
    assert v.rule_fired == "max_position_pct"


def test_existing_exposure_reduces_the_remaining_room(rm):
    state = PortfolioState(positions={"TATAMOTORS": 6},
                           position_value={"TATAMOTORS": 6000})
    v = rm.evaluate(order(qty=25), state, quote=1000)
    assert v.decision == "resize" and v.final_qty == 4


def test_full_position_is_vetoed_not_resized_to_zero(rm):
    state = PortfolioState(positions={"TATAMOTORS": 10},
                           position_value={"TATAMOTORS": 10_000})
    v = rm.evaluate(order(qty=5), state, quote=1000)
    assert v.decision == "veto" and v.rule_fired == "max_position_pct"


def test_desk_allocation_binds_before_the_firm_cap(rm):
    """The day desk has 20% of 100k = 20,000. With 19,000 deployed there is
    ₹1,000 of room, so at ₹1,000 exactly one share fits."""
    day = DESKS["day"]
    state = PortfolioState(desk_deployed=19_000)
    v = rm.evaluate(order(desk="day", product="MIS", qty=10), state,
                    quote=1000, desk=day, now=NOW)
    assert v.decision == "resize" and v.final_qty == 1
    assert v.rule_fired == "desk_allocation"


def test_exhausted_desk_allocation_vetoes(rm):
    day = DESKS["day"]
    state = PortfolioState(desk_deployed=20_000)
    v = rm.evaluate(order(desk="day", product="MIS"), state, quote=1000,
                    desk=day, now=NOW)
    assert v.decision == "veto" and v.rule_fired == "desk_allocation"


# ── intraday rules ───────────────────────────────────────────────────────
def test_no_new_intraday_entries_after_square_off(rm):
    day = DESKS["day"]
    at_close = NOW.replace(hour=15, minute=20)
    v = rm.evaluate(order(desk="day", product="MIS"), PortfolioState(),
                    quote=1000, desk=day, now=at_close)
    assert v.decision == "veto" and v.rule_fired == "day_square_off_window"


def test_exits_are_still_allowed_after_square_off(rm):
    """Vetoing the exit would be the opposite of what square-off means."""
    day = DESKS["day"]
    at_close = NOW.replace(hour=15, minute=20)
    state = PortfolioState(positions={"TATAMOTORS": 5},
                           position_value={"TATAMOTORS": 5000})
    v = rm.evaluate(order(desk="day", product="MIS", side="SELL", qty=5),
                    state, quote=1000, desk=day, now=at_close)
    assert v.decision == "approve"


def test_product_desk_mismatch_is_a_config_error_and_is_vetoed(rm):
    day = DESKS["day"]                       # day desk is MIS
    v = rm.evaluate(order(desk="day", product="CNC"), PortfolioState(),
                    quote=1000, desk=day, now=NOW)
    assert v.decision == "veto" and v.rule_fired == "product_desk_mismatch"


def test_firm_level_intraday_switch_vetoes_mis(tmp_path):
    limits = dataclasses.replace(LIMITS, allow_intraday=False)
    rm = RiskManager(limits, Journal(tmp_path / "j.sqlite3"))
    day = DESKS["day"]
    v = rm.evaluate(order(desk="day", product="MIS"), PortfolioState(),
                    quote=1000, desk=day, now=NOW)
    assert v.decision == "veto" and v.rule_fired == "intraday_disabled"


# ── auditability ─────────────────────────────────────────────────────────
def test_every_verdict_is_journaled_with_its_rule(tmp_path):
    journal = Journal(tmp_path / "j.sqlite3")
    rm = RiskManager(LIMITS, journal)
    rm.evaluate(order(symbol="SOMEMICRO"), PortfolioState(), quote=88)
    entries = journal.recent(5, kind="verdict")
    assert len(entries) == 1
    assert entries[0]["payload"]["rule_fired"] == "allowlist"
