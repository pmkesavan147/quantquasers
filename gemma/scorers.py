"""The three things Gemma is allowed to do: classify a headline, read a survey's
free text, and write prose.

Every function here has a deterministic fallback that produces a valid contract
object. A model failing is a quality regression, never an outage — and the
`model` field records which one you got.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.contracts import EventType, HeadlineScore, Horizon
from gemma.client import extract_json, generate, last_model

# ── headline classification ──────────────────────────────────────────────
CLASSIFIER_SYSTEM = (
    "You are a financial news classifier for Indian equities. Judge only the "
    "headline you are given. Do not speculate about price, do not give advice, "
    "and do not invent facts that are not in the headline."
)

EVENT_TYPES: tuple[str, ...] = (
    "earnings", "order_win", "regulatory", "promoter_pledge", "fundraise",
    "litigation", "management_change", "analyst_view", "macro", "other",
)


class _HeadlineOut(BaseModel):
    """The four fields Gemma returns. Everything else is computed here."""

    sentiment: float = Field(ge=-1, le=1)
    event_type: str
    materiality: int = Field(ge=1, le=5)
    rationale: str


HEADLINE_PROMPT = """Headline: "{title}"
Company: {company} (NSE-listed)

Classify it for this company's shareholders.

sentiment   -1.0 (very bad for the company) to 1.0 (very good)
event_type  one of: {events}
materiality 1 (noise) to 5 (moves the business)
rationale   one short clause, under 15 words, quoting only the headline
"""


def _label(sentiment: float) -> Literal["positive", "neutral", "negative"]:
    if sentiment >= 0.15:
        return "positive"
    if sentiment <= -0.15:
        return "negative"
    return "neutral"


# Used only when no model answers. Deliberately crude and deliberately visible:
# rows scored this way carry model="fallback" and the UI says so.
_POSITIVE = {
    "beats": 0.5, "beat": 0.5, "profit jumps": 0.6, "record": 0.45, "wins": 0.5,
    "bags": 0.5, "order win": 0.55, "approval": 0.4, "approved": 0.4,
    "upgrade": 0.45, "raises guidance": 0.6, "expansion": 0.35, "surges": 0.4,
    "dividend": 0.3, "buyback": 0.35, "partnership": 0.3, "acquires": 0.25,
}
_NEGATIVE = {
    "sebi": -0.4, "penalty": -0.55, "fine": -0.45, "probe": -0.5, "raid": -0.6,
    "downgrade": -0.5, "misses": -0.45, "miss": -0.4, "loss": -0.45,
    "fraud": -0.7, "resigns": -0.4, "pledge": -0.4, "recall": -0.45,
    "strike": -0.35, "ban": -0.55, "litigation": -0.4, "insolvency": -0.7,
    "slumps": -0.45, "plunges": -0.5, "cuts guidance": -0.6,
}
_EVENT_HINTS: dict[str, EventType] = {
    "profit": "earnings", "revenue": "earnings", "q1": "earnings",
    "q2": "earnings", "q3": "earnings", "q4": "earnings", "results": "earnings",
    "order": "order_win", "contract": "order_win", "sebi": "regulatory",
    "rbi": "regulatory", "regulator": "regulatory", "pledge": "promoter_pledge",
    "qip": "fundraise", "fundrais": "fundraise", "rights issue": "fundraise",
    "court": "litigation", "tribunal": "litigation", "lawsuit": "litigation",
    "ceo": "management_change", "cfo": "management_change",
    "resign": "management_change", "brokerage": "analyst_view",
    "target price": "analyst_view", "rating": "analyst_view",
    "inflation": "macro", "gdp": "macro", "rate": "macro", "crude": "macro",
}


def _fallback_headline(title: str) -> _HeadlineOut:
    low = title.lower()
    hits = [w for w in _POSITIVE if w in low] + [w for w in _NEGATIVE if w in low]
    score = sum(_POSITIVE.get(w, 0.0) + _NEGATIVE.get(w, 0.0) for w in hits)
    score = max(-1.0, min(1.0, score))

    event: EventType = "other"
    for hint, ev in _EVENT_HINTS.items():
        if hint in low:
            event = ev
            break

    return _HeadlineOut(
        sentiment=round(score, 2),
        event_type=event,
        # Materiality tracks how much evidence there was, so a keyword-free
        # headline cannot masquerade as a market-moving event.
        materiality=min(5, 1 + len(hits)),
        rationale="Keyword fallback — no model available.",
    )


def score_headline(
    title: str,
    company: str,
    *,
    symbol: str,
    id: str,
    source: str = "",
    url: str = "",
    published_at: datetime | None = None,
) -> HeadlineScore:
    """One headline per call. A small model batching JSON degrades sharply."""
    raw = generate(
        HEADLINE_PROMPT.format(
            title=title, company=company, events=", ".join(EVENT_TYPES)
        ),
        schema=_HeadlineOut,
        system=CLASSIFIER_SYSTEM,
        temperature=0.0,
    )

    model = last_model()
    try:
        out = _HeadlineOut.model_validate(extract_json(raw))
        if out.event_type not in EVENT_TYPES:
            out.event_type = "other"
    except Exception:
        out, model = _fallback_headline(title), "fallback"

    return HeadlineScore(
        id=id,
        symbol=symbol,
        title=title,
        source=source,
        url=url,
        published_at=published_at or datetime.now(),
        sentiment=max(-1.0, min(1.0, out.sentiment)),
        label=_label(out.sentiment),
        event_type=out.event_type,  # type: ignore[arg-type]
        materiality=max(1, min(5, out.materiality)),
        rationale=out.rationale.strip()[:200],
        model=model,
    )


# ── user profiling ───────────────────────────────────────────────────────
PROFILER_SYSTEM = (
    "You read an investor's own words and name their trading horizon. You are a "
    "second opinion: a hand-written rubric has already scored them, and it wins "
    "any disagreement. Never recommend allocations, products or trades."
)


class _ProfileOut(BaseModel):
    trader_type: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str


PROFILE_PROMPT = """A rubric over this investor's structured answers scored them
{rubric_score}/11 ({rubric_band}), where 0 is very conservative and 11 is very
aggressive.

