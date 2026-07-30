"""Risk manager — plain Python, no LLM anywhere near it.

Sits BELOW the desk layer: every order from every desk passes through
evaluate() and comes out approved, resized, or vetoed. Limits are frozen at
construction and there is no method to relax them at runtime. That is a
feature, and worth saying out loud.

Every verdict is journaled with the rule that fired, so a vetoed order is
as auditable as a filled one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from trading.config import DeskConfig, RiskLimits
from trading.journal.store import Journal
from trading.models import ProposedOrder, RiskVerdict


@dataclass
class PortfolioState:
    """Marked-to-market snapshot the risk manager judges against."""

    positions: dict[str, int] = field(default_factory=dict)        # symbol -> qty
    position_value: dict[str, float] = field(default_factory=dict)  # symbol -> ₹
    day_pnl: float = 0.0                 # realised + unrealised, today
    orders_today: int = 0
    desk_deployed: float = 0.0           # this desk's exposure, at cost

    @property
    def deployed(self) -> float:
        return sum(self.position_value.values())


class RiskManager:
    def __init__(self, limits: RiskLimits, journal: Journal):
        self.limits = limits
        self.journal = journal
        self.halted = False
        self._halt_reason: str | None = None

    # ── halt control (kill switch, /pause, /resume) ──────────────────────
    def halt(self, reason: str):
        self.halted = True
        self._halt_reason = reason
        self.journal.append("alert", {"event": "halt", "reason": reason})

    def resume(self):
        self.halted = False
        self._halt_reason = None
        self.journal.append("alert", {"event": "resume"})

    @property
    def halt_reason(self) -> str | None:
        return self._halt_reason

    # ── the gauntlet ─────────────────────────────────────────────────────
    def evaluate(
        self,
        order: ProposedOrder,
        state: PortfolioState,
        quote: float,
        desk: DeskConfig | None = None,
        now: datetime | None = None,
    ) -> RiskVerdict:
        verdict = self._evaluate(order, state, quote, desk, now or datetime.now())
        self.journal.append("verdict", verdict.model_dump(mode="json"))
        return verdict

    def _veto(self, order: ProposedOrder, rule: str) -> RiskVerdict:
        return RiskVerdict(order=order, decision="veto", final_qty=0,
                           rule_fired=rule)

    def _evaluate(
        self,
        order: ProposedOrder,
        state: PortfolioState,
        quote: float,
        desk: DeskConfig | None,
        now: datetime,
    ) -> RiskVerdict:
        lim = self.limits

        # 0. Kill switch first: a halted engine approves nothing.
        if self.halted:
            return self._veto(order, f"halted ({self._halt_reason})")

        # 1. Daily loss kill switch: trips the halt, then vetoes.
        loss_limit = lim.max_capital * lim.daily_loss_limit_pct / 100
        if state.day_pnl <= -loss_limit:
            self.halt(
                f"daily loss {state.day_pnl:,.0f} beyond limit -{loss_limit:,.0f}"
            )
            return self._veto(order, "daily_loss_limit")

        # 2. Runaway backstop.
        if state.orders_today >= lim.max_orders_per_day:
            return self._veto(order, "max_orders_per_day")

        # 3. Allowlist — only symbols the user approved, however good the signal.
        if order.symbol.upper() not in lim.allowlist:
            return self._veto(order, "allowlist")

        # 4. No price, no order.
        if quote <= 0:
            return self._veto(order, "no_valid_quote")

        # ── intraday rules (day desk) ────────────────────────────────────
        # 10. Product/desk coherence. A config error must not reach the broker.
        if desk is not None and order.product != desk.product:
            return self._veto(order, "product_desk_mismatch")

        # 11. Firm-level intraday switch, independent of the user's mandate
        #     (which the desk checks). Two gates, defence in depth.
        if order.product == "MIS" and not lim.allow_intraday:
            return self._veto(order, "intraday_disabled")

        # 9. No new intraday entries after square-off. Exits still allowed —
        #    the whole point of square-off is to close.
        if (
            desk is not None
            and desk.square_off is not None
            and order.side == "BUY"
            and now.time() >= desk.square_off
        ):
            return self._veto(order, "day_square_off_window")

        # ── SELL: only what we hold (CNC — no shorting) ──────────────────
        if order.side == "SELL":
            held = state.positions.get(order.symbol, 0)
            if held <= 0:
                return self._veto(order, "no_position_to_sell")
            if order.qty > held:
                return RiskVerdict(order=order, decision="resize",
                                   final_qty=held,
                                   rule_fired="sell_capped_at_held")
            return RiskVerdict(order=order, decision="approve",
                               final_qty=order.qty)

        # ── BUY sizing: per-position cap, firm capital, desk allocation ──
        per_position_cap = lim.max_capital * lim.max_position_pct / 100
        existing_value = state.position_value.get(order.symbol, 0.0)
        room_position = per_position_cap - existing_value
        room_capital = lim.max_capital - state.deployed

        room_desk = float("inf")
        if desk is not None:
            room_desk = desk.capital(lim) - state.desk_deployed

        room = min(room_position, room_capital, room_desk)

        # Name the binding constraint, so the journal says which wall we hit.
        if room == room_desk and room_desk <= min(room_position, room_capital):
            rule = "desk_allocation"
        elif room_position <= room_capital:
            rule = "max_position_pct"
        else:
            rule = "max_capital"

        max_qty = int(room // quote) if room > 0 else 0
        if max_qty <= 0:
            return self._veto(order, rule)
        if order.qty > max_qty:
            return RiskVerdict(order=order, decision="resize",
                               final_qty=max_qty, rule_fired=rule)
        return RiskVerdict(order=order, decision="approve", final_qty=order.qty)
