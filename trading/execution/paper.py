"""PaperBroker — same code path as live, only the fill is simulated.

Fills at the live quote ± slippage and charges the full itemised Indian
cost stack, so paper results are a meaningful rehearsal rather than a
flattering one.

One broker instance per desk: each desk owns a separate book, replayed
from its own fills in the shared journal.
"""

from __future__ import annotations

from datetime import datetime

from trading.execution.broker import InsufficientFunds, NotFilled
from trading.execution.costs import costs_for
from trading.execution.quotes import QuoteSource
from trading.models import Fill, ProposedOrder


class PaperBroker:
    mode = "paper"

    def __init__(self, quotes: QuoteSource, starting_cash: float,
                 desk: str, slippage_bps: float = 5.0):
        self.quotes = quotes
        self.desk = desk
        self._cash = starting_cash
        self._start_cash = starting_cash
        self._positions: dict[str, int] = {}
        self._avg_price: dict[str, float] = {}
        self._opened_at: dict[str, datetime] = {}
        self.slippage_bps = slippage_bps
        self._order_seq = 0
        self.realised_pnl = 0.0

    # ── fills ────────────────────────────────────────────────────────────
    def place(self, order: ProposedOrder, qty: int) -> Fill:
        if qty <= 0:
            raise NotFilled("qty must be positive")

        quote = self.quotes.ltp(order.symbol)
        if quote is None:
            raise NotFilled(f"no quote for {order.symbol}")

        slip = quote * self.slippage_bps / 10_000
        price = quote + slip if order.side == "BUY" else quote - slip

        if order.order_type == "LIMIT" and order.limit_price is not None:
            if order.side == "BUY" and quote > order.limit_price:
                raise NotFilled("limit below market — not filled")
            if order.side == "SELL" and quote < order.limit_price:
                raise NotFilled("limit above market — not filled")
            price = order.limit_price

        # Round BEFORE applying to the book, using exactly the values that
        # will be journaled. The journal is the source of truth, so a book
        # built from unrounded arithmetic would drift from its own replay.
        price = round(price, 2)
        cost_total = round(costs_for(order.product, order.side, qty, price).total, 2)
        self._order_seq += 1
        realised = 0.0

        if order.side == "BUY":
            need = qty * price + cost_total
            if need > self._cash:
                raise InsufficientFunds(
                    f"need ₹{need:,.0f}, have ₹{self._cash:,.0f}"
                )
            self._apply_buy(order.symbol, qty, price, cost_total)
        else:
            held = self._positions.get(order.symbol, 0)
            if held < qty:
                raise NotFilled(f"cannot sell {qty}, hold {held}")
            realised = self._apply_sell(order.symbol, qty, price, cost_total)

        return Fill(
            desk=self.desk,
            symbol=order.symbol,
            side=order.side,
            qty=qty,
            price=price,
            costs=cost_total,
            mode=self.mode,
            order_id=f"PAPER-{self.desk[:3].upper()}-{self._order_seq:05d}",
            product=order.product,
            reason=order.reason,
            realised=round(realised, 2),
        )

    def _apply_buy(self, symbol: str, qty: int, price: float, costs: float,
                   ts: datetime | None = None):
        held = self._positions.get(symbol, 0)
        self._avg_price[symbol] = (
            (self._avg_price.get(symbol, 0.0) * held + qty * price) / (held + qty)
        )
        self._positions[symbol] = held + qty
        self._cash -= qty * price + costs
        self._opened_at.setdefault(symbol, ts or datetime.now())

    def _apply_sell(self, symbol: str, qty: int, price: float,
                    costs: float) -> float:
        avg = self._avg_price.get(symbol, 0.0)
        realised = qty * (price - avg) - costs
        self.realised_pnl += realised
        self._positions[symbol] = self._positions.get(symbol, 0) - qty
        self._cash += qty * price - costs
        if self._positions.get(symbol, 0) <= 0:
            self._positions.pop(symbol, None)
            self._avg_price.pop(symbol, None)
            self._opened_at.pop(symbol, None)
        return realised

    # ── replay ───────────────────────────────────────────────────────────
    def restore_from_journal(self, journal) -> int:
        """Rebuild this desk's book from journaled paper fills, so an engine
        restart doesn't orphan positions. The journal is the source of truth.
        Returns the number of fills replayed."""
        n = 0
        for entry in journal.all_of("fill"):
            f = entry["payload"]
            if f.get("mode") != "paper" or f.get("desk") != self.desk:
                continue
            if f.get("price") is None:
                continue
            qty, price = int(f["qty"]), float(f["price"])
            costs = float(f.get("costs") or 0.0)
            ts = _parse_ts(entry.get("ts"))
            if f["side"] == "BUY":
                self._apply_buy(f["symbol"], qty, price, costs, ts)
            else:
                self._apply_sell(f["symbol"], qty, price, costs)
            n += 1
        return n

    # ── reads ────────────────────────────────────────────────────────────
    def positions(self) -> dict[str, int]:
        return dict(self._positions)

    def avg_price(self, symbol: str) -> float:
        return self._avg_price.get(symbol, 0.0)

    def opened_at(self, symbol: str) -> datetime:
        return self._opened_at.get(symbol, datetime.now())

    def cash(self) -> float:
        return self._cash

    def deployed(self) -> float:
        """Marked at cost, matching how the risk manager measures exposure."""
        return sum(
            self._avg_price.get(s, 0.0) * q for s, q in self._positions.items()
        )

    def unrealised(self) -> float:
        total = 0.0
        for sym, qty in self._positions.items():
            ltp = self.quotes.ltp(sym)
            if ltp is None:
                continue
            total += qty * (ltp - self._avg_price.get(sym, 0.0))
        return total


def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None
