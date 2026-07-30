"""Headline scores in, one symbol-level score out — weighted in Python.

Gemma scores each headline in isolation. It never sees the set, so it cannot
decide what the set means; that arithmetic lives here where it is testable.

    weight     = materiality × exp(-age_days / 3)
    score      = Σ(weight × sentiment) / Σ(weight)
    confidence = min(1, n/8) × (1 - stdev(sentiment)/2) × model_trust

The confidence term is the honest part: thin coverage caps it, and headlines
that disagree with each other drag it down. `ranker.py` multiplies the composite
score by this, so a single breathless headline cannot produce a top pick.

`model_trust` is the addition to the original formula, and it exists because
without it the keyword fallback looked *more* confident than a real model: every
headline it cannot read scores exactly 0.0, the spread collapses to zero, and
`1 - stdev/2` returns 1. Rows scored by the fallback are therefore trusted half
as much, which is what "we could not reach a model" should look like on screen.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime

from core.contracts import EventType, HeadlineScore, SymbolSentiment

RECENCY_TAU_DAYS = 3.0
FULL_COVERAGE_ARTICLES = 8

# How much a headline scored by the deterministic keyword fallback counts
# towards confidence, relative to one a model actually read.
FALLBACK_TRUST = 0.5


def _age_days(published_at: datetime, now: datetime) -> float:
    # Mixed tz-aware and naive datetimes are guaranteed once RSS and fixtures
    # are both in play; normalise rather than crash on the subtraction.
    a, b = published_at, now
    if (a.tzinfo is None) != (b.tzinfo is None):
        a = a.replace(tzinfo=None)
        b = b.replace(tzinfo=None)
    return max(0.0, (b - a).total_seconds() / 86400)


def weight_of(score: HeadlineScore, now: datetime) -> float:
    return score.materiality * math.exp(-_age_days(score.published_at, now)
                                        / RECENCY_TAU_DAYS)


def aggregate(
    symbol: str, scores: list[HeadlineScore], *, now: datetime | None = None
) -> SymbolSentiment:
    now = now or datetime.now()

    if not scores:
        return SymbolSentiment(
            symbol=symbol.upper(), as_of=now, score=0.0, confidence=0.0,
            n_articles=0, top_events=[], drivers=[],
        )

    weights = [weight_of(s, now) for s in scores]
    total_w = sum(weights)
    score = (
        sum(w * s.sentiment for w, s in zip(weights, scores)) / total_w
        if total_w > 0
        else 0.0
    )

    sentiments = [s.sentiment for s in scores]
    spread = statistics.stdev(sentiments) if len(sentiments) > 1 else 0.0
    coverage = min(1.0, len(scores) / FULL_COVERAGE_ARTICLES)

    read_by_model = sum(1 for s in scores if s.model != "fallback")
    model_trust = FALLBACK_TRUST + (1 - FALLBACK_TRUST) * read_by_model / len(scores)

    confidence = max(0.0, min(1.0, coverage * (1 - spread / 2) * model_trust))

    # Events ranked by the weight behind them, not by raw count — one material
    # regulatory action outranks three analyst notes.
    event_weight: dict[EventType, float] = {}
    for w, s in zip(weights, scores):
        event_weight[s.event_type] = event_weight.get(s.event_type, 0.0) + w
    top_events = [
        e for e, _ in sorted(event_weight.items(), key=lambda kv: -kv[1])
    ][:3]

    drivers = sorted(
        scores, key=lambda s: -abs(s.sentiment) * weight_of(s, now)
    )[:3]

    return SymbolSentiment(
        symbol=symbol.upper(),
        as_of=now,
        score=round(max(-1.0, min(1.0, score)), 3),
        confidence=round(confidence, 3),
        n_articles=len(scores),
        top_events=top_events,
        drivers=drivers,
    )


def market_mood(sentiments: list[SymbolSentiment]) -> dict:
    """One number for the header strip: coverage-weighted mean across symbols.

    Weighting by confidence stops a symbol with one stale headline from moving
    the market-wide read.
    """
    usable = [s for s in sentiments if s.n_articles > 0]
    if not usable:
        return {"score": 0.0, "confidence": 0.0, "symbols": 0, "articles": 0}

    total_w = sum(s.confidence for s in usable) or float(len(usable))
    weighted = sum(s.score * (s.confidence or 1.0) for s in usable) / total_w
    return {
        "score": round(weighted, 3),
        "confidence": round(sum(s.confidence for s in usable) / len(usable), 3),
        "symbols": len(usable),
        "articles": sum(s.n_articles for s in usable),
    }
