"""The Top 50 $10k wallet replayed under several slippage limits. Read only.

Lorenzo, 01/10: "ora siamo a 11k di totale invece di 32k [...] simula piu'
scenari di slippage e vediamo cosa esce". Same ledger and same replay as
the profile (sim_backtest.replay), only the size limit changes; open
positions are held at cost here, so the totals differ a little from the
screen, never between scenarios.

    docker compose exec -T app python - < scripts/slippage_scenarios.py > slippage_scenarios.json
"""
import json
import sys

sys.path.insert(0, "/app")
from app.trading.onchain import sim_backtest  # noqa: E402

sim_backtest._load()
tokens = sim_backtest.ledger_tokens()
bare = [{**t, "liq": None} for t in tokens]

scenarios = [("no cap, no slippage (before #450)", bare, None)]
scenarios += [("no cap, pays slippage", tokens, 99.0)]
scenarios += [(f"cap {p}%", tokens, p) for p in (0.5, 1.0, 2.0, 3.0, 5.0, 10.0)]

rows = []
for name, tks, pct in scenarios:
    r = sim_backtest.replay(tks, max_slip_pct=pct)
    rows.append({"scenario": name, "equity": r["equity"], "ret_pct": round((r["ret"] or 0) * 100, 1),
                 "max_dd_pct": round(r["max_dd"] * 100, 1), "trades": r["trades"], "win_rate": r["win_rate"],
                 "capped": r["capped"], "skipped": r["skipped"], "slippage_usd": r["slippage_usd"],
                 "open": len(r["open"])})

with_liq = sum(1 for t in tokens if t.get("liq"))
print(json.dumps({"tokens": len(tokens), "tokens_with_liquidity": with_liq, "scenarios": rows}, indent=1))
