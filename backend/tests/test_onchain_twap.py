"""Numero di fette e ritardi del TWAP — dal piano: N cresce con quanto
l'ordine pesa sulla liquidita' del pool, mai piu' di 8, mai fette sotto i 5
USD, mai un solo colpo per un ordine piccolo su un pool profondo."""

from __future__ import annotations

import random

from app.trading.onchain import twap


def test_small_order_on_deep_pool_is_a_single_slice():
    assert twap.slice_count(20.0, 1_000_000.0) == 1
    assert twap.plan_slices(20.0, 1_000_000.0) == [20.0]


def test_order_that_is_a_meaningful_share_of_a_thin_pool_gets_sliced():
    # 20 USD su un pool di 500 USD e' il 4% -> a target 1%/fetta serve n=4
    n = twap.slice_count(20.0, 500.0)
    assert n == 4


def test_never_more_than_max_slices():
    n = twap.slice_count(100.0, 100.0, target_slippage_pct=0.1)  # rapporto enorme
    assert n == twap.DEFAULT_MAX_SLICES


def test_never_a_slice_below_the_minimum():
    n = twap.slice_count(6.0, 100.0)  # 6% del pool, vorrebbe tante fette
    for size in twap.plan_slices(6.0, 100.0):
        assert size >= twap.DEFAULT_MIN_SLICE_USD - 0.01 or n == 1


def test_slices_sum_to_the_exact_notional():
    slices = twap.plan_slices(20.0, 300.0)
    assert round(sum(slices), 2) == 20.0


def test_zero_liquidity_falls_back_to_a_single_slice():
    assert twap.slice_count(20.0, 0.0) == 1
    assert twap.plan_slices(20.0, 0.0) == [20.0]


def test_delays_are_jittered_within_bounds():
    rng = random.Random(42)
    delays = twap.plan_delays_s(4, base_delay_s=30.0, jitter_pct=0.35, rng=rng)
    assert len(delays) == 3
    for d in delays:
        assert 30.0 * 0.65 <= d <= 30.0 * 1.35


def test_single_slice_has_no_delays():
    assert twap.plan_delays_s(1) == []
