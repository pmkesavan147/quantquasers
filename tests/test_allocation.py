"""Capital allocation derived from the risk band.

Pure functions — same profile in, same split out. The whole point is that no
model can move an equity allocation.
"""

from __future__ import annotations

import pytest

from core.contracts import Horizon, RiskProfile
from trading.allocation import (
    BASE_WEIGHTS,
    allocate,
    apply_to_desks,
    eligible_desks,
    explain,
    risk_band,
    rubric_score,
    rupees,
)
from trading.config import load_desks

ALL = [Horizon.DAY, Horizon.SWING, Horizon.LONG]


def profile(**kw) -> RiskProfile:
    base = dict(
        capital=500_000.0,
        horizons=ALL,
        allowed_caps=["large", "mid", "small"],
        max_drawdown_pct=25.0,
        experience="1-3y",
        day_trading=True,
        uses_leverage=False,
    )
    base.update(kw)
    return RiskProfile(**base)


SAFE = profile(
    horizons=[Horizon.LONG], allowed_caps=["large"], max_drawdown_pct=10.0,
    experience="new", day_trading=False, uses_leverage=False,
)
AGGRESSIVE = profile(
    allowed_caps=["large", "mid", "small", "micro"], max_drawdown_pct=40.0,
    experience="3y+", day_trading=True, uses_leverage=True,
)


# ── the rubric ───────────────────────────────────────────────────────────
def test_safe_player_is_conservative():
    assert risk_band(SAFE) == "conservative"


def test_high_risk_high_reward_is_aggressive():
    assert risk_band(AGGRESSIVE) == "aggressive"


def test_default_profile_is_balanced():
    assert risk_band(profile()) == "balanced"


def test_drawdown_tolerance_moves_the_score_most():
    low = rubric_score(profile(max_drawdown_pct=5.0))
    high = rubric_score(profile(max_drawdown_pct=40.0))
    assert high - low == 3


def test_allowing_micro_caps_raises_the_score():
    with_micro = rubric_score(profile(allowed_caps=["large", "mid", "small", "micro"]))
    without = rubric_score(profile(allowed_caps=["large", "mid", "small"]))
    assert with_micro > without


def test_score_is_never_negative():
    assert rubric_score(
        profile(horizons=[Horizon.LONG], allowed_caps=["large"],
                max_drawdown_pct=1.0, experience="new", day_trading=False)
    ) >= 0


# ── Gemma's read is bounded ──────────────────────────────────────────────
def test_gemma_can_nudge_one_notch_up():
    p = profile(trader_type=Horizon.DAY, confidence=0.9)
    assert risk_band(profile()) == "balanced"
    assert risk_band(p) == "aggressive"


def test_gemma_can_nudge_one_notch_down():
    p = profile(trader_type=Horizon.LONG, confidence=0.9)
    assert risk_band(p) == "conservative"


def test_gemma_below_the_confidence_floor_is_ignored():
    p = profile(trader_type=Horizon.DAY, confidence=0.5)
    assert risk_band(p) == "balanced"


def test_gemma_cannot_move_more_than_one_notch():
    """A confident model read must not turn a safe player into an aggressive
    allocation. The rubric is the authority."""
    p = RiskProfile(**{**SAFE.model_dump(), "trader_type": Horizon.DAY,
                       "confidence": 1.0})
    assert risk_band(p) == "balanced"      # conservative -> balanced, no further


def test_gemma_cannot_push_past_the_ends():
    top = RiskProfile(**{**AGGRESSIVE.model_dump(), "trader_type": Horizon.DAY,
                         "confidence": 1.0})
    assert risk_band(top) == "aggressive"


# ── allocation ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("p", [SAFE, AGGRESSIVE, profile(),
                               profile(day_trading=False),
                               profile(horizons=[Horizon.SWING])])
def test_allocation_always_sums_to_exactly_one_hundred(p):
    assert sum(allocate(p).values()) == pytest.approx(100.0, abs=0.001)


def test_three_modes_when_day_trading_is_on():
    a = allocate(profile())
    assert set(a) == {"day", "swing", "long_term"}
    assert a == BASE_WEIGHTS["balanced"]


def test_opting_out_of_intraday_removes_the_day_desk():
    a = allocate(profile(day_trading=False))
    assert "day" not in a
    assert set(a) == {"swing", "long_term"}


