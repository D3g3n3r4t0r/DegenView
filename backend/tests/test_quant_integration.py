"""Focused integration tests using the exact functions in existing modules.

Load only the tested definitions to avoid starting network-backed application
singletons. The repository's full suite remains an additional CI requirement.
"""
import ast
import math
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from app.trading.onchain import quant_engine as q
from app.trading.onchain import quant_runtime as runtime

ROOT = Path(__file__).parents[1] / "app"


def definitions(path, names, scope):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
             or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
    return scope


def test_real_trend_strategies_are_prefix_invariant():
    names = {"DEFAULT_PARAMS", "LORENZO_HF_DEFAULT_PARAMS", "HF_MIN_BARS", "_ma", "_wilder_rma",
             "compute_signals", "compute_lorenzo_hf_signals", "spot_only"}
    scope = definitions(ROOT / "analysis/strategies.py", names, {"np": np, "pd": pd})
    rows = []
    for i in range(700):
        price = 100 + i * .01 + 8 * math.sin(i / 13)
        rows.append([i * 300, price, price + 1, price - 1, price + .1, 1000 + i])
    for fn in ("compute_signals", "compute_lorenzo_hf_signals"):
        def provider(rs, _):
            df = pd.DataFrame(rs, columns=["t", "open", "high", "low", "close", "volume"])
            sig = scope["spot_only"](scope[fn](df))
            return list(zip(sig.entry_long, sig.exit_long))
        full = q.signal_table(rows, 300, 700 * 300, "unused", provider)
        prefix = q.signal_table(rows[:450], 300, 450 * 300, "unused", provider)
        assert {k: v for k, v in full.items() if k <= 450 * 300} == prefix


def test_autotrader_never_uses_alert_only_for_new_entries():
    old = {"chain": "robinhood", "kind": "meme", "alert_bt": {"Trend HF": {"state": "in", "in_at": 100}}}
    selected = {"chain": "robinhood", "quant_system": {"in_at": 110}, "ok": True}
    scope = definitions(ROOT / "trading/onchain/autotrader.py", {"entry_candidate"}, {
        "CHAIN": "robinhood", "alert_track": SimpleNamespace(_alerts={"a": old, "b": selected}),
        "quant_runtime": SimpleNamespace(can_enter=lambda a, now: a.get("ok") is True)})
    assert scope["entry_candidate"]("Trend HF", 120) is selected
    selected["ok"] = False
    assert scope["entry_candidate"]("Trend HF", 120) is None


def test_existing_position_keeps_legacy_exit_new_position_uses_quant_exit():
    alert = {"alert_bt": {"HF": {"state": "in"}}, "quant_system": {"state": "out", "eligible": True,
              "evaluated_at": time.time(), "events": [{"side": "sell", "why": "trend_exit"}]}}
    scope = definitions(ROOT / "trading/onchain/autotrader.py", {"_system_of", "should_exit"}, {
        "alert_track": SimpleNamespace(_alerts={"a": alert}), "time": time})
    assert scope["should_exit"]({"alert": "a"}, "HF") is None
    assert scope["should_exit"]({"alert": "a", "quant_policy": "v1"}, "HF") == "system sold"


def test_paper_return_uses_its_own_entry_not_whole_backtest():
    scope = definitions(ROOT / "trading/onchain/autotrader.py", {"_paper_ret"}, {})
    p = {"quant_policy": "v1", "entry_price": 100, "signal_at": 10,
         "costs": {"commission": 0, "slippage": 0}}
    a = {"quant_system": {"ret": 4, "mark": 120, "events": [{"side": "sell", "t": 9, "price": 300}]}}
    ret, closed, _ = scope["_paper_ret"](p, a, "HF")
    assert abs(ret - .2) < 1e-10 and not closed
    a["quant_system"]["events"].append({"side": "sell", "t": 11, "price": 110})
    ret, closed, _ = scope["_paper_ret"](p, a, "HF")
    assert abs(ret - .1) < 1e-10 and closed


def test_no_policy_means_no_new_entry_and_no_fabricated_evaluation():
    a = {"at": 100}
    runtime.refresh(a, [], 200)
    assert "quant_system" not in a
    assert not runtime.can_enter(a, 200)


def test_receipt_hooks_are_wired_without_rewriting_legacy_results():
    src = (ROOT / "trading/onchain/outcomes.py").read_text(encoding="utf-8")
    assert src.index("quant_memory.record(entries().values())") < src.index("_prune(_journal, KEEP")
    tree = ast.parse((ROOT / "trading/onchain/alert_track.py").read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.Attribute) and n.attr == "refresh" and isinstance(n.value, ast.Name)
               and n.value.id == "quant_runtime" for n in ast.walk(tree))
