"""Read-only: every token in the backtest lab, three ways of trading it.

  alert  -- buy at the first open after the discovery, sell on the trend exit
  trail  -- same, plus the 30% trailing stop (system.TRAIL)
  trend  -- wait for the trend follower's own entry

Grouped by the diary's outcome (rug / crollo / buono / finto / piatto) and by
whether the filter passed the token. Prints one JSON summary; writes nothing.
Run inside the app container: python - < scripts/rug_backtest.py
"""
import json
import statistics as st
import zlib

from app.trading.onchain import backtest_lab, outcomes, system

outcomes._load()
cfg = system.BY_LABEL["Trend HF"]


def run(bars, at, gone, mode):
    system.TRAIL_FROM = 0 if mode == "trail" else 10 ** 12
    r = system.follow(bars, cfg, at, gone=gone, on_alert=mode != "trend", now=at + system.WINDOW_S)
    return float(r["ret"]) if r["trades"] or r["state"] == "in" else None


groups: dict = {}
rows = backtest_lab._db().execute("SELECT key, decision, at, bars FROM lab").fetchall()
for key, decision, at, blob in rows:
    try:
        bars = json.loads(zlib.decompress(blob))
    except Exception:
        continue
    if len([b for b in bars if b[0] >= (at or 0)]) < 12:
        continue
    e = outcomes._journal.get(key) or {}
    label = outcomes.outcome(e) or "unknown"
    passed = "passed" if decision in outcomes.PASSED else "rejected"
    gone = label == "rug"
    for g in ((label, passed), (label, "all"), ("all", passed), ("all", "all")):
        b = groups.setdefault(" / ".join(g), {"alert": [], "trail": [], "trend": []})
        for mode in b:
            v = run(bars, at, gone, mode) if g == (label, passed) else None
            if g == (label, passed):
                b[mode].append(v)   # None = never bought, counted as 0%

# the finer groups feed the totals
for name, b in list(groups.items()):
    lab, pas = name.split(" / ")
    if lab != "all" and pas != "all":
        for tgt in (f"{lab} / all", f"all / {pas}", "all / all"):
            for m in b:
                groups[tgt][m] += b[m]


def summ(v):
    if not v:
        return None
    traded = len([x for x in v if x is not None])
    v = [x or 0.0 for x in v]
    return {"n": len(v), "traded": traded, "mean": round(st.mean(v), 3), "median": round(st.median(v), 3),
            "win": round(sum(x > 0 for x in v) / len(v), 3)}


print(json.dumps({"rows": len(rows), "groups": {k: {m: summ(v) for m, v in b.items()} for k, b in sorted(groups.items())}},
                 indent=1))
