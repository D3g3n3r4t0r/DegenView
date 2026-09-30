"""The Top 50 gems' trend follower trades, replayed on one wallet.

Lorenzo, 30/09: "voglio che tu applichi a quel portafoglio [10.000 dollari]
tutti gli ingressi e tutti i rendimenti di tutte le gemme in top 50 per
vedere come avrebbe performato". Every gem's saved backtest (strategy_lab
`daily`: the trend follower on the ladder's timeframe, fees included) is a
list of buys and sells; here they all run on one shared cash balance in
time order. Each buy spends `pct` of the wallet's value (at cost), or the
cash left; a buy with no cash left is counted as skipped. Open trades are
marked at the backtest's last close. Nothing is stored and nothing touches
the live simulated wallet: it is a read of results already on disk.
"""
from __future__ import annotations

FEE = 2 * 0.3 / 100          # radar.BACKTEST_PARAMS commission, in and out


def _round_trips(item: dict) -> list[dict]:
    """buy -> sell pairs of one gem, the last one maybe still open."""
    out, cur = [], None
    for ev in sorted(item.get("events") or [], key=lambda v: v.get("t") or 0):
        price = ev.get("price")
        if ev.get("side") == "buy" and cur is None and price:
            cur = {"in_t": int(ev["t"]), "in_price": float(price)}
        elif ev.get("side") == "sell" and cur is not None:
            ret = ev.get("ret")
            if ret is None and ev.get("price"):
                ret = float(ev["price"]) / cur["in_price"] - 1 - FEE
            out.append({**cur, "out_t": int(ev["t"]), "out_price": ev.get("price"), "ret": float(ret or 0.0)})
            cur = None
    if cur is not None:
        last = item.get("last")
        ret = float(last) / cur["in_price"] - 1 - FEE if last else 0.0
        out.append({**cur, "out_t": None, "out_price": last, "ret": ret, "open": True})
    return out


def replay(items: list[dict], cash: float = 10_000.0, pct: float = 10.0) -> dict:
    """items: {chain, token, symbol, interval, events, last}. Returns the
    wallet's trades, open positions, a value line and the totals."""
    start = cash = float(cash)
    pct = max(1.0, min(100.0, float(pct)))
    steps = []
    for it in items:
        for rt in _round_trips(it):
            base = {k: it.get(k) for k in ("chain", "token", "symbol", "interval", "pair")}
            steps.append((rt["in_t"], 1, base, rt))
            if not rt.get("open"):
                steps.append((rt["out_t"], 0, base, rt))
    steps.sort(key=lambda s: (s[0], s[1]))          # a sell frees cash before a buy at the same time
    held: dict[int, float] = {}                      # id(round trip) -> stake
    trades, skipped = [], 0
    curve = [[steps[0][0], start]] if steps else []
    for t, is_buy, base, rt in steps:
        if is_buy:
            equity = cash + sum(held.values())
            stake = min(cash, equity * pct / 100)
            if stake < 0.01:
                skipped += 1
                continue
            cash -= stake
            held[id(rt)] = stake
            continue
        stake = held.pop(id(rt), None)
        if stake is None:
            continue
        cash += stake * (1 + rt["ret"])
        trades.append({**base, **rt, "stake": round(stake, 2), "pnl": round(stake * rt["ret"], 2)})
        curve.append([t, round(cash + sum(held.values()), 2)])
    open_rows = []
    for t, is_buy, base, rt in steps:
        stake = held.get(id(rt)) if is_buy else None
        if stake is not None:
            open_rows.append({**base, **rt, "stake": round(stake, 2), "pnl": round(stake * rt["ret"], 2)})
    final = cash + sum(r["stake"] * (1 + r["ret"]) for r in open_rows)
    if steps:
        curve.append([max(s[0] for s in steps), round(final, 2)])
    wins = sum(1 for r in trades if r["ret"] > 0)
    return {"start": round(start, 2), "pct": pct, "final": round(final, 2), "cash": round(cash, 2),
            "ret": round(final / start - 1, 4) if start else None, "trades": trades[::-1], "open": open_rows,
            "curve": curve, "gems": len({(i.get("chain"), i.get("token")) for i in items}),
            "traded": len({(r["chain"], r["token"]) for r in trades + open_rows}),
            "wins": wins, "closed": len(trades), "skipped": skipped,
            "from": steps[0][0] if steps else None}
