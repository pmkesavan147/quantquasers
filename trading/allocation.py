"""Capital allocation across desks — derived from the user's risk band.

Desk allocations are NOT static config. The user declares their capital and
their appetite at account creation, and the split across day / swing /
long-term follows from it. Opting out of intraday removes the day desk and
the remaining desks renormalise to absorb its share.

Everything here is a pure function of the RiskProfile: same profile in, same
allocation out, every time. An LLM must never set an equity allocation, so
the band comes from a hand-written rubric over the user's own declared
answers. Gemma's read of their free text may move the band by at most one
notch, and only when it is confident.
"""

from __future__ import annotations

import dataclasses
from typing import Literal

from core.contracts import Horizon, RiskProfile
from trading.config import DeskConfig

RiskBand = Literal["conservative", "balanced", "aggressive"]

BANDS: tuple[RiskBand, ...] = ("conservative", "balanced", "aggressive")

# Base weights per band, before eligibility filtering. Renormalised over
# whichever desks the user actually enabled, so 3-mode, 2-mode and long-only
# all flow through one code path.
BASE_WEIGHTS: dict[RiskBand, dict[str, float]] = {
    "conservative": {"day": 5.0, "swing": 20.0, "long_term": 75.0},
    "balanced":     {"day": 15.0, "swing": 30.0, "long_term": 55.0},
    "aggressive":   {"day": 30.0, "swing": 35.0, "long_term": 35.0},
}

# Gemma's read only counts above this. Below it, the rubric stands alone.
GEMMA_CONFIDENCE_FLOOR = 0.70

DESK_FOR_HORIZON = {
    Horizon.DAY: "day",
    Horizon.SWING: "swing",
    Horizon.LONG: "long_term",
}


# ── the rubric ───────────────────────────────────────────────────────────
def rubric_score(p: RiskProfile) -> int:
    """0..11. Built only from what the user explicitly declared."""
    score = 0

    # Drawdown tolerance is the single most informative answer: it is the one
    # question phrased in money the user could actually lose.
    if p.max_drawdown_pct >= 35:
        score += 3
    elif p.max_drawdown_pct >= 25:
        score += 2
    elif p.max_drawdown_pct >= 15:
        score += 1

    score += {"new": 0, "1-3y": 1, "3y+": 2}[p.experience]

    if p.day_trading:
        score += 1
    if p.uses_leverage:
        score += 1

    # Willingness to hold illiquid names is an appetite signal in itself.
    if "micro" in p.allowed_caps:
        score += 2
    elif "small" in p.allowed_caps:
        score += 1

    if Horizon.DAY in p.horizons:
        score += 1
    elif p.horizons == [Horizon.LONG]:
        score -= 1

    return max(0, score)


def _band_from_score(score: int) -> RiskBand:
    if score <= 3:
        return "conservative"
    if score <= 7:
        return "balanced"
    return "aggressive"


def risk_band(p: RiskProfile) -> RiskBand:
    """The rubric decides. Gemma may nudge it one notch, no further."""
    band = _band_from_score(rubric_score(p))

    if p.trader_type is not None and p.confidence >= GEMMA_CONFIDENCE_FLOOR:
        i = BANDS.index(band)
        if p.trader_type == Horizon.DAY:
            i = min(i + 1, len(BANDS) - 1)
        elif p.trader_type == Horizon.LONG:
            i = max(i - 1, 0)
        band = BANDS[i]

    return band


# ── the allocation ───────────────────────────────────────────────────────
def eligible_desks(p: RiskProfile) -> list[str]:
    """Which desks this user gets at all.

    The day desk requires BOTH an intraday horizon and the day_trading flag —
    opting out of intraday must remove the desk, not merely starve it.
    """
    names = [
        DESK_FOR_HORIZON[h] for h in p.horizons if h in DESK_FOR_HORIZON
    ]
    if not p.day_trading and "day" in names:
        names.remove("day")

    # A profile with no usable horizon still needs somewhere to put money.
    return names or ["long_term"]


def allocate(p: RiskProfile) -> dict[str, float]:
    """Percentages that sum to exactly 100 across the user's eligible desks."""
    band = risk_band(p)
    names = eligible_desks(p)

    weights = {n: BASE_WEIGHTS[band][n] for n in names}
    total = sum(weights.values())
    if total <= 0:  # unreachable with the tables above, but don't divide by 0
        share = round(100 / len(names), 2)
        weights = {n: share for n in names}
        total = sum(weights.values())

    out = {n: round(w / total * 100, 2) for n, w in weights.items()}

    # Put the rounding residue on the largest desk so the total is exactly 100.
    residue = round(100 - sum(out.values()), 2)
    if residue:
        biggest = max(out, key=lambda n: out[n])
        out[biggest] = round(out[biggest] + residue, 2)

    return out


def rupees(p: RiskProfile) -> dict[str, float]:
    """The allocation in money, which is what the user actually understands."""
    return {
        name: round(p.capital * pct / 100, 2)
        for name, pct in allocate(p).items()
    }


def apply_to_desks(
    desks: dict[str, DeskConfig], p: RiskProfile
) -> dict[str, DeskConfig]:
    """Rewrite desk configs for this profile.

    Ineligible desks are returned disabled at 0% rather than deleted, so the
    UI can still show "day desk — off, you opted out of intraday" instead of
    silently dropping a desk the user might expect to see.
    """
    pcts = allocate(p)
    out: dict[str, DeskConfig] = {}
    for name, cfg in desks.items():
        out[name] = dataclasses.replace(
            cfg,
            allocation_pct=pcts.get(name, 0.0),
            enabled=name in pcts and cfg.enabled,
        )
    return out


def explain(p: RiskProfile) -> dict:
    """Everything the onboarding screen needs to justify the split."""
    band = risk_band(p)
    pcts, money = allocate(p), rupees(p)
    return {
        "capital": p.capital,
        "risk_band": band,
        "rubric_score": rubric_score(p),
        "gemma_read": p.trader_type.value if p.trader_type else None,
        "gemma_confidence": p.confidence,
        "gemma_applied": (
            p.trader_type is not None and p.confidence >= GEMMA_CONFIDENCE_FLOOR
        ),
        "desks_enabled": sorted(pcts),
        "desks_off": sorted(set(BASE_WEIGHTS[band]) - set(pcts)),
        "allocation_pct": pcts,
        "allocation_rupees": money,
        "sip": {
            "amount": p.sip_amount,
            "frequency": p.sip_frequency,
            "target_desk": "long_term" if p.sip_amount > 0 else None,
            "note": (
                "A SIP deploys on schedule regardless of sentiment. Sentiment "
                "selects which stocks it buys, never whether it invests."
            ),
        },
    }
