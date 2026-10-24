"""Summary of the AlphaTrend 1H overfitting checks (scripts/robust_1h.py).

Portfolio = every pair of a basket with the same stake, month by month
(simple returns, trades by entry month). For the 20-pair basket ("main",
where the values were chosen) and the 10 pairs outside the choice ("hold"):

  1. the chosen cell (17 / 0.4) and the author's (14 / 1.0) year by year,
     at the site's costs and at double costs;
  2. walk-forward: every half year from 2021, the cell with the best last
     12 months (plain best, and best x solidity of its grid neighbours),
     then its next six months — values the test never saw, every time;
  3. PBO (CSCV, validation.probability_of_backtest_overfitting) over the
     336 cells, month by month;
  4. deflated Sharpe of the chosen cell, with 336 trials and with the
     ~9 000 the whole research tried;
  5. PBO over every long-only cell of the eighteen public strategies, by
     year (the strategy choice itself, not only the values);
  6. the chosen cell on MEXC's candles against Binance's.

    PYTHONPATH=backend python scripts/robust_1h_summary.py <rob dir> [<public dir> ...]
"""
from __future__ import annotations

import glob
import gzip
import json
import math
import os
import statistics as st
import sys
from itertools import combinations

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from app.analysis.validation import (  # noqa: E402
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
)

HOLD = set(os.environ.get("HOLD", "NEARUSDT,FILUSDT,UNIUSDT,AAVEUSDT,ALGOUSDT,VETUSDT,EOSUSDT,XTZUSDT,BCHUSDT,NEOUSDT").split(","))
CHOSEN, AUTHOR = "17,0.4", "14,1.0"
TRIALS_TOTAL = int(os.environ.get("TRIALS_TOTAL", "9000"))
FIRST = "2020-07"     # the BTC weekly EMA 21 is warm from here


def load(folder, prefix):
    out = []
    for f in sorted(glob.glob(os.path.join(folder, "**", f"{prefix}-*.json.gz"), recursive=True)):
        with gzip.open(f, "rt") as fh:
            out.append(json.load(fh))
    return out


def months_between(a, b):
    y, m = map(int, a.split("-"))
    out = []
    while f"{y}-{m:02d}" <= b:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def portfolio(pairs, key, months):
    """Equal-stake monthly return of a cell over the pairs that have it."""
    rows = []
    for p in pairs:
        cell = p["cells"].get(key)
        if cell is None:
            continue
        rows.append([cell.get(m, [0.0, 0])[0] for m in months])
    return np.mean(np.array(rows), axis=0) if rows else np.zeros(len(months))


def by_year(series, months):
    out = {}
    for v, m in zip(series, months):
        out[m[:4]] = out.get(m[:4], 0.0) + float(v)
    return {y: round(v) for y, v in out.items()}


def fmt_years(d):
    return " ".join(f"{y} {v:+d}" for y, v in d.items())


def grid_cells(pairs, cost):
    keys = sorted({k.split("|")[1] for k in pairs[0]["cells"] if k.startswith(cost + "|")},
                  key=lambda s: (int(s.split(",")[0]), float(s.split(",")[1])))
    periods = sorted({int(k.split(",")[0]) for k in keys})
    coeffs = sorted({float(k.split(",")[1]) for k in keys})
    return keys, periods, coeffs


def neighbours(key, periods, coeffs):
    p, c = int(key.split(",")[0]), float(key.split(",")[1])
    i, j = periods.index(p), coeffs.index(c)
    out = []
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if 0 <= i + di < len(periods) and 0 <= j + dj < len(coeffs):
            out.append(f"{periods[i + di]},{coeffs[j + dj]}")
    return out


