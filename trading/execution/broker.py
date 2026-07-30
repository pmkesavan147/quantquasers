"""Broker interface: one contract, two implementations (paper | kite).

Which one runs is decided by the gate, never by a desk and never by a
strategy. A desk cannot tell whether it is trading paper or real money —
that's the property that makes paper a meaningful rehearsal.
"""

from __future__ import annotations

from typing import Protocol

from trading.models import Fill, ProposedOrder


class Broker(Protocol):
    mode: str

    def place(self, order: ProposedOrder, qty: int) -> Fill: ...
    def positions(self) -> dict[str, int]: ...
    def cash(self) -> float: ...
    def avg_price(self, symbol: str) -> float: ...


class InsufficientFunds(RuntimeError):
    pass


class NotFilled(RuntimeError):
    pass
