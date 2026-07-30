"""Shared contracts — the single source of truth across all three tracks.

Owned by Track 1. Frozen once pushed; changes require telling both other
devs in person.

Track 2 (trading) imports from here and adds nothing to it. Order/journal
models live in trading/models.py.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Horizon(str, Enum):
    DAY = "day"
    SWING = "swing"
    LONG = "long_term"


CapBucket = Literal["large", "mid", "small", "micro"]

EventType = Literal[
    "earnings",
    "order_win",
    "regulatory",
    "promoter_pledge",
    "fundraise",
    "litigation",
    "management_change",
    "analyst_view",
    "macro",
    "other",
]


# ── sentiment ────────────────────────────────────────────────────────────
class HeadlineScore(BaseModel):
    id: str
    symbol: str
    title: str
    source: str
    url: str
    published_at: datetime
    sentiment: float = Field(ge=-1, le=1)
    label: Literal["positive", "neutral", "negative"]
    event_type: EventType
    materiality: int = Field(ge=1, le=5)
    rationale: str
    model: str  # "gemma3:4b" | "gemma-3-27b-it" | "fallback"


class SymbolSentiment(BaseModel):
    symbol: str
    as_of: datetime
    score: float = Field(ge=-1, le=1)  # computed in Python, not by Gemma
    confidence: float = Field(ge=0, le=1)
    n_articles: int
    top_events: list[EventType] = Field(default_factory=list)
    drivers: list[HeadlineScore] = Field(default_factory=list)


# ── user ─────────────────────────────────────────────────────────────────
class RiskProfile(BaseModel):
    capital: float = Field(gt=0, description="₹ the user is putting in")
    horizons: list[Horizon]
    allowed_caps: list[CapBucket]
    max_drawdown_pct: float
    experience: Literal["new", "1-3y", "3y+"]
    day_trading: bool
    uses_leverage: bool

    # Gemma's read of the survey free text. Advisory: the deterministic rubric
    # in trading/allocation.py is authoritative and this may move the risk
    # band by at most one notch. See allocation.risk_band().
    trader_type: Horizon | None = None
    confidence: float = 0.0

    # Recurring inflow. 0 disables it. A SIP deploys on schedule regardless of
    # sentiment — sentiment chooses WHICH stocks, never WHETHER to invest,
    # because pausing a SIP is what destroys rupee-cost averaging.
    sip_amount: float = 0.0
    sip_frequency: Literal["none", "weekly", "monthly"] = "none"


# ── quant (deterministic) ────────────────────────────────────────────────
class QuantMetrics(BaseModel):
    symbol: str
    name: str
    cap_bucket: CapBucket
    mcap_cr: float
    ltp: float
    annual_vol: float          # %
    beta: float                # vs ^NSEI
    max_drawdown_1y: float     # %, positive number
    adtv_cr: float             # 30d avg daily traded value, ₹ crore
    atr_pct: float
    rsi14: float
    sma20: float
    sma50: float
    sma200: float
    dist_52w_high_pct: float
    asm_gsm_flag: bool

    # Recent realised move, used by the Track 2 lag guard. Optional so the
    # contract stays valid if Track 1 has not wired it yet — the guard
    # degrades to a no-op rather than blocking every entry.
    move_1d_pct: float | None = None
    move_5d_pct: float | None = None
    move_20d_pct: float | None = None


# ── mandate ──────────────────────────────────────────────────────────────
class Reason(BaseModel):
    code: str                                  # "R2"
    severity: Literal["block", "warn"]
    text: str
    metric: str
    value: float
    threshold: float


class MandateVerdict(BaseModel):
    level: Literal["SUITABLE", "STRETCH", "OUTSIDE_MANDATE"]
    reasons: list[Reason] = Field(default_factory=list)


# ── output ───────────────────────────────────────────────────────────────
class Candidate(BaseModel):
    symbol: str
    horizon: Horizon
    composite_score: float = Field(ge=0, le=100)
    sentiment: SymbolSentiment
    quant: QuantMetrics
    verdict: MandateVerdict
    explanation: str = ""
