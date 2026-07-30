"""The six cases the spec demands, plus the edges around them.

All pure — no network, no LLM, no DB. Runs in milliseconds.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.factories import NOW, candidate, headline, position, quant, sentiment
from trading.config import load_desks
from trading.sentiment_rules import (
    conviction,
    conviction_qty,
    entry_allowed,
    exit_trigger,
)

DESKS = load_desks()
DAY = DESKS["day"]
SWING = DESKS["swing"]
LONG = DESKS["long_term"]

# The entry window is 09:30-14:30; NOW is 10:30, inside it.
AT = NOW


# ── 1. high composite score + negative sentiment => no entry ─────────────
def test_high_score_negative_sentiment_is_rejected():
    c = candidate(
        composite_score=95.0,
        sent=sentiment(score=-0.40, confidence=0.9, n_articles=20),
    )
    ok, why = entry_allowed(c, DAY, AT)
    assert ok is False
    assert why.startswith("sentiment_below_threshold")


def test_positive_sentiment_passes():
    ok, why = entry_allowed(candidate(), DAY, AT)
    assert ok is True and why is None


# ── 2. blocked event outranks a positive aggregate ───────────────────────
def test_promoter_pledge_blocks_entry_despite_positive_score():
    sent = sentiment(
        score=0.70,
        confidence=0.85,
        n_articles=12,
        drivers=[
            headline(sentiment=0.8, event_type="order_win"),
            headline(sentiment=-0.5, event_type="promoter_pledge", age_hours=2),
        ],
    )
    ok, why = entry_allowed(candidate(sent=sent), DAY, AT)
    assert ok is False
    assert why == "blocked_event:promoter_pledge"


def test_blocked_event_outside_freshness_window_does_not_block():
    """A pledge disclosure from last month is priced in, not news."""
    sent = sentiment(
        score=0.70,
        confidence=0.85,
        n_articles=12,
        drivers=[
            headline(sentiment=0.8, event_type="order_win", age_hours=1),
            headline(sentiment=-0.5, event_type="promoter_pledge", age_hours=200),
        ],
    )
    ok, why = entry_allowed(candidate(sent=sent), DAY, AT)
    assert ok is True, why


# ── 3. conviction sizing ─────────────────────────────────────────────────
def test_max_conviction_takes_a_full_slot():
    c = candidate(sent=sentiment(score=0.9, confidence=1.0, n_articles=20))
    assert conviction(c) == pytest.approx(0.9)
    # slot 10_000 at ₹100 => 0.5 + 0.5*0.9 = 0.95 of the slot => 95 shares
    assert conviction_qty(c, DAY, ltp=100.0, slot_value=10_000) == 95


def test_low_conviction_still_takes_half_a_slot():
    c = candidate(sent=sentiment(score=0.3, confidence=0.5, n_articles=20))
    assert conviction(c) == pytest.approx(0.15)
    # 0.5 + 0.5*0.15 = 0.575 => 57 shares
    assert conviction_qty(c, DAY, ltp=100.0, slot_value=10_000) == 57


def test_stretch_verdict_halves_conviction_but_still_enters():
    c = candidate(level="STRETCH",
                  sent=sentiment(score=0.8, confidence=1.0, n_articles=20))
    ok, _ = entry_allowed(c, DAY, AT)
    assert ok is True
    assert conviction(c) == pytest.approx(0.4)


def test_zero_price_sizes_to_zero_rather_than_dividing_by_zero():
    assert conviction_qty(candidate(), DAY, ltp=0.0, slot_value=10_000) == 0


def test_conviction_never_turns_an_affordable_entry_into_no_entry():
    """A high-priced share whose half-slot rounds to zero still buys one.
    Otherwise the desk quietly excludes everything above slot_value/2."""
    c = candidate(sent=sentiment(score=0.2, confidence=0.5, n_articles=20))
    # 0.55 of a 5,000 slot is 2,750 — less than one ₹3,724 share.
    assert conviction_qty(c, LONG, ltp=3_724.0, slot_value=5_000) == 1


def test_genuinely_unaffordable_share_sizes_to_zero():
    c = candidate(sent=sentiment(score=0.9, confidence=1.0, n_articles=20))
    assert conviction_qty(c, LONG, ltp=90_000.0, slot_value=5_000) == 0


# ── 4. sentiment reversal exit ───────────────────────────────────────────
def test_swing_exits_on_sentiment_reversal():
    pos = position(desk="swing", held_days=5, avg_price=1000.0)
    sent = sentiment(score=-0.15, confidence=0.7, age_hours=2)
    assert exit_trigger(pos, sent, SWING, ltp=1010.0, now=NOW) == "sentiment_reversal"


def test_min_hold_suppresses_reversal_exit_but_not_a_stop():
    pos = position(desk="swing", held_days=1, avg_price=1000.0)   # min_hold is 2
    sent = sentiment(score=-0.15, confidence=0.7, age_hours=2)
    assert exit_trigger(pos, sent, SWING, ltp=1010.0, now=NOW) is None
    # a stop still fires inside the minimum hold
    assert exit_trigger(pos, sent, SWING, ltp=930.0, now=NOW) == "stop_loss"


def test_positive_sentiment_holds():
    pos = position(desk="swing", held_days=5, avg_price=1000.0)
    assert exit_trigger(pos, sentiment(score=0.5), SWING, 1010.0, NOW) is None


# ── 5. staleness: no new entry, position RETAINED ────────────────────────
def test_stale_sentiment_blocks_entry_on_the_day_desk():
    c = candidate(sent=sentiment(score=0.8, confidence=0.9, n_articles=10,
                                 age_hours=9))     # day window is 6h
    ok, why = entry_allowed(c, DAY, AT)
    assert ok is False
    assert why.startswith("sentiment_stale")


def test_stale_sentiment_does_not_force_an_exit():
    """An absence of news is not a sell signal. A Wi-Fi outage must not
    become a liquidation event."""
    pos = position(desk="day", held_days=0, avg_price=1000.0)
    stale = sentiment(score=-0.9, confidence=0.9, age_hours=48)
    at_noon = NOW.replace(hour=12, minute=0)
    assert exit_trigger(pos, stale, DAY, ltp=1000.0, now=at_noon) is None


def test_missing_sentiment_does_not_force_an_exit():
    pos = position(desk="swing", held_days=5, avg_price=1000.0)
    assert exit_trigger(pos, None, SWING, ltp=1000.0, now=NOW) is None


# ── 6. lag guard ─────────────────────────────────────────────────────────
def test_already_priced_in_is_skipped_on_the_day_desk():
    c = candidate(q=quant(move_1d_pct=5.0))       # day cap is 3.0%
    ok, why = entry_allowed(c, DAY, AT)
    assert ok is False
    assert why.startswith("sentiment_already_priced")


def test_lag_guard_uses_the_right_field_per_horizon():
    """The day desk reads move_1d_pct, swing reads move_5d_pct."""
    c = candidate(horizon="swing", q=quant(move_1d_pct=5.0, move_5d_pct=2.0))
    ok, _ = entry_allowed(c, SWING, AT)
    assert ok is True          # 1d move is irrelevant to the swing desk

    c2 = candidate(horizon="swing", q=quant(move_1d_pct=0.5, move_5d_pct=9.0))
    ok2, why2 = entry_allowed(c2, SWING, AT)
    assert ok2 is False and why2.startswith("sentiment_already_priced")


def test_lag_guard_is_a_noop_when_track1_has_not_populated_the_field():
    c = candidate(q=quant(move_1d_pct=None))
    ok, why = entry_allowed(c, DAY, AT)
    assert ok is True, why


# ── mandate, horizon, window, leverage ───────────────────────────────────
def test_outside_mandate_is_a_hard_block_and_names_the_codes():
    c = candidate(level="OUTSIDE_MANDATE", block_codes=("R2", "R3"))
    ok, why = entry_allowed(c, DAY, AT)
    assert ok is False
    assert why == "mandate_blocked:R2,R3"


def test_wrong_horizon_never_reaches_a_desk():
    ok, why = entry_allowed(candidate(horizon="long_term"), DAY, AT)
    assert ok is False and why == "wrong_horizon"


def test_outside_entry_window_is_rejected():
    ok, why = entry_allowed(candidate(), DAY, NOW.replace(hour=15, minute=0))
    assert ok is False and why == "outside_entry_window"


def test_mandate_forbidding_leverage_blocks_the_intraday_desk():
    ok, why = entry_allowed(candidate(), DAY, AT, day_trading_allowed=False)
    assert ok is False and why == "mandate_forbids_intraday"


def test_insufficient_coverage_is_rejected():
    c = candidate(sent=sentiment(score=0.8, confidence=0.9, n_articles=1))
    ok, why = entry_allowed(c, DAY, AT)
    assert ok is False and why.startswith("insufficient_coverage")


def test_low_confidence_is_rejected():
    c = candidate(sent=sentiment(score=0.8, confidence=0.2, n_articles=10))
    ok, why = entry_allowed(c, DAY, AT)
    assert ok is False and why.startswith("confidence_below_threshold")


def test_long_desk_accepts_weaker_signals_than_the_day_desk():
    """Thresholds loosen as the horizon lengthens."""
    weak = sentiment(score=0.15, confidence=0.45, n_articles=6, age_hours=100)
    c = candidate(horizon="long_term", sent=weak, q=quant(move_20d_pct=3.0))
    assert entry_allowed(c, LONG, AT)[0] is True
    day_c = candidate(horizon="day", sent=weak)
    assert entry_allowed(day_c, DAY, AT)[0] is False


# ── exit precedence ──────────────────────────────────────────────────────
def test_square_off_outranks_everything():
    pos = position(desk="day", held_days=0, avg_price=1000.0)
    good = sentiment(score=0.9, age_hours=1)
    at_close = NOW.replace(hour=15, minute=20)
    assert exit_trigger(pos, good, DAY, ltp=1200.0, now=at_close) == "square_off"


def test_blocked_event_outranks_a_target():
    pos = position(desk="swing", held_days=5, avg_price=1000.0)
    sent = sentiment(
        score=0.6, age_hours=1,
        drivers=[headline(event_type="litigation", sentiment=-0.6, age_hours=1)],
    )
    # +20% would otherwise hit the 12% target
    assert exit_trigger(pos, sent, SWING, ltp=1200.0, now=NOW) == "blocked_event:litigation"


def test_stop_loss_outranks_sentiment_reversal():
    pos = position(desk="swing", held_days=5, avg_price=1000.0)
    sent = sentiment(score=-0.5, age_hours=1)
    assert exit_trigger(pos, sent, SWING, ltp=900.0, now=NOW) == "stop_loss"


def test_target_fires_when_nothing_worse_does():
    pos = position(desk="swing", held_days=5, avg_price=1000.0)
    assert exit_trigger(pos, sentiment(score=0.5), SWING, 1200.0, NOW) == "target"


def test_max_hold_fires_on_a_quiet_position():
    pos = position(desk="swing", held_days=20, avg_price=1000.0)
    assert exit_trigger(pos, sentiment(score=0.5), SWING, 1005.0, NOW) == "max_hold"


def test_long_desk_rebalances_rather_than_stopping_out():
    pos = position(desk="long_term", held_days=30, avg_price=1000.0)
    # long_term has no stop_loss_pct — a 40% drawdown must not stop out
    assert exit_trigger(pos, sentiment(score=0.5), LONG, 600.0, NOW) == "rebalance"


def test_desk_allocations_sum_to_one_hundred():
    assert sum(d.allocation_pct for d in DESKS.values()) == 100
