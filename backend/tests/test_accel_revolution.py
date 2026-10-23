"""Tests for the 3-Pillar Performance Revolution (`seed-0398l`):
1. Pillar 1: Native Rust / NumPy SIMD Quant Kernels (`rust_bridge`) & `orjson` SIMD (`fast_json`)
2. Pillar 2: Zero-Latency RAM Snapshot & Mtime Caching (`ram_cache`, `arenas`, `sectors`, `parser`, `indicators`)
3. Pillar 3: Client-Side WebAssembly Quant Engine (`wasm-engine.js`) & `/api/perf` telemetry
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pandas as pd

from app import perf
from app.accel import fast_json, ram_cache, rust_bridge
from app.analysis import fibonacci, indicators, smc_engine, strategies
from app.pine import parser as pine_parser


def _sample_df(n: int = 240) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    t = np.linspace(0, 12 * np.pi, n)
    close = 100.0 + 12.0 * np.sin(t) + np.linspace(0, 5, n)
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=idx,
    )


def test_fast_confirmed_transitions_matches_all_signal_types():
    df = _sample_df(20)
    sig = pd.DataFrame(
        {
            "entry_long": [False, True, False, False, False, False, True, False] + [False] * 12,
            "entry_short": [False, False, False, True, False, True, False, False] + [False] * 12,
            "exit_long": [False, False, True, False, False, False, False, True] + [False] * 12,
            "exit_short": [False, False, False, False, True, False, False, False] + [False] * 12,
        },
        index=df.index,
    )
    events, final_pos = strategies.confirmed_events(df, signals=sig, last_bar_closed=True)
    types = [(e.time, e.type) for e in events]
    expected_bars = [
        (int(df.index[1].timestamp()), "entry_long"),
        (int(df.index[2].timestamp()), "exit_long"),
        (int(df.index[3].timestamp()), "entry_short"),
        (int(df.index[4].timestamp()), "exit_short"),
        (int(df.index[5].timestamp()), "entry_short"),
        (int(df.index[6].timestamp()), "flip_to_long"),
        (int(df.index[7].timestamp()), "exit_long"),
    ]
    assert types == expected_bars
    assert final_pos == 0


def test_lki_indicator_cache_accelerates_parameter_sweep():
    df = _sample_df(300)
    before_hits = rust_bridge.stats()["lki_indicator_cache_hits"]
    s1 = strategies.compute_lki_signals(df, {"rsi_oversold": 25, "rsi_overbought": 75})
    s2 = strategies.compute_lki_signals(df, {"rsi_oversold": 30, "rsi_overbought": 70})
    s3 = strategies.compute_lki2_signals(df, {"rsi_oversold": 28, "rsi_overbought": 72})
    after_hits = rust_bridge.stats()["lki_indicator_cache_hits"]
    assert after_hits >= before_hits + 2
    assert len(s1) == len(s2) == len(s3) == 300


def test_fast_json_mtime_cache_and_invalidation(tmp_path: Path):
    p = tmp_path / "sample.json"
    p.write_text(fast_json.dumps({"alpha": 1, "beta": [1, 2, 3]}), encoding="utf-8")
    first = fast_json.read_json_cached(p)
    hits_before = fast_json.stats()["file_cache_hits"]
    second = fast_json.read_json_cached(p)
    hits_after = fast_json.stats()["file_cache_hits"]
    assert first == second == {"alpha": 1, "beta": [1, 2, 3]}
    assert hits_after == hits_before + 1

    fast_json.invalidate_file_cache(p)
    p.write_text(fast_json.dumps({"alpha": 2}), encoding="utf-8")
    assert fast_json.read_json_cached(p) == {"alpha": 2}


def test_ram_cache_copy_on_write_isolation():
    ram_cache.invalidate("test_cow")
    val = ram_cache.get_or_compute("test_cow", 30.0, lambda: {"items": [1, 2, 3]})
    val["items"].append(99)
    cached = ram_cache.get_or_compute("test_cow", 30.0, lambda: {"items": []})
    assert cached == {"items": [1, 2, 3]}

    async def _run():
        return await ram_cache.get_or_compute_async("test_cow_async", 30.0, lambda: {"ok": True})

    assert asyncio.run(_run()) == {"ok": True}


def test_pinescript_parser_ast_cache_and_indicator_cache():
    src = "//@version=5\nindicator('Test')\nx = ta.ema(close, 14)\nplot(x)\n"
    ast1 = pine_parser.parse_program(src)
    ast2 = pine_parser.parse_program(src)
    assert len(ast1) == len(ast2) == 2
    assert ast1 is not ast2  # returns shallow copy so caller list mutations are isolated

    df = _sample_df(120)
    ind1 = indicators.compute_indicators(df, "1h")
    ind2 = indicators.compute_indicators(df, "1h")
    assert [i.name for i in ind1] == [i.name for i in ind2]


def test_perf_snapshot_exposes_accel_telemetry_and_wasm_asset():
    snap = perf.snapshot()
    assert "accel" in snap
    assert "rust_core" in snap["accel"]
    assert "simd_json" in snap["accel"]
    assert "ram_snapshot_cache" in snap["accel"]
    assert "smc_cache" in snap["accel"]
    assert snap["accel"]["wasm_engine"]["enabled"] is True

    wasm_js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "wasm-engine.js").read_text(encoding="utf-8")
    assert "WebAssembly.Module" in wasm_js
    assert "WasmQuantEngine" in wasm_js


def test_smc_and_fib_fingerprint_caching_and_fast_json_response():
    df = _sample_df(160)
    before = smc_engine.smc_cache_stats()
    sw1 = smc_engine.compute_swings(df, "ltf")
    sw2 = smc_engine.compute_swings(df, "ltf")
    lvl1 = smc_engine.compute_levels(df, sw1)
    lvl2 = smc_engine.compute_levels(df, sw2)
    fib1 = fibonacci.compute_fib_zones(df, "ltf", "1h")
    fib2 = fibonacci.compute_fib_zones(df, "ltf", "1h")
    after = smc_engine.smc_cache_stats()
    assert after["swings_hits"] >= before["swings_hits"] + 1
    assert after["levels_hits"] >= before["levels_hits"] + 1
    assert lvl1 == lvl2
    assert fib1 == fib2

    resp = fast_json.FastJSONResponse({"ok": True, "count": 42})
    assert resp.media_type == "application/json"
    assert fast_json.loads(resp.body) == {"ok": True, "count": 42}
