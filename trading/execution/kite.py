"""Kite Connect adapter.

Two independent halves, and the distinction matters:

  MARKET DATA  — used in paper mode too. Real LTPs, real instrument
                 lookups, no order ever placed. This is a genuine broker
                 integration you can demo without risking a rupee.

  ORDER ROUTING — reachable only through the triple-locked gate. Never
                 armed during the hackathon.

Auth flow (access tokens expire daily, ~08:00 IST):
    login_url()  ->  user logs in in a browser
                 ->  redirect carries ?request_token=...
    exchange(request_token)  ->  access_token, cached to kite_token.json
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from trading.execution.broker import NotFilled
from trading.execution.costs import costs_for
from trading.models import Fill, ProposedOrder

ROOT = Path(__file__).resolve().parent.parent.parent
TOKEN_FILE = ROOT / "kite_token.json"


# ── auth ─────────────────────────────────────────────────────────────────
def _kite_class():
    try:
        from kiteconnect import KiteConnect
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "kiteconnect not installed — pip install kiteconnect"
        ) from e
    return KiteConnect


def login_url() -> str:
    api_key = os.environ["KITE_API_KEY"]
    return _kite_class()(api_key=api_key).login_url()


def exchange(request_token: str) -> str:
    """Swap a one-time request_token for a daily access_token and cache it."""
    api_key = os.environ["KITE_API_KEY"]
    api_secret = os.environ["KITE_API_SECRET"]
    kite = _kite_class()(api_key=api_key)
    data = kite.generate_session(request_token, api_secret=api_secret)
    token = data["access_token"]
    TOKEN_FILE.write_text(
        json.dumps({"access_token": token, "date": date.today().isoformat()}),
        encoding="utf-8",
    )
    return token


def cached_token() -> str | None:
    """None when absent or stale — Kite tokens do not survive the night."""
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("date") != date.today().isoformat():
        return None
    return data.get("access_token")


def load_kite():
    """An authenticated KiteConnect, or None if we have no valid token.

    Returning None rather than raising is deliberate: a missing token must
    degrade to mock quotes, not crash the engine mid-session.
    """
    api_key = os.getenv("KITE_API_KEY")
    token = cached_token()
    if not api_key or not token:
        return None
    kite = _kite_class()(api_key=api_key)
    kite.set_access_token(token)
    return kite


def kite_status() -> dict:
    """For GET /api/health."""
    return {
        "api_key_present": bool(os.getenv("KITE_API_KEY")),
        "token_valid_today": cached_token() is not None,
    }


# ── order routing (gated) ────────────────────────────────────────────────
class KiteBroker:
    """Live order routing. Constructed only by the gate, only when all three
    locks are open. Not exercised during the hackathon."""

    mode = "live"

    def __init__(self, kite, quotes, desk: str):
        if kite is None:
            raise RuntimeError("KiteBroker requires an authenticated session")
        self.kite = kite
        self.quotes = quotes
        self.desk = desk

    def place(self, order: ProposedOrder, qty: int) -> Fill:
        if qty <= 0:
            raise NotFilled("qty must be positive")
        order_id = self.kite.place_order(
            variety=self.kite.VARIETY_REGULAR,
            exchange=self.kite.EXCHANGE_NSE,
            tradingsymbol=order.symbol.upper(),
            transaction_type=(
                self.kite.TRANSACTION_TYPE_BUY if order.side == "BUY"
                else self.kite.TRANSACTION_TYPE_SELL
            ),
            quantity=qty,
            product=(
                self.kite.PRODUCT_MIS if order.product == "MIS"
                else self.kite.PRODUCT_CNC
            ),
            order_type=(
                self.kite.ORDER_TYPE_LIMIT if order.order_type == "LIMIT"
                else self.kite.ORDER_TYPE_MARKET
            ),
            price=order.limit_price,
        )
        price = self.quotes.ltp(order.symbol) or 0.0
        costs = costs_for(order.product, order.side, qty, price)
        return Fill(
            desk=self.desk, symbol=order.symbol, side=order.side, qty=qty,
            price=round(price, 2), costs=round(costs.total, 2), mode=self.mode,
            order_id=str(order_id), product=order.product, reason=order.reason,
        )

    def positions(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self.kite.positions().get("net", []):
            if p.get("quantity"):
                out[p["tradingsymbol"]] = int(p["quantity"])
        return out

    def avg_price(self, symbol: str) -> float:
        for p in self.kite.positions().get("net", []):
            if p["tradingsymbol"] == symbol.upper():
                return float(p.get("average_price") or 0.0)
        return 0.0

    def cash(self) -> float:
        m = self.kite.margins("equity")
        return float(m["available"]["live_balance"])