Structured answers: {mcq}

Their own words —
On the market right now: "{outlook}"
On what success looks like: "{goal}"

trader_type  one of: day, swing, long_term
confidence   0.0 to 1.0 — how strongly THEIR WORDS support that horizon.
             Use below 0.7 if their words are vague, empty, or contradict the
             rubric band above.
reasoning    one sentence, quoting their words
"""


def profile_user(
    *,
    rubric_score: int,
    rubric_band: str,
    mcq: dict,
    outlook: str = "",
    goal: str = "",
) -> tuple[Horizon | None, float, str]:
    """Gemma's read of the free text: `(trader_type, confidence, reasoning)`.

    Advisory by contract. `trading.allocation.risk_band()` moves the band by at
    most one notch and only above a 0.70 confidence floor, so a confident wrong
    answer here cannot rewrite someone's portfolio.

    Returns `(None, 0.0, ...)` when there is nothing to read — no free text
    means no second opinion, not a guess.
    """
    if not outlook.strip() and not goal.strip():
        return None, 0.0, "No free text given — rubric used alone."

    raw = generate(
        PROFILE_PROMPT.format(
            rubric_score=rubric_score, rubric_band=rubric_band, mcq=mcq,
            outlook=outlook.strip()[:600] or "(not answered)",
            goal=goal.strip()[:600] or "(not answered)",
        ),
        schema=_ProfileOut,
        system=PROFILER_SYSTEM,
        temperature=0.0,
    )

    try:
        out = _ProfileOut.model_validate(extract_json(raw))
        horizon = Horizon(out.trader_type.strip().lower())
    except Exception:
        return None, 0.0, "Model unavailable or unparseable — rubric used alone."

    confidence = max(0.0, min(1.0, out.confidence))
    return horizon, confidence, out.reasoning.strip()[:280]


# ── prose ────────────────────────────────────────────────────────────────
EXPLAINER_SYSTEM = (
    "You explain a stock screening result in plain English for a retail "
    "investor in India. Copy the numbers you are given verbatim; never compute "
    "or estimate one. No price targets. No buy, sell or hold language."
)

EXPLAIN_PROMPT = """Symbol: {symbol}
Horizon: {horizon}
Sentiment score: {sentiment} from {n_articles} article(s), confidence {confidence}
Recent events: {events}
Liquidity (30d avg daily traded value): {adtv}
Annualised volatility: {vol}
Distance from 52-week high: {dist}
Mandate verdict: {verdict}{reasons}

