"""Summary of the 1H test environment (scripts/research_1h.py): reads every
r1h-<PAIR>.json.gz and, for each variant (family | L or LS | regime):

  common  ONE set of values for every pair — the cell with the best median
          yearly return over the pairs on the TRAIN years, weighted by how
          well its ±1-step neighbours hold it (the site's "most solid", so a
          lone spike is not chosen). Then its 2021 and 2022, never seen.
  pair    each pair its own values, the same choice on its own train years
          (what the Lab's Max return does), then 2021 and 2022.

Writes results-1h.md and prints one ::notice per family.

    python scripts/research_1h_summary.py <dir with r1h-*.json.gz>
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import statistics as st
import sys

TRAIN_FROM = int(os.environ.get("TRAIN_FROM", "2023"))
TEST_YEARS = tuple(int(y) for y in os.environ.get("TEST_YEARS", "2021,2022").split(","))
MAX_DD = 60.0          # the site's drawdown cap, per year here
MIN_TRADES = 3         # a year, on the judged train years (site rule)


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 1) if xs else None


def load(folder):
    out = []
    for f in sorted(glob.glob(os.path.join(folder, "**", "r1h-*.json.gz"), recursive=True)):
        with gzip.open(f, "rt") as fh:
            out.append(json.load(fh))
    return out


def split(key):
    fam, mode, rg, vals = key.split("|")
    return f"{fam}|{mode}|{rg}", tuple(vals.split(","))


def train_score(cell, train_years):
    """Simple return a year on the train years, None if the site's limits fail."""
    ys = [y for y in train_years if y in cell]
    if not ys:
        return None
    full = ys[:-1] if len(ys) > 1 else ys          # last year partial: no trade count rule
    if any(cell[y][1] == 0 for y in full) or sum(cell[y][1] for y in full) < MIN_TRADES * len(full):
        return None
    if any(cell[y][2] > MAX_DD for y in ys):
        return None
    return sum(cell[y][0] for y in ys) / len(ys)


def neighbours(vals, grid_vals):
    out = []
    for d, v in enumerate(vals):
        axis = grid_vals[d]
        i = axis.index(v)
        for j in (i - 1, i + 1):
            if 0 <= j < len(axis):
                out.append(vals[:d] + (axis[j],) + vals[d + 1:])
    return out


def solid_pick(scores: dict):
    """Best score × solidity (median neighbour / own, clipped 0..1)."""
    axes = [sorted({k[d] for k in scores}, key=float) for d in range(len(next(iter(scores))))]
    best = None
    for k, s in scores.items():
        if s is None or s <= 0:
            continue
        # a neighbour outside the limits counts as nothing earned
        near = [scores.get(n) or 0.0 for n in neighbours(k, axes)]
        if not near:
            continue
        sol = max(0.0, min(1.0, st.median(near) / s))
        if best is None or (s * sol, s) > best[0]:
            best = ((s * sol, s), k, round(sol, 2))
    return best


