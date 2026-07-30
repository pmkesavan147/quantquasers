"""Quote sources.

Paper mode is meant to run on LIVE Kite quotes — that's a genuine broker
integration you can demo without risking a rupee. MockQuoteSource provides
deterministic prices (no RNG, so demos and tests are reproducible) until
credentials exist.

Tier note: the free Kite Personal tier gives EOD closes, which is fine for
swing and CNC. Live intraday ticks need the paid data add-on. Say which
tier you are on rather than implying ticks you do not have.
"""

from __future__ import annotations

import math
from typing import Protocol


class QuoteSource(Protocol):
    def ltp(self, symbol: str) -> float | None: ...


class MockQuoteSource:
    """Deterministic drifting prices seeded from a base map."""

    def __init__(self, base_prices: dict[str, float]):
        self.base = {k.upper(): v for k, v in base_prices.items()}
        self._tick = 0

    def advance(self, n: int = 1):
        self._tick += n

    def set(self, symbol: str, price: float):
        """Force a price — used by tests to drive stops and targets."""
        self.base[symbol.upper()] = price

    def ltp(self, symbol: str) -> float | None:
        base = self.base.get(symbol.upper())
        if base is None:
            return None
        wobble = 1 + 0.002 * math.sin(self._tick + len(symbol) % 7)
        return round(base * wobble, 2)


class KiteQuoteSource:
    """Live LTPs via Kite market data. Places no orders."""

    def __init__(self, kite):  # kiteconnect.KiteConnect, already authenticated
        self.kite = kite

    def ltp(self, symbol: str) -> float | None:
        key = f"NSE:{symbol.upper()}"
        try:
            data = self.kite.ltp([key])
            return float(data[key]["last_price"])
        except Exception:
            return None
