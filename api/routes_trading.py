"""Track 2's half of the API. Track 1 owns routes_sentiment.py.

Route names and shapes are the frozen contract from the track docs — do not
rename these without telling Track 3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.state import engine, fixture_candidates, quote_backend, set_profile
from api.state import profile as current_profile
from core.contracts import Candidate, Horizon, RiskProfile
from trading.allocation import explain, risk_band
from trading.desks import propose_entries, propose_exits
from trading.execution.gate import gate_armed, resolve_mode
from trading.execution.kite import kite_status
from trading.models import DeskState, Fill, PortfolioState, ProposedOrder

router = APIRouter(prefix="/api", tags=["trading"])

DEFAULT_CAPITAL = 500_000.0


# ── account creation ─────────────────────────────────────────────────────
class AccountRequest(BaseModel):
    """What the onboarding wizard collects. Capital is the only hard
    requirement; everything else has a sane default."""

    capital: float = Field(DEFAULT_CAPITAL, gt=0,
                           description="₹ the user is putting in")
    horizons: list[Horizon] = Field(
        default_factory=lambda: [Horizon.DAY, Horizon.SWING, Horizon.LONG]
    )
    day_trading: bool = True
    uses_leverage: bool = False
    allowed_caps: list[str] = Field(
        default_factory=lambda: ["large", "mid", "small"]
    )
    max_drawdown_pct: float = Field(25.0, gt=0, le=100)
    experience: Literal["new", "1-3y", "3y+"] = "1-3y"

    # Gemma's read of the survey free text. Advisory — moves the band one
    # notch at most, and only above the confidence floor.
    trader_type: Horizon | None = None
    confidence: float = Field(0.0, ge=0, le=1)

    sip_amount: float = Field(0.0, ge=0)
    sip_frequency: Literal["none", "weekly", "monthly"] = "none"

    def to_profile(self) -> RiskProfile:
        return RiskProfile(
            capital=self.capital,
            horizons=self.horizons,
            allowed_caps=self.allowed_caps,
            max_drawdown_pct=self.max_drawdown_pct,
            experience=self.experience,
            day_trading=self.day_trading,
            uses_leverage=self.uses_leverage,
            trader_type=self.trader_type,
            confidence=self.confidence,
            sip_amount=self.sip_amount,
            sip_frequency=self.sip_frequency,
        )


@router.post("/account")
def create_account(req: AccountRequest) -> dict:
    """Create the account and derive the desk split from the risk band.

    Capital is the user's declared number and overrides the env default.
    Opting out of intraday removes the day desk entirely; the remaining desks
    renormalise to absorb its share.
    """
    if req.sip_amount > 0 and req.sip_frequency == "none":
        raise HTTPException(
            422, "sip_amount > 0 requires sip_frequency of 'weekly' or 'monthly'"
        )

    profile = req.to_profile()
    eng = set_profile(profile)
    return {
        **explain(profile),
        "desks": [eng.desk_state(n).model_dump() for n in eng.desks],
    }


@router.get("/account")
def get_account() -> dict:
    """The current profile and its allocation, or defaults if none is set."""
    p = current_profile()
    if p is None:
        return {
            "configured": False,
            "default_capital": DEFAULT_CAPITAL,
            "note": "POST /api/account to set capital and derive the desk split",
        }
    return {"configured": True, "profile": p.model_dump(mode="json"),
            **explain(p)}


@router.post("/account/preview")
def preview_account(req: AccountRequest) -> dict:
    """What the split WOULD be. Changes nothing — for the onboarding slider,
    so the user sees the allocation move as they answer."""
    return explain(req.to_profile())


# ── request bodies ───────────────────────────────────────────────────────
class DeskRequest(BaseModel):
    desk: str
    candidates: list[Candidate] | None = None   # None => use fixtures
    # None => take it from the account's profile. An explicit value overrides.
    day_trading_allowed: bool | None = None
    at: datetime | None = None                  # pretend it is this time


class RunResponse(BaseModel):
    desk: str
    mode: str
    fills: list[Fill]
    vetoed: list[dict]
    resized: list[dict]
    skipped: list[dict]
    errors: list[dict]


def _candidates_for(req: DeskRequest, horizon: str, now: datetime) -> list[Candidate]:
    if req.candidates is not None:
        return req.candidates
    return fixture_candidates(now).get(horizon, [])


def _desk_or_404(name: str):
    eng = engine()
    if name not in eng.desks:
        raise HTTPException(404, f"unknown desk '{name}' — have {list(eng.desks)}")
    return eng, eng.desks[name]


# ── orders ───────────────────────────────────────────────────────────────
@router.post("/orders/propose", response_model=list[ProposedOrder])
def propose(req: DeskRequest) -> list[ProposedOrder]:
    """What the desk WOULD do. Reads only — nothing is placed, nothing is
    journaled. Safe to poll from the UI."""
    eng, desk = _desk_or_404(req.desk)
    now = req.at or datetime.now()
    cands = _candidates_for(req, desk.horizon.value, now)
    broker = eng.brokers[desk.name]

    allowed = req.day_trading_allowed
    if allowed is None:
        allowed = eng.profile.day_trading if eng.profile is not None else True

    sentiments = {c.symbol: c.sentiment for c in cands}
    exits = propose_exits(desk, broker, sentiments, eng.quotes, now)
    entries, _skips = propose_entries(
        desk, cands, broker, eng.limits, eng.quotes, now,
        day_trading_allowed=allowed,
        exiting={o.symbol for o in exits},
    )
    return exits + entries


@router.post("/orders/execute", response_model=RunResponse)
def execute(req: DeskRequest) -> RunResponse:
    """Runs the desk for real. Paper unless all three gate locks are open —
    and they are not."""
    eng, desk = _desk_or_404(req.desk)
    now = req.at or datetime.now()
    cands = _candidates_for(req, desk.horizon.value, now)

    run = eng.run_desk(
        desk.name, cands, now=now,
        day_trading_allowed=req.day_trading_allowed,
    )
    return RunResponse(
        desk=desk.name,
        mode=eng.mode,
        fills=run.fills,
        vetoed=[{"symbol": s, "rule": r} for s, r in run.vetoed],
        resized=[{"symbol": s, "rule": r} for s, r in run.resized],
        skipped=[{"symbol": s.symbol, "reason": s.reason} for s in run.skips],
        errors=[{"symbol": s, "error": e} for s, e in run.errors],
    )


# ── reads ────────────────────────────────────────────────────────────────
@router.get("/desks", response_model=list[DeskState])
def desks() -> list[DeskState]:
    eng = engine()
    return [eng.desk_state(n) for n in eng.desks]


@router.get("/portfolio", response_model=PortfolioState)
def portfolio() -> PortfolioState:
    return engine().portfolio()


@router.get("/journal")
def journal(
    kind: str | None = Query(None, description="proposal|verdict|fill|alert|skip|note"),
    limit: int = Query(50, ge=1, le=1000),
) -> list[dict]:
    """The audit trail. Reverse-chronological."""
    return engine().journal.recent(limit, kind=kind)


# ── control ──────────────────────────────────────────────────────────────
@router.post("/control/pause")
def pause(reason: str = "manual pause") -> dict:
    eng = engine()
    eng.risk.halt(reason)
    return {"halted": True, "reason": eng.risk.halt_reason}


@router.post("/control/resume")
def resume() -> dict:
    eng = engine()
    eng.risk.resume()
    return {"halted": False, "reason": None}


@router.get("/health")
def health() -> dict:
    eng = engine()
    mode, reasons = resolve_mode()
    p = current_profile()
    return {
        "db": True,
        "account_configured": p is not None,
        "capital": eng.limits.max_capital,
        "risk_band": risk_band(p) if p else None,
        "mode": mode,
        "gate_armed": gate_armed(),
        "gate_shut_because": reasons,
        "quotes": quote_backend(),
        "kite": kite_status(),
        "halted": eng.risk.halted,
        "halt_reason": eng.risk.halt_reason,
        "desks": list(eng.desks),
        "paper_trading_days": eng.journal.paper_trading_days(),
        "disclaimer": (
            "Educational analysis only. Not investment advice. Not issued by a "
            "SEBI-registered Research Analyst or Investment Adviser."
        ),
    }
