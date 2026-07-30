"""Track 2's half of the API. Track 1 owns routes_sentiment.py.

Route names and shapes are the frozen contract from the track docs — do not
rename these without telling Track 3.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.state import engine, fixture_candidates, quote_backend
from core.contracts import Candidate
from trading.desks import propose_entries, propose_exits
from trading.execution.gate import gate_armed, resolve_mode
from trading.execution.kite import kite_status
from trading.models import DeskState, Fill, PortfolioState, ProposedOrder

router = APIRouter(prefix="/api", tags=["trading"])


# ── request bodies ───────────────────────────────────────────────────────
class DeskRequest(BaseModel):
    desk: str
    candidates: list[Candidate] | None = None   # None => use fixtures
    day_trading_allowed: bool = True
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

    sentiments = {c.symbol: c.sentiment for c in cands}
    exits = propose_exits(desk, broker, sentiments, eng.quotes, now)
    entries, _skips = propose_entries(
        desk, cands, broker, eng.limits, eng.quotes, now,
        day_trading_allowed=req.day_trading_allowed,
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
    return {
        "db": True,
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
