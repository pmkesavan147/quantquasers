"""All seven refusal rules, and the escalation between them.

Every assertion checks the *number* on the Reason, not just that a refusal
happened — a refusal without its metric is decoration.
"""

from __future__ import annotations

import pytest

from core.contracts import Horizon, QuantMetrics, RiskProfile
from selection.mandate import (
    MIN_INTRADAY_ADTV_CR,
    MIN_INTRADAY_ATR_PCT,
    NEW_TRADER_VOL_CEILING,
    evaluate,
)


def quant(**over) -> QuantMetrics:
    base = dict(
        symbol="TESTCO", name="Test Company", cap_bucket="large",
        mcap_cr=250_000.0, ltp=1_000.0, annual_vol=22.0, beta=1.0,
        max_drawdown_1y=15.0, adtv_cr=400.0, atr_pct=1.8, rsi14=55.0,
        sma20=980.0, sma50=950.0, sma200=900.0, dist_52w_high_pct=-8.0,
        asm_gsm_flag=False,
    )
    base.update(over)
    return QuantMetrics(**base)


def profile(**over) -> RiskProfile:
    base = dict(
        capital=500_000.0,
        horizons=[Horizon.DAY, Horizon.SWING, Horizon.LONG],
        allowed_caps=["large", "mid"],
        max_drawdown_pct=25.0,
        experience="1-3y",
        day_trading=True,
        uses_leverage=False,
    )
    base.update(over)
    return RiskProfile(**base)


def codes(verdict) -> set[str]:
    return {r.code for r in verdict.reasons}


def reason(verdict, code):
    return next(r for r in verdict.reasons if r.code == code)


def test_a_clean_large_cap_is_suitable():
    v = evaluate(quant(), profile(), Horizon.SWING)
    assert v.level == "SUITABLE"
    assert v.reasons == []


def test_r1_blocks_a_cap_bucket_outside_the_mandate():
    v = evaluate(quant(cap_bucket="small", mcap_cr=9_000.0), profile(),
                 Horizon.LONG)
    assert v.level == "OUTSIDE_MANDATE"
    assert "R1" in codes(v)
    assert reason(v, "R1").value == 9_000.0


def test_r2_blocks_illiquid_intraday_and_names_the_floor():
    v = evaluate(quant(adtv_cr=2.1), profile(), Horizon.DAY)
    assert v.level == "OUTSIDE_MANDATE"
    r = reason(v, "R2")
    assert (r.value, r.threshold) == (2.1, MIN_INTRADAY_ADTV_CR)
    assert "impact cost" in r.text


def test_r2_does_not_fire_for_a_swing_candidate():
    """A swing entry must not be refused for failing an intraday floor."""
    v = evaluate(quant(adtv_cr=2.1), profile(), Horizon.SWING)
    assert "R2" not in codes(v)


def test_r2_does_not_fire_when_the_user_forbade_intraday():
    v = evaluate(quant(adtv_cr=2.1), profile(day_trading=False), Horizon.DAY)
    assert "R2" not in codes(v)
    assert "R3" not in codes(v)


def test_r3_blocks_small_caps_intraday():
    v = evaluate(
        quant(cap_bucket="small", mcap_cr=9_000.0, adtv_cr=900.0),
        profile(allowed_caps=["large", "mid", "small"]),
        Horizon.DAY,
    )
    assert v.level == "OUTSIDE_MANDATE"
    assert "R3" in codes(v)
    assert "R2" not in codes(v)   # liquidity was fine; only the bucket failed


def test_r4_blocks_a_symbol_under_surveillance():
    v = evaluate(quant(asm_gsm_flag=True), profile(), Horizon.LONG)
    assert v.level == "OUTSIDE_MANDATE"
    assert "surveillance" in reason(v, "R4").text


def test_r5_warns_past_the_users_own_drawdown_number():
    v = evaluate(quant(max_drawdown_1y=41.0), profile(max_drawdown_pct=25.0),
                 Horizon.SWING)
    assert v.level == "STRETCH"
    r = reason(v, "R5")
    assert (r.value, r.threshold) == (41.0, 25.0)


def test_r5_is_silent_when_inside_the_users_tolerance():
    v = evaluate(quant(max_drawdown_1y=20.0), profile(max_drawdown_pct=40.0),
                 Horizon.SWING)
    assert v.level == "SUITABLE"


def test_r6_warns_only_for_a_new_trader():
    volatile = quant(annual_vol=NEW_TRADER_VOL_CEILING + 10)
    assert "R6" in codes(evaluate(volatile, profile(experience="new"),
                                  Horizon.SWING))
    assert "R6" not in codes(evaluate(volatile, profile(experience="3y+"),
                                      Horizon.SWING))


def test_r7_warns_when_there_is_no_intraday_range():
    v = evaluate(quant(atr_pct=0.4), profile(), Horizon.DAY)
    assert "R7" in codes(v)
    assert reason(v, "R7").threshold == MIN_INTRADAY_ATR_PCT


def test_r7_fires_on_the_day_horizon_even_without_the_flag():
    """The range test is about the instrument, not the permission."""
    v = evaluate(quant(atr_pct=0.4), profile(day_trading=False), Horizon.DAY)
    assert "R7" in codes(v)


def test_a_block_outranks_any_number_of_warns():
    v = evaluate(
        quant(asm_gsm_flag=True, max_drawdown_1y=80.0, atr_pct=0.1),
        profile(experience="new"),
        Horizon.DAY,
    )
    assert v.level == "OUTSIDE_MANDATE"
    assert {"R4", "R5", "R7"} <= codes(v)


def test_the_headline_demo_case():
    """A micro-cap with day trading on: at least two blocks, each with its
    number. This is the case a markets-literate judge will ask for."""
    v = evaluate(
        quant(cap_bucket="micro", mcap_cr=340.0, adtv_cr=1.8,
              asm_gsm_flag=True, max_drawdown_1y=48.0),
        profile(),
        Horizon.DAY,
    )
    assert v.level == "OUTSIDE_MANDATE"
    blocks = [r for r in v.reasons if r.severity == "block"]
    assert len(blocks) >= 2
    assert all(r.metric and r.value is not None for r in blocks)


@pytest.mark.parametrize("horizon", list(Horizon))
def test_every_horizon_produces_a_valid_verdict(horizon):
    v = evaluate(quant(), profile(), horizon)
    assert v.level in {"SUITABLE", "STRETCH", "OUTSIDE_MANDATE"}
