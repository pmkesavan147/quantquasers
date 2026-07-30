"""Indian equity cost model — itemised, always on, both product types.

Delivery (CNC) rates ported from the reference implementation. Intraday
(MIS) rates added for the day desk, which the reference did not need.

Zerodha, NSE equity. Verify against the live brokerage calculator before
any real-money use — these rates change:
https://zerodha.com/brokerage-calculator

                        CNC (delivery)          MIS (intraday)
  brokerage             ₹0                      0.03% or ₹20/order, lower
  STT                   0.1%  buy AND sell      0.025% SELL side only
  exchange txn (NSE)    0.00297%                0.00297%
  SEBI charges          ₹10/crore               ₹10/crore
  stamp duty            0.015%  BUY only        0.003%  BUY only
  GST                   18% on (brokerage + exchange txn + SEBI)
  slippage              bps, applied to the fill price by the broker sim

Paper P&L that ignores these is a lie. The reference measured 0.80pp of
CAGR lost to cost drag over 10 years — visible only because it itemised.
"""

from __future__ import annotations

from dataclasses import dataclass

# shared
EXCH_TXN_RATE = 0.0000297
SEBI_RATE = 0.000001
GST_RATE = 0.18

# delivery
STT_RATE_CNC = 0.001
STAMP_RATE_CNC_BUY = 0.00015

# intraday
STT_RATE_MIS_SELL = 0.00025
STAMP_RATE_MIS_BUY = 0.00003
BROKERAGE_RATE_MIS = 0.0003
BROKERAGE_CAP_MIS = 20.0


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    stt: float
    exchange_txn: float
    sebi: float
    stamp: float
    gst: float

    @property
    def total(self) -> float:
        return (
            self.brokerage + self.stt + self.exchange_txn
            + self.sebi + self.stamp + self.gst
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "brokerage": round(self.brokerage, 2),
            "stt": round(self.stt, 2),
            "exchange_txn": round(self.exchange_txn, 2),
            "sebi": round(self.sebi, 2),
            "stamp": round(self.stamp, 2),
            "gst": round(self.gst, 2),
            "total": round(self.total, 2),
        }


def delivery_costs(side: str, qty: int, price: float) -> CostBreakdown:
    turnover = qty * price
    brokerage = 0.0
    stt = turnover * STT_RATE_CNC
    exch = turnover * EXCH_TXN_RATE
    sebi = turnover * SEBI_RATE
    stamp = turnover * STAMP_RATE_CNC_BUY if side == "BUY" else 0.0
    gst = (brokerage + exch + sebi) * GST_RATE
    return CostBreakdown(brokerage, stt, exch, sebi, stamp, gst)


def intraday_costs(side: str, qty: int, price: float) -> CostBreakdown:
    turnover = qty * price
    brokerage = min(turnover * BROKERAGE_RATE_MIS, BROKERAGE_CAP_MIS)
    stt = turnover * STT_RATE_MIS_SELL if side == "SELL" else 0.0
    exch = turnover * EXCH_TXN_RATE
    sebi = turnover * SEBI_RATE
    stamp = turnover * STAMP_RATE_MIS_BUY if side == "BUY" else 0.0
    gst = (brokerage + exch + sebi) * GST_RATE
    return CostBreakdown(brokerage, stt, exch, sebi, stamp, gst)


def costs_for(product: str, side: str, qty: int, price: float) -> CostBreakdown:
    """Dispatch on product. The day desk trades MIS, the others CNC."""
    if product == "MIS":
        return intraday_costs(side, qty, price)
    return delivery_costs(side, qty, price)
