"""Costs are always charged, itemised, and different per product.

Paper P&L that ignores costs is a lie, so these are worth pinning down.
"""

from __future__ import annotations

import pytest

from trading.execution.costs import costs_for, delivery_costs, intraday_costs


def test_delivery_charges_stt_on_both_sides():
    buy = delivery_costs("BUY", 100, 1000.0)
    sell = delivery_costs("SELL", 100, 1000.0)
    assert buy.stt == pytest.approx(100.0)      # 0.1% of 100,000
    assert sell.stt == pytest.approx(100.0)


def test_intraday_charges_stt_on_the_sell_side_only():
    assert intraday_costs("BUY", 100, 1000.0).stt == 0.0
    assert intraday_costs("SELL", 100, 1000.0).stt == pytest.approx(25.0)


def test_stamp_duty_is_buy_side_only_for_both_products():
    assert delivery_costs("SELL", 100, 1000.0).stamp == 0.0
    assert intraday_costs("SELL", 100, 1000.0).stamp == 0.0
    assert delivery_costs("BUY", 100, 1000.0).stamp > 0
    assert intraday_costs("BUY", 100, 1000.0).stamp > 0


def test_delivery_brokerage_is_zero_intraday_is_not():
    assert delivery_costs("BUY", 100, 1000.0).brokerage == 0.0
    assert intraday_costs("BUY", 100, 1000.0).brokerage > 0


def test_intraday_brokerage_is_capped_at_twenty_rupees():
    small = intraday_costs("BUY", 1, 1000.0)         # 0.03% of 1,000 = ₹0.30
    large = intraday_costs("BUY", 10_000, 1000.0)    # 0.03% of 1cr = ₹3,000
    assert small.brokerage == pytest.approx(0.30)
    assert large.brokerage == pytest.approx(20.0)


def test_gst_applies_to_brokerage_txn_and_sebi_but_not_stt():
    c = intraday_costs("BUY", 100, 1000.0)
    expected = (c.brokerage + c.exchange_txn + c.sebi) * 0.18
    assert c.gst == pytest.approx(expected)


def test_total_is_the_sum_of_the_items():
    c = delivery_costs("BUY", 100, 1000.0)
    assert c.total == pytest.approx(
        c.brokerage + c.stt + c.exchange_txn + c.sebi + c.stamp + c.gst
    )


def test_intraday_is_cheaper_than_delivery_on_a_round_trip():
    """The whole reason intraday exists as a product."""
    cnc = (delivery_costs("BUY", 100, 1000.0).total
           + delivery_costs("SELL", 100, 1000.0).total)
    mis = (intraday_costs("BUY", 100, 1000.0).total
           + intraday_costs("SELL", 100, 1000.0).total)
    assert mis < cnc


def test_costs_are_never_zero():
    """No product, side, or size may round to a free trade."""
    for product in ("CNC", "MIS"):
        for side in ("BUY", "SELL"):
            assert costs_for(product, side, 1, 10.0).total > 0


def test_dispatch_matches_the_direct_functions():
    assert costs_for("MIS", "SELL", 50, 500.0).as_dict() == \
        intraday_costs("SELL", 50, 500.0).as_dict()
    assert costs_for("CNC", "BUY", 50, 500.0).as_dict() == \
        delivery_costs("BUY", 50, 500.0).as_dict()
