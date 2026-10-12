"""Timings and loop lag for the overhaul baseline (week 1)."""
import asyncio

from app import perf


def test_snapshot_percentiles_and_errors():
    perf._routes.clear()
    for ms in range(1, 101):
        perf.record("GET /api/x", ms / 1000, 500 if ms == 100 else 200)
    snap = perf.snapshot()
    row = next(r for r in snap["routes"] if r["route"] == "GET /api/x")
    assert row["count"] == 100 and row["errors"] == 1
    assert 49 <= row["p50_ms"] <= 51 and row["max_ms"] == 100.0


def test_probe_sees_a_blocked_loop():
    perf._lags.clear()

    async def run():
        task = asyncio.create_task(perf.loop_lag_probe())
        await asyncio.sleep(0.05)
        import time
        time.sleep(0.8)            # block the loop past the probe's wake-up, like a sync backtest
        await asyncio.sleep(perf.PROBE_EVERY_S + 0.2)
        task.cancel()

    asyncio.run(run())
    assert perf.snapshot()["loop_lag"]["max_ms"] >= 100