def main(folder):
    pairs = load(folder)
    if not pairs:
        print("::warning title=1h summary::no results")
        return 0
    years = sorted({y for p in pairs for c in p["cells"].values() for y in c})
    train_years = [y for y in years if int(y) >= TRAIN_FROM]
    tests = [str(y) for y in TEST_YEARS if str(y) in years]
    variants: dict[str, dict] = {}
    for p in pairs:
        for key, cell in p["cells"].items():
            var, vals = split(key)
            variants.setdefault(var, {}).setdefault(vals, {})[p["symbol"]] = cell
    lines = [f"# 1H test environment — {len(pairs)} pairs, choice on {train_years[0]}–{train_years[-1]}, "
             f"never seen: {', '.join(tests)}", ""]
    bh = {y: med([p["hold"].get(y) for p in pairs]) for y in years}
    lines.append("Buy & hold, median: " + " · ".join(f"{y} {v:+.0f}%" for y, v in bh.items() if v is not None))
    lines.append("")
    rows = []
    for var, cells in sorted(variants.items()):
        # common values: median over pairs of each pair's train score
        common = {}
        for vals, by_pair in cells.items():
            sc = [train_score(c, train_years) for c in by_pair.values()]
            ok = [s for s in sc if s is not None]
            common[vals] = st.median(ok) if len(ok) >= 0.7 * len(by_pair) else None
        pick = solid_pick(common)
        row = {"var": var}
        if pick:
            _, vals, sol = pick
            by_pair = cells[vals]
            row["common"] = {
                "vals": ",".join(vals), "sol": sol, "train": round(common[vals], 1),
                **{y: med([c[y][0] for c in by_pair.values() if y in c]) for y in years},
                **{f"pos{y}": sum(1 for c in by_pair.values() if y in c and c[y][0] > 0) for y in tests},
                **{f"worst{y}": min((c[y][0] for c in by_pair.values() if y in c), default=None) for y in tests},
                **{f"tr{y}": med([c[y][1] for c in by_pair.values() if y in c]) for y in tests},
                **{f"dd{y}": med([c[y][2] for c in by_pair.values() if y in c]) for y in tests},
                "n": sum(1 for c in by_pair.values() if tests[0] in c),
            }
        # each pair its own values
        own = {y: [] for y in tests}
        for p in pairs:
            sc = {vals: train_score(by_pair[p["symbol"]], train_years)
                  for vals, by_pair in cells.items() if p["symbol"] in by_pair}
            if not sc:
                continue
            pk = solid_pick(sc)
            if pk:
                c = cells[pk[1]][p["symbol"]]
                for y in tests:
                    if y in c:
                        own[y].append(c[y][0])
        # the author's own values (public_1h.py: every scale factor at 1)
        dflt = next((v for v in cells if all(float(x) == 1.0 for x in v)), None)
        if dflt is not None and "|" in var and var.split("|")[0] not in ("ST", "DC", "EX", "LZ"):
            bp = cells[dflt]
            sc = [train_score(c, train_years) for c in bp.values()]
            row["default"] = {
                "train": med([sum(c[y][0] for y in train_years if y in c) / max(1, len(train_years)) for c in bp.values()]),
                "admitted": sum(1 for x in sc if x is not None),
                **{y: med([c[y][0] for c in bp.values() if y in c]) for y in years},
                **{f"pos{y}": sum(1 for c in bp.values() if y in c and c[y][0] > 0) for y in tests},
                **{f"tr{y}": med([c[y][1] for c in bp.values() if y in c]) for y in tests},
            }
        row["pair"] = {y: med(v) for y, v in own.items()}
        row["pair_pos"] = {y: f"{sum(1 for x in v if x > 0)}/{len(v)}" for y, v in own.items()}
        rows.append(row)

    def fmt(r):
        c = r.get("common")
        if not c:
            d = r.get("default")
            tail = (" · author's values: " + " ".join(f"{y} {d[y]:+.0f}% ({d['pos' + y]}+)" for y in tests)) if d else ""
            return f"{r['var']}: no value holds the limits" + tail
        t = " ".join(f"{y} {c[y]:+.0f}% ({c['pos' + y]}/{c['n']}+, worst {c['worst' + y]:+.0f}, "
                     f"{c['tr' + y]:.0f}tr, dd {c['dd' + y]:.0f})" for y in tests)
        ins = " ".join(f"{y} {c[y]:+.0f}" for y in train_years if c.get(y) is not None)
        pp = " ".join(f"{y} {r['pair'][y]:+.0f}% ({r['pair_pos'][y]})" for y in tests if r["pair"][y] is not None)
        out = f"{r['var']} [{c['vals']}] sol {c['sol']} train {c['train']:+.0f}%/y ({ins}) · {t} · own values: {pp}"
        d = r.get("default")
        if d:
            out += " · author's values: train " + f"{d['train']:+.0f}%/y " + " ".join(
                f"{y} {d[y]:+.0f}% ({d['pos' + y]}+, {d['tr' + y]:.0f}tr)" for y in tests)
        return out

    # SHOW_MODES=L: only the long-only rows (Lorenzo, 24/10: "la strategia
    # deve essere solo long piu' uscita, quindi reversal")
    show = set(os.environ.get("SHOW_MODES", "L,LS").split(","))
    rows = [r for r in rows if r["var"].split("|")[1] in show]
    shown = []
    for fam in sorted({r["var"].split("|")[0] for r in rows}):
        fam_rows = [fmt(r) for r in rows if r["var"].startswith(fam + "|")]
        lines += [f"## {fam}", ""] + [f"- {x}" for x in fam_rows] + [""]
        shown += fam_rows
    # GitHub keeps 10 notices per step: every row in at most 7 of them
    per = max(1, -(-len(shown) // 7))
    for k in range(0, len(shown), per):
        print(f"::notice title=1h rows {k // per + 1}::" + " ‖ ".join(shown[k:k + per]))
    # every year at once: the worst yearly median of the common values
    full = [y for y in years if y != years[-1]]
    ranked = sorted((r for r in rows if r.get("common")),
                    key=lambda r: (min(r["common"][y] for y in full), sum(r["common"][y] for y in full)),
                    reverse=True)
    top = [f"{r['var']} [{r['common']['vals']}] " + " ".join(f"{y} {r['common'][y]:+.0f}" for y in full)
           for r in ranked[:12]]
    lines += ["## Ranking (worst yearly median, every full year)", ""] + [f"- {x}" for x in top]
    print("::notice title=1h ranking::" + " ‖ ".join(top))
    # CELLS="AT|L|w21|0.714286,0.5;...": these cells as they are — values
    # chosen on one basket, read on pairs that never took part in the choice
    want = [c for c in os.environ.get("CELLS", "").split(";") if c]
    if want:
        out = []
        for key in want:
            var, vals = split(key)
            by_pair = variants.get(var, {}).get(vals, {})
            if not by_pair:
                out.append(f"{key}: not run")
                continue
            out.append(f"{key} ({len(by_pair)} pairs) " + " ".join(
                f"{y} {med([c[y][0] for c in by_pair.values() if y in c]):+.0f}%"
                f" ({sum(1 for c in by_pair.values() if y in c and c[y][0] > 0)}+)" for y in years))
        print("::notice title=1h cells::" + " ‖ ".join(out))
    print("::notice title=1h buy&hold::" + lines[2])
    with open("results-1h.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open("results-1h.json", "w") as fh:
        json.dump({"bh": bh, "rows": rows}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
