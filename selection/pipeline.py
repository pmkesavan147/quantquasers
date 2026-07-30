"""News + prices + mandate → `Candidate[]`, which is exactly what Track 2 eats.

This is the seam between the tracks. `POST /api/orders/execute` already accepts
a `candidates` list, so the trading floor does not know or care whether these
came from here, from fixtures, or from a hand-written test.

Cost control matters because Gemma is the slow part:

* one model call per *headline*, cached on disk by prompt hash;
* one model call per *explanation*, and only for the top few per horizon —
  everything below that gets the templated string, which contains the same
  numbers.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core.contracts import (
    Candidate,
    Horizon,
    HeadlineScore,
    QuantMetrics,
    RiskProfile,
    SymbolSentiment,
)
from gemma.scorers import explain_candidate, score_headline
from ingest import snapshot
from ingest.news import Headline, headlines_for, source_mix
from selection import quant as quant_mod
from selection.mandate import evaluate
from selection.ranker import components, composite, rank
from selection.sentiment import aggregate, market_mood
from selection.universe import company_name, universe

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"

# How many candidates per horizon get a written explanation from Gemma. The
# rest get the deterministic template — same facts, no model latency.
EXPLAIN_TOP_N = 3

DEFAULT_UNIVERSE_LIMIT = 12


_fixture_quant: dict[str, QuantMetrics] | None = None


def fixture_quant() -> dict[str, QuantMetrics]:
    """QuantMetrics from the committed fixtures, keyed by symbol.

    Used when a symbol has no price history — a demerged ticker, a delisting, or
    no network on a cold cache. Better a labelled fixture than a fabricated
    number.
    """
    global _fixture_quant
    if _fixture_quant is None:
        out: dict[str, QuantMetrics] = {}
        for path in sorted(FIXTURES.glob("candidates_*.json")):
            try:
                for row in json.loads(path.read_text(encoding="utf-8")):
                    q = QuantMetrics.model_validate(row["quant"])
                    out.setdefault(q.symbol.upper(), q)
            except Exception:
                continue
        _fixture_quant = out
    return _fixture_quant


def score_symbol(
    symbol: str,
    *,
    allow_network: bool = True,
    now: datetime | None = None,
) -> tuple[SymbolSentiment, list[Headline]]:
    """Every headline for one symbol, scored one at a time, then aggregated."""
    now = now or datetime.now()
    items = headlines_for(
        symbol, company_name(symbol), allow_network=allow_network, now=now
    )

    scored: list[HeadlineScore] = [
        score_headline(
            h.title,
            company_name(symbol),
            symbol=symbol.upper(),
            id=h.id,
            source=h.source,
            url=h.url,
            published_at=h.published_at,
        )
        for h in items
    ]
    return aggregate(symbol, scored, now=now), items


def quant_for(
    symbol: str, *, allow_network: bool = True
) -> tuple[QuantMetrics | None, str]:
    """`(metrics, provenance)`: 'live' | 'snapshot' | 'fixture' | 'none'.

    A deployed instance serves metrics computed from real prices, but computed
    *earlier* — calling that "live" would be the exact dishonesty this field
    exists to prevent.
    """
    live = quant_mod.fetch(symbol, allow_network=allow_network)
    if live is not None:
        return live, "snapshot" if snapshot.enabled() else "live"
    fixture = fixture_quant().get(symbol.upper())
    if fixture is not None:
        return fixture, "fixture"
    return None, "none"


def build_candidates(
    profile: RiskProfile,
    horizon: Horizon,
    symbols: list[str] | None = None,
    *,
    allow_network: bool = True,
    explain: bool = True,
    now: datetime | None = None,
) -> tuple[list[Candidate], dict]:
    """Ranked candidates for one desk, plus a provenance report.

    The report is not decoration: it says which numbers were live, which came
    from fixtures, and which model scored the news. Demoing fixture data while
    claiming it is live is the one dishonesty this project cannot afford.
    """
    now = now or datetime.now()
    symbols = [s.upper() for s in (symbols or list(universe())[:DEFAULT_UNIVERSE_LIMIT])]

    candidates: list[Candidate] = []
    provenance = {"live": 0, "snapshot": 0, "fixture": 0, "none": 0}
    headline_origins: dict[str, int] = {}
    models: dict[str, int] = {}
    sentiments: list[SymbolSentiment] = []

    for symbol in symbols:
        sentiment, items = score_symbol(symbol, allow_network=allow_network, now=now)
        sentiments.append(sentiment)
        for origin, count in source_mix(items).items():
            headline_origins[origin] = headline_origins.get(origin, 0) + count
        for driver in sentiment.drivers:
            models[driver.model] = models.get(driver.model, 0) + 1

        metrics, where = quant_for(symbol, allow_network=allow_network)
        provenance[where] += 1
        if metrics is None:
            continue

        verdict = evaluate(metrics, profile, horizon)
        candidates.append(
            Candidate(
                symbol=symbol,
                horizon=horizon,
                composite_score=composite(metrics, sentiment, horizon),
                sentiment=sentiment,
                quant=metrics,
                verdict=verdict,
                explanation="",
            )
        )

    ranked = rank(candidates)

    for i, cand in enumerate(ranked):
        wants_model = explain and i < EXPLAIN_TOP_N
        cand.explanation = (
            explain_candidate(
                symbol=cand.symbol,
                horizon=cand.horizon.value,
                sentiment=cand.sentiment.score,
                n_articles=cand.sentiment.n_articles,
                confidence=cand.sentiment.confidence,
                events=[e for e in cand.sentiment.top_events],
                adtv_cr=cand.quant.adtv_cr,
                annual_vol=cand.quant.annual_vol,
                dist_52w_high_pct=cand.quant.dist_52w_high_pct,
                verdict=cand.verdict.level,
                reasons=[r.text for r in cand.verdict.reasons],
            )
            if wants_model
            else _template_explanation(cand)
        )

    report = {
        "horizon": horizon.value,
        "symbols_scanned": len(symbols),
        "candidates": len(ranked),
        "suitable": sum(1 for c in ranked if c.verdict.level == "SUITABLE"),
        "stretch": sum(1 for c in ranked if c.verdict.level == "STRETCH"),
        "refused": sum(1 for c in ranked if c.verdict.level == "OUTSIDE_MANDATE"),
        "quant_source": provenance,
        "headline_source": headline_origins,
        "headline_models": models,
        "market_mood": market_mood(sentiments),
        "as_of": now.isoformat(timespec="seconds"),
    }
    return ranked, report


def _template_explanation(c: Candidate) -> str:
    verdict_line = {
        "SUITABLE": "Fits the mandate.",
        "STRETCH": "Inside the mandate but stretching it.",
        "OUTSIDE_MANDATE": "Refused — outside the mandate.",
    }.get(c.verdict.level, c.verdict.level)
    first = f" {c.verdict.reasons[0].text}" if c.verdict.reasons else ""
    return (
        f"Sentiment {c.sentiment.score:+.2f} across {c.sentiment.n_articles} "
        f"article(s) at {c.sentiment.confidence:.0%} confidence; liquidity "
        f"₹{c.quant.adtv_cr:,.1f} crore, volatility {c.quant.annual_vol:.1f}%. "
        f"{verdict_line}{first}"
    )


def scoreboard(
    profile: RiskProfile,
    horizons: list[Horizon] | None = None,
    *,
    symbols: list[str] | None = None,
    allow_network: bool = True,
    explain: bool = True,
    now: datetime | None = None,
) -> dict[str, dict]:
    """`build_candidates` across several desks in one pass.

    Sentiment work is cached by prompt hash, so the second and third horizon are
    nearly free — the same headline is not re-scored per desk.
    """
    horizons = horizons or [Horizon.DAY, Horizon.SWING, Horizon.LONG]
    out: dict[str, dict] = {}
    for horizon in horizons:
        ranked, report = build_candidates(
            profile, horizon, symbols,
            allow_network=allow_network, explain=explain, now=now,
        )
        out[horizon.value] = {"candidates": ranked, "report": report}
    return out
