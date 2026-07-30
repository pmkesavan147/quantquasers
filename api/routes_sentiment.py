"""Track 1's half of the API: the survey, the news read, and the candidates.

Track 2 owns `routes_trading.py`. The seam between them is `Candidate` — this
module produces them, `POST /api/orders/execute` consumes them, and neither
knows anything else about the other.

Every route here degrades instead of failing: no model becomes the keyword
fallback, no network becomes the disk cache and then committed fixtures. What
you never get is a fabricated number — provenance is reported on every payload.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.state import engine, profile as current_profile, set_profile
from core.contracts import Candidate, Horizon, RiskProfile
from gemma import client as gemma_client
from gemma.quiz import QUESTIONS, report_for, summarise, to_profile
from ingest.news import headlines_for
from selection.pipeline import build_candidates, score_symbol
from selection.sentiment import market_mood
from selection.universe import company_name, universe
from trading.allocation import explain

router = APIRouter(prefix="/api", tags=["sentiment"])

DEFAULT_SCAN_LIMIT = 8


def _profile_or_default(explicit: RiskProfile | None) -> RiskProfile:
    """The account's profile, an explicit one, or a documented default.

    The default exists so the sentiment screens work before onboarding — a judge
    landing on /insights first should see real headlines, not an error.
    """
    if explicit is not None:
        return explicit
    live = current_profile()
    if live is not None:
        return live
    return RiskProfile(
        capital=500_000.0,
        horizons=[Horizon.DAY, Horizon.SWING, Horizon.LONG],
        allowed_caps=["large", "mid", "small"],
        max_drawdown_pct=25.0,
        experience="1-3y",
        day_trading=True,
        uses_leverage=False,
    )


def _symbols(requested: list[str] | None, limit: int) -> list[str]:
    if requested:
        known = set(universe())
        unknown = [s.upper() for s in requested if s.upper() not in known]
        if unknown:
            raise HTTPException(
                404, f"not in data/universe.csv: {', '.join(unknown)}"
            )
        return [s.upper() for s in requested]
    return sorted(universe())[:limit]


# ── the survey ───────────────────────────────────────────────────────────
@router.get("/quiz")
def quiz() -> dict:
    """The questions, so the frontend never hard-codes them.

    Options carry backend enum values, which is what stopped the three tracks
    agreeing last time: the UI now sends `long_term`, never `years+`.
    """
    return {
        "questions": [q.model_dump(exclude_none=True) for q in QUESTIONS],
        "note": (
            "Structured answers drive a hand-written rubric. The two free-text "
            "answers are read by Gemma, which may move the risk band by one "
            "notch and only above 0.70 confidence."
        ),
    }


class QuizSubmission(BaseModel):
    answers: dict = Field(default_factory=dict)
    # False for the onboarding slider: score the answers, change nothing.
    create_account: bool = True
    use_gemma: bool = True
    include_report: bool = False


@router.post("/quiz/submit")
def submit_quiz(req: QuizSubmission) -> dict:
    """Answers in; profile, risk band, desk split and Gemma's read out.

    With `create_account` the engine is rebuilt on the new profile, which is the
    whole of onboarding in one call. Without it, nothing is mutated.
    """
    profile, gemma_read = to_profile(req.answers, use_gemma=req.use_gemma)
    payload = summarise(profile, gemma_read)

    if req.include_report:
        payload["report"] = report_for(profile, req.answers)

    if req.create_account:
        eng = set_profile(profile)
        payload["account"] = {
            **explain(profile),
            "desks": [eng.desk_state(n).model_dump() for n in eng.desks],
        }
        payload["created"] = True
    else:
        payload["created"] = False

    payload["model"] = gemma_client.status()
    return payload


class ReportRequest(BaseModel):
    answers: dict = Field(default_factory=dict)


@router.post("/persona/report")
def persona_report(req: ReportRequest) -> dict:
    """The prose read of the persona. Split from /quiz/submit because it is the
    slowest model call and the UI should not block onboarding on it."""
    profile = current_profile()
    if profile is None:
        profile, _ = to_profile(req.answers, use_gemma=False)
    return {
        "report": report_for(profile, req.answers),
        "model": gemma_client.last_model(),
    }


# ── the news read ────────────────────────────────────────────────────────
@router.get("/sentiment/market")
def market_sentiment(
    symbols: list[str] | None = Query(None),
    limit: int = Query(DEFAULT_SCAN_LIMIT, ge=1, le=40),
    offline: bool = Query(False, description="ignore the network, use cache"),
) -> dict:
    """Per-symbol sentiment plus one market-wide mood number.

    Weighting is Python (`selection/sentiment.py`); Gemma only ever saw one
    headline at a time and never the aggregate.
    """
    now = datetime.now()
    wanted = _symbols(symbols, limit)

    out = []
    aggregates = []
    origins: dict[str, int] = {}
    models: dict[str, int] = {}

    for symbol in wanted:
        sentiment, items = score_symbol(
            symbol, allow_network=not offline, now=now
        )
        aggregates.append(sentiment)
        for h in items:
            origins[h.origin] = origins.get(h.origin, 0) + 1
        for d in sentiment.drivers:
            models[d.model] = models.get(d.model, 0) + 1
        out.append(
            {
                "symbol": symbol,
                "name": company_name(symbol),
                "score": sentiment.score,
                "confidence": sentiment.confidence,
                "n_articles": sentiment.n_articles,
                "top_events": sentiment.top_events,
                "drivers": [d.model_dump(mode="json") for d in sentiment.drivers],
            }
        )

    return {
        "as_of": now.isoformat(timespec="seconds"),
        "mood": market_mood(aggregates),
        "symbols": out,
        "provenance": {"headline_source": origins, "models": models},
    }


@router.get("/sentiment/{symbol}")
def symbol_sentiment(symbol: str, offline: bool = Query(False)) -> dict:
    """One symbol, with every headline that fed the score and what scored it."""
    symbol = symbol.upper()
    if symbol not in universe():
        raise HTTPException(404, f"{symbol} is not in data/universe.csv")

    now = datetime.now()
    sentiment, items = score_symbol(symbol, allow_network=not offline, now=now)
    return {
        "symbol": symbol,
        "name": company_name(symbol),
        "sentiment": sentiment.model_dump(mode="json"),
        "headlines": [h.model_dump(mode="json") for h in items],
    }


# ── candidates: the seam with Track 2 ────────────────────────────────────
class CandidateRequest(BaseModel):
    horizon: Horizon
    symbols: list[str] | None = None
    limit: int = Field(DEFAULT_SCAN_LIMIT, ge=1, le=40)
    profile: RiskProfile | None = None      # None => the account's profile
    offline: bool = False
    explain: bool = True


@router.post("/candidates")
def candidates(req: CandidateRequest) -> dict:
    """Ranked candidates for one desk, refusals included.

    `OUTSIDE_MANDATE` rows are returned, not filtered — each carries the metric,
    the value and the threshold it crossed, and the UI strikes them through.
    Hiding them would hide the most defensible thing the system does.
    """
    profile = _profile_or_default(req.profile)
    ranked, report = build_candidates(
        profile,
        req.horizon,
        _symbols(req.symbols, req.limit),
        allow_network=not req.offline,
        explain=req.explain,
    )
    return {
        "horizon": req.horizon.value,
        "candidates": [c.model_dump(mode="json") for c in ranked],
        "report": report,
    }


@router.post("/candidates/to-desk")
def candidates_to_desk(req: CandidateRequest) -> dict:
    """Build candidates and hand them straight to the matching desk as
    *proposals* — the read-only half of Track 2. Nothing is placed here.

    This is the one-call demo of the whole system: news in, orders proposed out,
    every refusal visible on the way.
    """
    profile = _profile_or_default(req.profile)
    ranked, report = build_candidates(
        profile,
        req.horizon,
        _symbols(req.symbols, req.limit),
        allow_network=not req.offline,
        explain=req.explain,
    )

    desk_name = req.horizon.value
    eng = engine()
    if desk_name not in eng.desks:
        raise HTTPException(404, f"no desk '{desk_name}' on this engine")

    from trading.desks import propose_entries, propose_exits

    desk = eng.desks[desk_name]
    broker = eng.brokers[desk_name]
    now = datetime.now()
    tradeable = _tradeable(ranked)

    # Exits first, for the same reason the engine does it that way: freeing a
    # slot must be visible before anything competes for it.
    exits = propose_exits(
        desk, broker, {c.symbol: c.sentiment for c in tradeable}, eng.quotes, now
    )
    entries, skips = propose_entries(
        desk, tradeable, broker, eng.limits, eng.quotes, now,
        day_trading_allowed=profile.day_trading,
        exiting={o.symbol for o in exits},
    )
    return {
        "horizon": req.horizon.value,
        "candidates": [c.model_dump(mode="json") for c in ranked],
        "proposed_orders": [o.model_dump(mode="json") for o in exits + entries],
        "skipped": [{"symbol": s.symbol, "reason": s.reason} for s in skips],
        "refused": [
            {
                "symbol": c.symbol,
                "reasons": [r.model_dump() for r in c.verdict.reasons],
            }
            for c in ranked
            if c.verdict.level == "OUTSIDE_MANDATE"
        ],
        "report": report,
    }


def _tradeable(ranked: list[Candidate]) -> list[Candidate]:
    """Refusals never reach a desk. They are returned to the UI, not traded —
    the mandate is a control, not a suggestion."""
    return [c for c in ranked if c.verdict.level != "OUTSIDE_MANDATE"]


# ── introspection ────────────────────────────────────────────────────────
@router.get("/universe")
def traded_universe() -> dict:
    rows = universe()
    buckets: dict[str, int] = {}
    for r in rows.values():
        buckets[r.cap_bucket] = buckets.get(r.cap_bucket, 0) + 1
    return {
        "count": len(rows),
        "buckets": buckets,
        "symbols": [r.model_dump() for r in rows.values()],
        "note": (
            "Cap buckets approximate SEBI's rank-based classification using "
            "absolute market cap; 'micro' (< ₹500 crore) is our own extension, "
            "not an official SEBI bucket. ASM/GSM flags are a hand-maintained "
            "snapshot, not a live feed."
        ),
    }


@router.get("/gemma/status")
def gemma_status() -> dict:
    """Which backend is live, and how much is already cached. The UI shows this
    so nobody claims a model wrote something the keyword fallback wrote."""
    return gemma_client.status()


@router.get("/news/{symbol}")
def raw_news(symbol: str, offline: bool = Query(False)) -> dict:
    symbol = symbol.upper()
    items = headlines_for(
        symbol, company_name(symbol), allow_network=not offline
    )
    return {
        "symbol": symbol,
        "count": len(items),
        "headlines": [h.model_dump(mode="json") for h in items],
    }
