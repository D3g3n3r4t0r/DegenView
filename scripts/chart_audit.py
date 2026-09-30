"""Every Top 50 row against the trades its chart draws. Read only.

Lorenzo, 30/09 (MERRYMEN): "+400% in classifica [...] non vedo niente [...]
queste cose non devono accadere". For each token in the lab store it takes
what the Top list shows (main._lab_summary, then the same rule as
frontend/static/onchain/lab-shown.js) and the events the chart draws for it,
and flags any row whose number has no arrows, or whose arrow count does not
match its trades. Prints JSON, one line per token, and a summary.

    docker compose exec -T app python - < scripts/chart_audit.py > chart_audit.json
"""
import json
import sys

sys.path.insert(0, "/app")
from app.trading.onchain import strategy_lab  # noqa: E402

strategy_lab._load()


def shown(bt: dict) -> tuple[str, dict | None, list]:
    daily = bt.get("daily") or {}
    drow = (daily.get("rows") or [None])[0]
    if drow and drow.get("trades") and drow.get("return_pct") is not None:
        return daily.get("interval") or "1d", drow, (daily.get("best") or {}).get("events") or []
    rows = [r for r in bt.get("rows") or [] if r.get("trades") and r.get("return_pct") is not None]
    if rows:
        return "5m", max(rows, key=lambda r: r["return_pct"]), (bt.get("best") or {}).get("events") or []
    return "", None, []


bad = 0
out = []
for key, r in strategy_lab._results.items():
    bt = strategy_lab.get(*key.split(":", 1))
    if not bt:
        continue
    iv, row, ev = shown(bt)
    if row is None:
        continue
    sells = sum(1 for e in ev if e.get("side") == "sell")
    buys = sum(1 for e in ev if e.get("side") == "buy")
    ok = bool(ev) and sells == row["trades"] and buys >= sells
    bad += not ok
    out.append({"symbol": r.get("symbol"), "key": key, "interval": iv, "return_pct": row["return_pct"],
                "trades": row["trades"], "buys": buys, "sells": sells,
                "ok": ok})
for o in sorted(out, key=lambda o: o["ok"]):
    print(json.dumps(o))
print(json.dumps({"tokens": len(out), "mismatched": bad}))
