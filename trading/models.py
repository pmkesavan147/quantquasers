"""Trading schemas. Owned by Track 2.

Ported from the reference implementation, extended with `desk` and
`product` so one risk manager can serve three desks with different
product types (MIS intraday vs CNC delivery).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Product = Literal["MIS", "CNC"]


class ProposedOrder(BaseModel):
    desk: str                        # "day" | "swing" | "long_term"
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: int
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    product: Product = "CNC"
    limit_price: float | None = None
    reason: str                      # the desk's own stated rationale


class RiskVerdict(BaseModel):
    order: ProposedOrder
    decision: Literal["approve", "resize", "veto"]
    final_qty: int
    rule_fired: str | None = None


class Fill(BaseModel):
    desk: str
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: int
    price: float
    costs: float
    mode: str                        # "paper" | "live"
    order_id: str
    product: Product = "CNC"
    reason: str = ""
    # Realised P&L booked by this fill, net of its costs. Non-zero on SELLs
    # only. Stored on the fill so the journal is self-describing — daily P&L
    # can be summed from the ledger without re-deriving average prices.
    realised: float = 0.0


class Position(BaseModel):
    """A desk's open holding. Derived by replaying the journal, never stored."""

    desk: str
    symbol: str
    qty: int
    avg_price: float
    opened_at: datetime
    product: Product = "CNC"

    def pnl_pct(self, ltp: float) -> float:
        if self.avg_price <= 0:
            return 0.0
        return (ltp - self.avg_price) / self.avg_price * 100

    def held_days(self, now: datetime) -> int:
        return max(0, (now.date() - self.opened_at.date()).days)


class JournalEntry(BaseModel):
    """Append-only. One table, typed payloads."""

    ts: datetime
    kind: Literal["proposal", "verdict", "fill", "alert", "auth", "note", "skip"]
    payload: dict


class DeskState(BaseModel):
    """What GET /api/desks returns."""

    name: str
    horizon: str
    enabled: bool
    product: Product
    allocation_pct: float
    capital: float
    deployed: float
    cash: float
    open_positions: int
    max_positions: int
    unrealised_pnl: float
    realised_pnl_today: float


class PortfolioState(BaseModel):
    """What GET /api/portfolio returns. Firm-wide, across all desks."""

    mode: str
    halted: bool
    halt_reason: str | None = None
    capital: float
    deployed: float
    cash: float
    unrealised_pnl: float
    realised_pnl_today: float
    day_pnl: float
    orders_today: int
    positions: list[Position] = []
    desks: list[DeskState] = []