def walk_forward(pairs, cost, months, solid):
    keys, periods, coeffs = grid_cells(pairs, cost)
    mat = {k: portfolio(pairs, f"{cost}|{k}", months) for k in keys}
    idx = {m: i for i, m in enumerate(months)}
    picks, oos, ins = [], {}, []
    for y in range(2021, 2027):
        for h, (a, b) in enumerate((("01", "06"), ("07", "12"))):
            t0, t1 = f"{y}-{a}", f"{y}-{b}"
            if t0 not in idx:
                continue
            i0 = idx[t0]
            i1 = idx[t1] + 1 if t1 in idx else len(months)
            tr0 = max(0, i0 - 12)
            score = {k: float(mat[k][tr0:i0].sum()) for k in keys}
            if solid:
                def sol(k):
                    s = score[k]
                    if s <= 0:
                        return s
                    near = [score[n] for n in neighbours(k, periods, coeffs)]
                    return s * max(0.0, min(1.0, st.median(near) / s))
                best = max(keys, key=sol)
            else:
                best = max(keys, key=lambda k: score[k])
            picks.append(f"{y}H{h + 1}:{best}")
            ins.append(score[best] / 2)                   # per half year
            for j in range(i0, i1):
                oos[months[j]] = float(mat[best][j])
    om = sorted(oos)
    yearly = by_year([oos[m] for m in om], om)
    halves = len(ins)
    eff = (sum(oos.values()) / max(1, halves)) / (st.mean(ins) or 1e-9) if ins else None
    return yearly, picks, eff


