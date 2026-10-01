"""Every Top 50 row against the trades its chart draws. Read only.

Lorenzo, 30/09 (MERRYMEN): "+400% in classifica [...] non vedo niente [...]
queste cose non devono accadere". For each token in the lab store: the row
the list shows (main._lab_summary -> strategy_lab.shown, the same rule
as frontend/static/onchain/lab-shown.js) and the events its chart draws.
"hidden" = a listed result (trend follower or RSI+BB) whose saved arrows are not its trades:
the list leaves it out until the lab redoes it (it goes first in the queue).
"mismatched" must be 0.

    docker compose exec -T app python - < scripts/chart_audit.py > chart_audit.json
"""
import json
import sys

sys.path.insert(0, "/app")
from app.trading.onchain import sim_backtest, strategy_lab  # noqa: E402

strategy_lab._load()

counts = {"tokens": 0, "listed": 0, "hidden": 0, "mismatched": 0}
for key, r in strategy_lab._results.items():
    bt = strategy_lab.get(*key.split(":", 1))
    if not bt:
        continue
    counts["tokens"] += 1
    daily = bt.get("daily") or {}
    got = strategy_lab.shown(bt)
    iv, part, row = got if got else (None, None, None)
    if row is None:
        if strategy_lab.trend_row(bt) or (daily and strategy_lab.trend_row(daily)):
            counts["hidden"] += 1
            print(json.dumps({"symbol": r.get("symbol"), "key": key, "hidden": True,
                              "row_label": (strategy_lab.trend_row(bt) or {}).get("label"),
                              "events_label": (bt.get("best") or {}).get("label")}))
        continue
    ev = part["best"]["events"]
    sells = sum(1 for e in ev if e.get("side") == "sell")
    ok = sells == row["trades"]
    counts["listed"] += 1
    counts["mismatched"] += not ok
    print(json.dumps({"symbol": r.get("symbol"), "key": key, "interval": iv, "label": row["label"],
                      "events_labels": sorted({e.get("lab") or "?" for e in part["best"]["events"]}),
                      "return_pct": row["return_pct"], "trades": row["trades"], "sells": sells, "ok": ok}))
print(json.dumps(counts))
# The Top 50 wallet's saved trades by strategy ("unknown" = never proven).
by: dict[str, int] = {}
for tk in sim_backtest.ledger_tokens():
    for e in tk["events"]:
        k = f"{e.get('iv')} {sim_backtest.strategy_of(e)}"
        by[k] = by.get(k, 0) + 1
print(json.dumps({"ledger": dict(sorted(by.items()))}))