def test_the_day_desks_share_is_redistributed_not_lost():
    with_day = allocate(profile())
    without = allocate(profile(day_trading=False))
    assert without["swing"] > with_day["swing"]
    assert without["long_term"] > with_day["long_term"]
    assert sum(without.values()) == pytest.approx(100.0)


def test_aggressive_without_intraday_is_fifty_fifty():
    a = allocate(RiskProfile(**{**AGGRESSIVE.model_dump(), "day_trading": False}))
    assert a == {"swing": 50.0, "long_term": 50.0}


def test_conservative_tilts_hard_to_long_term():
    a = allocate(SAFE)
    assert set(a) == {"long_term"}
    assert a["long_term"] == 100.0


def test_aggressive_gives_the_day_desk_six_times_the_conservative_weight():
    agg = BASE_WEIGHTS["aggressive"]["day"]
    con = BASE_WEIGHTS["conservative"]["day"]
    assert agg / con == 6.0


def test_a_profile_with_no_usable_horizon_still_allocates():
    a = allocate(profile(horizons=[], day_trading=False))
    assert a == {"long_term": 100.0}


def test_day_horizon_without_the_day_trading_flag_is_dropped():
    """Selecting the intraday horizon but declining day trading must not
    quietly re-enable the desk."""
    assert "day" not in eligible_desks(profile(day_trading=False))


# ── money ────────────────────────────────────────────────────────────────
def test_rupees_match_the_declared_capital():
    p = profile(capital=500_000.0)
    money = rupees(p)
    assert sum(money.values()) == pytest.approx(500_000.0, abs=1.0)
    assert money["long_term"] == pytest.approx(275_000.0)


def test_capital_scales_the_split_linearly():
    small = rupees(profile(capital=100_000.0))
    big = rupees(profile(capital=1_000_000.0))
    for desk in small:
        assert big[desk] == pytest.approx(small[desk] * 10)


def test_capital_must_be_positive():
    with pytest.raises(ValueError):
        profile(capital=0)


# ── applying it to desk configs ──────────────────────────────────────────
def test_apply_rewrites_allocations_and_disables_opted_out_desks():
    desks = apply_to_desks(load_desks(), profile(day_trading=False))
    assert desks["day"].enabled is False
    assert desks["day"].allocation_pct == 0.0
    assert desks["swing"].enabled and desks["long_term"].enabled
    enabled_total = sum(d.allocation_pct for d in desks.values() if d.enabled)
    assert enabled_total == pytest.approx(100.0)


def test_disabled_desks_are_kept_not_deleted():
    """The UI needs to say 'day desk off — you opted out', not silently omit it."""
    desks = apply_to_desks(load_desks(), profile(day_trading=False))
    assert set(desks) == {"day", "swing", "long_term"}


def test_desk_capital_follows_the_profile():
    from trading.config import RiskLimits

    p = profile(capital=500_000.0)
    desks = apply_to_desks(load_desks(), p)
    limits = RiskLimits(max_capital=p.capital)
    assert desks["long_term"].capital(limits) == pytest.approx(275_000.0)
    assert desks["day"].capital(limits) == pytest.approx(75_000.0)


# ── the explanation the UI renders ───────────────────────────────────────
def test_explain_shows_the_band_the_money_and_which_desks_are_off():
    e = explain(profile(day_trading=False, capital=500_000.0))
    assert e["risk_band"] == "balanced"
    assert e["desks_off"] == ["day"]
    assert sum(e["allocation_rupees"].values()) == pytest.approx(500_000.0, abs=1.0)
    assert e["gemma_applied"] is False


def test_explain_reports_when_gemma_moved_the_band():
    e = explain(profile(trader_type=Horizon.DAY, confidence=0.9))
    assert e["gemma_applied"] is True
    assert e["gemma_read"] == "day"
    assert e["risk_band"] == "aggressive"


def test_explain_describes_the_sip_when_one_is_set():
    e = explain(profile(sip_amount=10_000, sip_frequency="monthly"))
    assert e["sip"]["amount"] == 10_000
    assert e["sip"]["target_desk"] == "long_term"


def test_explain_reports_no_sip_target_when_disabled():
    assert explain(profile())["sip"]["target_desk"] is None


# ── determinism ──────────────────────────────────────────────────────────
def test_allocation_is_deterministic():
    p = profile()
    assert [allocate(p) for _ in range(5)].count(allocate(p)) == 5