Write at most 3 sentences: what the news says, what the numbers say, and what
the mandate verdict means for this investor. If the verdict is OUTSIDE_MANDATE,
lead with the refusal.
"""


def explain_candidate(
    *,
    symbol: str,
    horizon: str,
    sentiment: float,
    n_articles: int,
    confidence: float,
    events: list[str],
    adtv_cr: float,
    annual_vol: float,
    dist_52w_high_pct: float,
    verdict: str,
    reasons: list[str],
) -> str:
    """Numbers arrive pre-formatted as strings so the model copies, not counts."""
    reason_text = ("\nReasons: " + "; ".join(reasons)) if reasons else ""
    raw = generate(
        EXPLAIN_PROMPT.format(
            symbol=symbol,
            horizon=horizon,
            sentiment=f"{sentiment:+.2f}",
            n_articles=n_articles,
            confidence=f"{confidence:.0%}",
            events=", ".join(events) or "none tagged",
            adtv=f"₹{adtv_cr:,.1f} crore",
            vol=f"{annual_vol:.1f}%",
            dist=f"{dist_52w_high_pct:.1f}%",
            verdict=verdict,
            reasons=reason_text,
        ),
        system=EXPLAINER_SYSTEM,
        temperature=0.2,
    )
    if raw:
        return raw.strip()[:600]

    # Templated fallback: the same facts, no prose. Numbers still come from
    # Python, so nothing on screen becomes less true when the model is down.
    verdict_line = {
        "SUITABLE": "Fits the mandate.",
        "STRETCH": "Inside the mandate but stretching it.",
        "OUTSIDE_MANDATE": "Refused — outside the mandate.",
    }.get(verdict, verdict)
    return (
        f"{symbol}: sentiment {sentiment:+.2f} across {n_articles} article(s) "
        f"({confidence:.0%} confidence). Liquidity ₹{adtv_cr:,.1f} crore, "
        f"volatility {annual_vol:.1f}%, {dist_52w_high_pct:.1f}% from the 52-week "
        f"high. {verdict_line}"
        + (f" {reasons[0]}" if reasons else "")
    )


REPORT_SYSTEM = (
    "You write a short, friendly investor-personality note. Plain paragraphs, "
    "no markdown, no bullet points, no percentages, no product or trade "
    "recommendations."
)

REPORT_PROMPT = """Horizon band: {band}
Rubric score: {rubric_score}/11
Their words on the market: "{outlook}"
Their words on success: "{goal}"

Under 180 words: what this style means, one strength, one blind spot to watch,
one practical habit. End with one line stating this is not investment advice.
"""


def personality_report(
    *, band: str, rubric_score: int, outlook: str = "", goal: str = ""
) -> str:
    raw = generate(
        REPORT_PROMPT.format(
            band=band, rubric_score=rubric_score,
            outlook=outlook.strip()[:600] or "(not answered)",
            goal=goal.strip()[:600] or "(not answered)",
        ),
        system=REPORT_SYSTEM,
        temperature=0.4,
    )
    if raw:
        return raw.strip()

    return (
        f"Your answers put you in the {band} band ({rubric_score}/11 on our "
        "rubric). That band sets how much of your capital each desk may use — "
        "intraday gets the smallest share in the conservative band and the "
        "largest in the aggressive one. Your strength is having stated a "
        "drawdown you can live with, which is the number most people skip. The "
        "blind spot to watch is acting on a headline before checking whether "
        "the move already happened. A practical habit: read the refusal "
        "reasons, not just the picks. This is educational analysis, not "
        "investment advice."
    )
