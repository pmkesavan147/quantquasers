"""Composite score per horizon. Deterministic weights, no model involvement.

Each component is normalised to 0–100, weighted per horizon, summed, then
multiplied by `sentiment.confidence` — so a name with one thin headline cannot
outrank a name with corroborated coverage no matter how loud that headline was.

| Component            | Day  | Swing | Long |
|----------------------|------|-------|------|
| Sentiment            | 0.40 | 0.35  | 0.20 |
| Momentum (RSI + SMA) | 0.20 | 0.35  | 0.15 |
| Liquidity (ADTV)     | 0.30 | 0.10  | 0.05 |
| Volatility           | 0.10 | 0.10  | —    |
| Trend (vs SMA200)    | —    | 0.10  | 0.35 |
| Drawdown (lower ok)  | —    | —     | 0.25 |

`OUTSIDE_MANDATE` candidates are scored and returned like any other. The UI
strikes them through and shows the reason; silently dropping them would hide
the most interesting thing the system does.
"""

from __future__ import annotations

from core.contracts import Candidate, Horizon, QuantMetrics, SymbolSentiment

WEIGHTS: dict[Horizon, dict[str, float]] = {
    Horizon.DAY: {"sentiment": 0.40, "momentum": 0.20, "liquidity": 0.30,
                  "volatility": 0.10, "trend": 0.0, "drawdown": 0.0},
    Horizon.SWING: {"sentiment": 0.35, "momentum": 0.35, "liquidity": 0.10,
                    "volatility": 0.10, "trend": 0.10, "drawdown": 0.0},
    Horizon.LONG: {"sentiment": 0.20, "momentum": 0.15, "liquidity": 0.05,
                   "volatility": 0.0, "trend": 0.35, "drawdown": 0.25},
}

# ₹ crore of average daily traded value that counts as "fully liquid" for
# scoring. Above this, more liquidity stops being an advantage.
LIQUIDITY_SATURATION_CR = 500.0
VOL_SATURATION_PCT = 60.0
DRAWDOWN_SATURATION_PCT = 60.0


def _clamp100(v: float) -> float:
    return max(0.0, min(100.0, v))


def sentiment_component(s: SymbolSentiment) -> float:
    """-1..1 mapped to 0..100. Neutral news is a 50, not a zero."""
    return _clamp100((s.score + 1.0) * 50.0)


def momentum_component(q: QuantMetrics) -> float:
    """RSI plus how far price sits above its 20- and 50-day averages.

    RSI is used as a position, not a signal: 50 is neutral, and the extremes
    are left to the sentiment gates in `trading/sentiment_rules.py` to judge.
    """
    rsi = _clamp100(q.rsi14)
    above_20 = 50.0 + (q.ltp / q.sma20 - 1.0) * 500 if q.sma20 else 50.0
    above_50 = 50.0 + (q.ltp / q.sma50 - 1.0) * 250 if q.sma50 else 50.0
    return _clamp100(0.4 * rsi + 0.3 * _clamp100(above_20) + 0.3 * _clamp100(above_50))


def liquidity_component(q: QuantMetrics) -> float:
    return _clamp100(q.adtv_cr / LIQUIDITY_SATURATION_CR * 100)


def volatility_component(q: QuantMetrics) -> float:
    """Higher is better here — a day desk needs range to work with."""
    return _clamp100(q.annual_vol / VOL_SATURATION_PCT * 100)


def trend_component(q: QuantMetrics) -> float:
    if not q.sma200:
        return 50.0
    return _clamp100(50.0 + (q.ltp / q.sma200 - 1.0) * 200)


def drawdown_component(q: QuantMetrics) -> float:
    """Lower drawdown scores higher — this is the only inverted component."""
    return _clamp100(100.0 - q.max_drawdown_1y / DRAWDOWN_SATURATION_PCT * 100)


def components(q: QuantMetrics, s: SymbolSentiment) -> dict[str, float]:
    return {
        "sentiment": round(sentiment_component(s), 1),
        "momentum": round(momentum_component(q), 1),
        "liquidity": round(liquidity_component(q), 1),
        "volatility": round(volatility_component(q), 1),
        "trend": round(trend_component(q), 1),
        "drawdown": round(drawdown_component(q), 1),
    }


def composite(q: QuantMetrics, s: SymbolSentiment, horizon: Horizon) -> float:
    """0–100. Scaled by sentiment confidence, so thin coverage cannot win."""
    parts = components(q, s)
    weights = WEIGHTS[horizon]
    raw = sum(parts[name] * w for name, w in weights.items())
    return round(_clamp100(raw * s.confidence), 2)


def rank(candidates: list[Candidate]) -> list[Candidate]:
    """Highest score first, with refusals last among equals.

    Sorting refusals down keeps the top of the list actionable while still
    returning every one of them.
    """
    order = {"SUITABLE": 0, "STRETCH": 1, "OUTSIDE_MANDATE": 2}
    return sorted(
        candidates,
        key=lambda c: (order.get(c.verdict.level, 3), -c.composite_score),
    )
