"""Quant metrics, sentiment aggregation and ranking — all on synthetic data.

No network and no model anywhere in this file. If any of these tests need
either, the deterministic half of the system has leaked into the probabilistic
half and that is the bug.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd
import pytest

from core.contracts import HeadlineScore, Horizon, QuantMetrics, SymbolSentiment
from selection import ranker
from selection.quant import metrics_from_frames
from selection.sentiment import FALLBACK_TRUST, aggregate, market_mood

NOW = datetime(2026, 7, 30, 10, 30)


def frame(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    volumes = volumes or [100_000.0] * len(closes)
    index = pd.date_range(end="2026-07-30", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": volumes,
        },
        index=index,
    )


# ── quant ────────────────────────────────────────────────────────────────
def test_a_flat_series_has_no_volatility_and_no_drawdown():
    q = metrics_from_frames("TESTCO", frame([100.0] * 260))
    assert q.annual_vol == 0.0
    assert q.max_drawdown_1y == 0.0
    assert q.ltp == 100.0


def test_max_drawdown_measures_peak_to_trough():
    closes = [100.0] * 30 + [200.0] + [120.0] + [160.0] * 30
    q = metrics_from_frames("TESTCO", frame(closes))
    assert q.max_drawdown_1y == pytest.approx(40.0, abs=0.1)


def test_adtv_uses_the_last_thirty_sessions_in_crore():
    # 100 sessions of ₹1cr/day, then 30 of ₹10cr/day: only the recent window counts.
    closes = [100.0] * 130
    volumes = [10_000.0] * 100 + [100_000.0] * 30
    q = metrics_from_frames("TESTCO", frame(closes, volumes))
    assert q.adtv_cr == pytest.approx(100.0 * 100_000.0 / 1e7, rel=0.01)


def test_rsi_saturates_on_an_unbroken_advance():
    q = metrics_from_frames("TESTCO", frame([100.0 + i for i in range(60)]))
    assert q.rsi14 == 100.0


def test_beta_of_one_against_an_identical_market():
    closes = [100.0 * (1.001**i) for i in range(200)]
    df = frame(closes)
    q = metrics_from_frames("TESTCO", df, df)
    assert q.beta == pytest.approx(1.0, abs=0.05)


def test_distance_from_the_52_week_high_is_negative_off_the_top():
    closes = [100.0] * 100 + [150.0] + [120.0] * 20
    q = metrics_from_frames("TESTCO", frame(closes))
    assert q.dist_52w_high_pct == pytest.approx(-20.0, abs=0.1)


def test_recent_move_fields_are_populated_for_the_lag_guard():
    q = metrics_from_frames("TESTCO", frame([100.0 + i for i in range(40)]))
    assert q.move_1d_pct is not None and q.move_1d_pct > 0
    assert q.move_20d_pct is not None and q.move_20d_pct > q.move_1d_pct


def test_unknown_symbols_do_not_invent_a_market_cap():
    q = metrics_from_frames("NOTINUNIVERSE", frame([100.0] * 60))
    assert q.mcap_cr == 0.0
    assert q.asm_gsm_flag is False


# ── sentiment aggregation ────────────────────────────────────────────────
def score(
    sentiment: float, *, hours_ago: float = 1.0, materiality: int = 3,
    model: str = "gemma-4", event: str = "earnings", ident: str = "h",
) -> HeadlineScore:
    return HeadlineScore(
        id=ident, symbol="TESTCO", title="t", source="s", url="",
        published_at=NOW - timedelta(hours=hours_ago),
        sentiment=sentiment,
        label="positive" if sentiment > 0.15 else
              "negative" if sentiment < -0.15 else "neutral",
        event_type=event, materiality=materiality, rationale="r", model=model,
    )


def test_no_headlines_means_zero_confidence_not_zero_sentiment_with_confidence():
    s = aggregate("TESTCO", [], now=NOW)
    assert (s.score, s.confidence, s.n_articles) == (0.0, 0.0, 0)


def test_recent_headlines_outweigh_old_ones():
    s = aggregate(
        "TESTCO",
        [score(1.0, hours_ago=1, ident="new"),
         score(-1.0, hours_ago=24 * 10, ident="old")],
        now=NOW,
    )
    assert s.score > 0.5


def test_materiality_scales_the_weight():
    s = aggregate(
        "TESTCO",
        [score(1.0, materiality=5, ident="big"),
         score(-1.0, materiality=1, ident="small")],
        now=NOW,
    )
    assert s.score > 0.4


def test_disagreement_between_headlines_lowers_confidence():
    agree = aggregate("TESTCO", [score(0.6, ident=f"a{i}") for i in range(8)],
                      now=NOW)
    disagree = aggregate(
        "TESTCO",
        [score(0.9 if i % 2 else -0.9, ident=f"d{i}") for i in range(8)],
        now=NOW,
    )
    assert disagree.confidence < agree.confidence


def test_thin_coverage_caps_confidence():
    one = aggregate("TESTCO", [score(0.8, ident="only")], now=NOW)
    assert one.confidence <= 1 / 8


def test_the_keyword_fallback_is_trusted_less_than_a_model():
    real = aggregate("TESTCO", [score(0.5, ident=f"r{i}") for i in range(8)],
                     now=NOW)
    fake = aggregate(
        "TESTCO",
        [score(0.5, model="fallback", ident=f"f{i}") for i in range(8)],
        now=NOW,
    )
    assert fake.confidence == pytest.approx(real.confidence * FALLBACK_TRUST,
                                            rel=0.01)


def test_top_events_are_ranked_by_weight_not_count():
    scores = [
        score(-0.9, materiality=5, event="regulatory", ident="reg"),
        score(0.2, materiality=1, event="analyst_view", ident="a1"),
        score(0.2, materiality=1, event="analyst_view", ident="a2"),
    ]
    s = aggregate("TESTCO", scores, now=NOW)
    assert s.top_events[0] == "regulatory"


def test_drivers_are_the_three_loudest_headlines():
    scores = [score(0.1 * i, ident=f"h{i}") for i in range(1, 9)]
    s = aggregate("TESTCO", scores, now=NOW)
    assert len(s.drivers) == 3
    assert abs(s.drivers[0].sentiment) >= abs(s.drivers[-1].sentiment)


def test_naive_and_aware_timestamps_do_not_crash_the_weighting():
    from datetime import timezone

    aware = score(0.5, ident="aware").model_copy(
        update={"published_at": datetime.now(timezone.utc)}
    )
    s = aggregate("TESTCO", [aware], now=datetime.now())
    assert s.n_articles == 1


def test_market_mood_ignores_symbols_with_no_coverage():
    covered = aggregate("A", [score(0.8, ident=f"c{i}") for i in range(8)],
                        now=NOW)
    empty = aggregate("B", [], now=NOW)
    mood = market_mood([covered, empty])
    assert mood["symbols"] == 1
    assert mood["score"] == pytest.approx(covered.score, abs=0.01)


# ── ranking ──────────────────────────────────────────────────────────────
def q(**over) -> QuantMetrics:
    base = dict(
        symbol="TESTCO", name="Test", cap_bucket="large", mcap_cr=200_000.0,
        ltp=1_000.0, annual_vol=25.0, beta=1.0, max_drawdown_1y=20.0,
        adtv_cr=250.0, atr_pct=1.5, rsi14=55.0, sma20=980.0, sma50=960.0,
        sma200=900.0, dist_52w_high_pct=-5.0, asm_gsm_flag=False,
    )
    base.update(over)
    return QuantMetrics(**base)


def sentiment(score_: float, confidence: float) -> SymbolSentiment:
    return SymbolSentiment(
        symbol="TESTCO", as_of=NOW, score=score_, confidence=confidence,
        n_articles=6, top_events=["earnings"], drivers=[],
    )


def test_zero_confidence_zeroes_the_composite():
    assert ranker.composite(q(), sentiment(0.9, 0.0), Horizon.DAY) == 0.0


def test_confidence_scales_the_composite_linearly():
    full = ranker.composite(q(), sentiment(0.5, 1.0), Horizon.SWING)
    half = ranker.composite(q(), sentiment(0.5, 0.5), Horizon.SWING)
    assert half == pytest.approx(full / 2, rel=0.02)


def test_the_day_desk_weights_liquidity_more_than_the_long_desk():
    illiquid = q(adtv_cr=5.0)
    liquid = q(adtv_cr=500.0)
    s = sentiment(0.4, 1.0)
    day_gap = (ranker.composite(liquid, s, Horizon.DAY)
               - ranker.composite(illiquid, s, Horizon.DAY))
    long_gap = (ranker.composite(liquid, s, Horizon.LONG)
                - ranker.composite(illiquid, s, Horizon.LONG))
    assert day_gap > long_gap


def test_the_long_desk_rewards_a_shallower_drawdown():
    s = sentiment(0.3, 1.0)
    shallow = ranker.composite(q(max_drawdown_1y=10.0), s, Horizon.LONG)
    deep = ranker.composite(q(max_drawdown_1y=55.0), s, Horizon.LONG)
    assert shallow > deep


def test_drawdown_does_not_affect_the_day_desk():
    s = sentiment(0.3, 1.0)
    assert ranker.composite(q(max_drawdown_1y=10.0), s, Horizon.DAY) == (
        ranker.composite(q(max_drawdown_1y=55.0), s, Horizon.DAY)
    )


def test_every_horizon_weight_set_sums_to_one():
    for horizon, weights in ranker.WEIGHTS.items():
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9), horizon


def test_composite_stays_inside_zero_to_one_hundred():
    extreme = q(adtv_cr=1e6, annual_vol=500.0, rsi14=100.0, ltp=10_000.0)
    assert 0.0 <= ranker.composite(extreme, sentiment(1.0, 1.0), Horizon.DAY) <= 100.0


def test_neutral_news_scores_the_sentiment_component_at_fifty():
    assert ranker.sentiment_component(sentiment(0.0, 1.0)) == 50.0


def test_refusals_sort_below_tradeable_candidates():
    from core.contracts import Candidate, MandateVerdict, Reason

    def cand(symbol: str, score_: float, level: str) -> Candidate:
        reasons = (
            [Reason(code="R4", severity="block", text="t", metric="m",
                    value=1.0, threshold=1.0)]
            if level == "OUTSIDE_MANDATE"
            else []
        )
        return Candidate(
            symbol=symbol, horizon=Horizon.DAY, composite_score=score_,
            sentiment=sentiment(0.2, 0.8), quant=q(symbol=symbol),
            verdict=MandateVerdict(level=level, reasons=reasons),
        )

    ranked = ranker.rank([
        cand("REFUSED", 99.0, "OUTSIDE_MANDATE"),
        cand("OK", 40.0, "SUITABLE"),
        cand("WARN", 80.0, "STRETCH"),
    ])
    assert [c.symbol for c in ranked] == ["OK", "WARN", "REFUSED"]