def custom_cscv(matrix):
    """CSCV with one block per row (years): too few rows for the site's
    12-block version. matrix: rows x candidates."""
    t, n = matrix.shape
    logits = []
    for tr in combinations(range(t), t // 2):
        te = [i for i in range(t) if i not in tr]
        a, b = matrix[list(tr)].sum(axis=0), matrix[te].sum(axis=0)
        w = int(np.argmax(a))
        rank = (np.argsort(np.argsort(b))[w] + 1) / (n + 1)
        logits.append(math.log(rank / (1 - rank)))
    return float(np.mean([x < 0 for x in logits])), len(logits), float(np.median(logits))


def main(rob_dir, public_dirs):
    pairs = load(rob_dir, "rob")
    if not pairs:
        print("::warning title=robust::no results")
        return 0
    last = max(m for p in pairs for c in p["cells"].values() for m in c)
    months = months_between(FIRST, last)
    baskets = {"main": [p for p in pairs if p["symbol"] not in HOLD],
               "hold": [p for p in pairs if p["symbol"] in HOLD]}
    notes = []

    # 1. chosen vs author, both costs
    rows = []
    for b, ps in baskets.items():
        if not ps:
            continue
        hold = {y: round(st.median([p["hold"][y] for p in ps if y in p["hold"]])) for y in ("2021", "2022", "2023", "2024", "2025")}
        rows.append(f"{b} ({len(ps)} pairs) B&H median " + fmt_years({y: v for y, v in hold.items()}))
        for name, cell in (("chosen 17/0.4", CHOSEN), ("author 14/1.0", AUTHOR)):
            for cost in ("base", "x2"):
                rows.append(f"{b} {name} {cost}: " + fmt_years(by_year(portfolio(ps, f"{cost}|{cell}", months), months)))
    notes.append(("1 chosen/author/costs", rows))

    # 2. walk-forward
    rows = []
    for b, ps in baskets.items():
        if not ps:
            continue
        for cost in ("base", "x2"):
            for solid in (False, True):
                yearly, picks, eff = walk_forward(ps, cost, months, solid)
                rows.append(f"{b} {cost} {'solid' if solid else 'best'}: OOS " + fmt_years(yearly)
                            + f" · efficiency {eff:.2f} · picks " + " ".join(picks))
    notes.append(("2 walk-forward", rows))

    # 3. PBO over the grid, 4. deflated Sharpe
    rows = []
    for b, ps in baskets.items():
        if not ps:
            continue
        for cost in ("base", "x2"):
            keys, _, _ = grid_cells(ps, cost)
            mat = np.column_stack([portfolio(ps, f"{cost}|{k}", months) for k in keys])
            pbo = probability_of_backtest_overfitting(mat, n_blocks=12)
            sr = []
            for j in range(mat.shape[1]):
                col = mat[:, j]
                sd = float(np.std(col, ddof=1))
                sr.append(float(np.mean(col) / sd) if sd > 0 else 0.0)
            var_sr = float(np.var(sr, ddof=1))
            ch = mat[:, keys.index(CHOSEN)]
            d1 = deflated_sharpe_ratio(ch, 336, trial_sharpe_variance=var_sr, periods_per_year=12)
            d2 = deflated_sharpe_ratio(ch, TRIALS_TOTAL, trial_sharpe_variance=var_sr, periods_per_year=12)
            best = keys[int(np.argmax(mat.sum(axis=0)))]
            rows.append(f"{b} {cost}: PBO {pbo.pbo:.2f} ({pbo.n_splits} splits, median logit {pbo.median_logit:.2f})"
                        f" · best over all months {best} · chosen Sharpe {d1.sharpe:.2f}/y"
                        f" · DSR 336 trials {d1.deflated:.2f} (threshold {d1.sharpe_threshold:.2f})"
                        f" · DSR {TRIALS_TOTAL} trials {d2.deflated:.2f} (threshold {d2.sharpe_threshold:.2f})"
                        f" · cells with positive total {int((mat.sum(axis=0) > 0).sum())}/{len(keys)}")
    notes.append(("3-4 PBO and deflated Sharpe", rows))

    # 5. PBO over the strategy choice (public runs, long only, by year)
    rows = []
    pub = [p for d in public_dirs for p in load(d, "r1h")]
    if pub:
        years = ["2021", "2022", "2023", "2024", "2025", "2026"]
        cells = sorted({k for p in pub for k in p["cells"] if "|L|" in k})
        cols, names = [], []
        for k in cells:
            vals = [p["cells"][k] for p in pub if k in p["cells"]]
            if len(vals) < 0.7 * len({p["symbol"] for p in pub}):
                continue
            cols.append([st.median([v[y][0] for v in vals if y in v]) for y in years])
            names.append(k)
        mat = np.array(cols).T
        if mat.ndim != 2 or mat.shape[1] < 2:
            rows.append("public results missing")
            notes.append(("5 strategy-choice PBO", rows))
            mat = None
    if pub and mat is not None:
        pbo, n_sp, lg = custom_cscv(mat)
        order = np.argsort(-mat.sum(axis=0))
        rows.append(f"all long-only cells of the 18 public strategies: {len(names)} candidates, "
                    f"PBO {pbo:.2f} over {n_sp} year splits (median logit {lg:.2f})")
        rows.append("top by all years: " + " | ".join(f"{names[i]} {mat[:, i].sum():+.0f}" for i in order[:6]))
        fams = {}
        for i, n in enumerate(names):
            fams.setdefault(n.split("|")[0], []).append(float(mat[:, i].sum()))
        rows.append("family medians (all cells, all years): " + " ".join(
            f"{f} {st.median(v):+.0f}" for f, v in sorted(fams.items(), key=lambda kv: -st.median(kv[1]))))
        notes.append(("5 strategy-choice PBO", rows))

    # 6. MEXC vs Binance
    rows, diffs = [], []
    for p in pairs:
        mx = p.get("mexc") or {}
        if "error" in mx or not mx:
            rows.append(f"{p['symbol']} mexc: {mx.get('error', 'missing')}")
            continue
        ms = [m for m in months if m >= mx["from"]]
        a = sum(mx["mexc"].get(m, [0, 0])[0] for m in ms)
        b = sum(mx["binance"].get(m, [0, 0])[0] for m in ms)
        ta = sum(mx["mexc"].get(m, [0, 0])[1] for m in ms)
        tb = sum(mx["binance"].get(m, [0, 0])[1] for m in ms)
        diffs.append(a - b)
        rows.append(f"{p['symbol']} since {mx['from']}: MEXC {a:+.0f}% ({ta}tr) vs Binance {b:+.0f}% ({tb}tr)")
    if diffs:
        rows.insert(0, f"median MEXC - Binance {st.median(diffs):+.0f} points over {len(diffs)} pairs")
    notes.append(("6 MEXC vs Binance", rows))

    for title, rs in notes:
        print(f"::notice title=robust {title}::" + " ‖ ".join(rs))
    with open("robust-1h.md", "w") as fh:
        for title, rs in notes:
            fh.write(f"## {title}\n\n" + "\n".join(f"- {r}" for r in rs) + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ".", sys.argv[2:]))
