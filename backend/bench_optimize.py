"""
Stability harness for the parameter optimiser (pipeline phase A).

Measures the quantity the redesign exists to reduce: how much the optimiser's
answer changes when only the random seed changes. Same data, same strategy,
same budget — only the seed differs, so every point of spread it reports is
selection noise rather than information.

This is the baseline. Any later claim that the plateau-search pipeline is more
stable has to be made against numbers produced by this script, not against an
impression.

Usage
    python bench_optimize.py                       # synthetic, all strategies
    python bench_optimize.py --runs 30 --trials 200
    python bench_optimize.py --csv baseline.csv    # save per-run detail

Reported per (strategy, series):
    cv_is      coefficient of variation of the in-sample return across runs
    cv_oos     same, out-of-sample — the one that matters
    spread     max/min ratio of in-sample return, the "17x vs 40x" number
    param_dist mean pairwise distance between selected parameter vectors,
               normalised per dimension to [0,1]; 0 = every run agreed
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analysis.optimize import _STRATEGY_SPACES, optimize_strategy
from app.analysis.regime import analyze_regime, regime_gate


# --- synthetic series with controlled character ------------------------------


def make_series(kind: str, n: int = 1200, seed: int = 0) -> pd.DataFrame:
    """Build an OHLCV frame whose statistical character we control.

    'pump' reproduces the KASUSDT shape that motivated this work: most of the
    total return concentrated in a few explosive moves, which is precisely the
    setting where which-configuration-was-long-during-the-pump dominates the
    result and the optimiser turns into a lottery.
    """
    rng = np.random.default_rng(seed)
    if kind == "random_walk":
        r = rng.normal(0.0005, 0.025, n)
    elif kind == "trending":
        r = np.zeros(n)
        e = rng.normal(0.0004, 0.022, n)
        for i in range(1, n):
            r[i] = 0.25 * r[i - 1] + e[i]
    elif kind == "mean_reverting":
        r = np.zeros(n)
        e = rng.normal(0.0003, 0.022, n)
        for i in range(1, n):
            r[i] = -0.25 * r[i - 1] + e[i]
    elif kind == "pump":
        r = rng.normal(0.0004, 0.035, n)
        for start in (int(n * 0.30), int(n * 0.62), int(n * 0.85)):
            r[start:start + 12] += 0.07
    else:
        raise ValueError(f"unknown series kind {kind!r}")

    close = 100.0 * np.exp(np.cumsum(r))
    return pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.003, n)),
            "high": close * (1 + np.abs(rng.normal(0, 0.012, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.012, n))),
            "close": close,
            "volume": rng.uniform(1e6, 5e6, n),
        },
        index=pd.date_range("2022-01-01", periods=n, freq="D"),
    )


# --- parameter distance ------------------------------------------------------


def _param_distance(param_sets: list[dict]) -> float | None:
    """Mean pairwise L2 distance between parameter vectors, each dimension
    min-max normalised across the observed sets. 0 means every run landed on
    the same configuration; ~0.5 means they are scattered across the space."""
    if len(param_sets) < 2:
        return None
    keys = sorted(set().union(*(set(p) for p in param_sets)))
    numeric = [k for k in keys if all(isinstance(p.get(k), (int, float)) and not isinstance(p.get(k), bool) for p in param_sets)]
    if not numeric:
        return None

    mat = np.array([[float(p[k]) for k in numeric] for p in param_sets])
    lo, hi = mat.min(axis=0), mat.max(axis=0)
    span = np.where(hi - lo > 0, hi - lo, 1.0)
    norm = (mat - lo) / span

    dists = [
        float(np.linalg.norm(norm[i] - norm[j]) / np.sqrt(len(numeric)))
        for i in range(len(norm))
        for j in range(i + 1, len(norm))
    ]
    return statistics.fmean(dists) if dists else None


def _cv(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None and np.isfinite(v)]
    if len(vals) < 2:
        return None
    mean = statistics.fmean(vals)
    if abs(mean) < 1e-9:
        return None
    return statistics.stdev(vals) / abs(mean)


@dataclass
class RunResult:
    strategy: str
    series: str
    seed: int
    is_return: float
    oos_return: float | None
    overfitted: bool
    num_trades: int
    shortlist: int
    params: dict
    seconds: float


def bench(
    strategies: list[str],
    series_kinds: list[str],
    runs: int,
    trials: int,
    n_candles: int,
) -> list[RunResult]:
    out: list[RunResult] = []
    for kind in series_kinds:
        df = make_series(kind, n=n_candles, seed=42)
        rep = analyze_regime(df)
        print(f"\n=== series '{kind}'  n={len(df)}  "
              f"VR={rep.variance_ratio:.3f} z={rep.vr_z:+.2f} verdict={rep.verdict}")

        for strat in strategies:
            gate = regime_gate(df, strat, report=rep)
            print(f"\n  {strat}")
            print(f"    gate: {'PASS' if gate.passed else 'BLOCK'} — {gate.reason}")
            print(f"    {'seed':>5} {'IS %':>10} {'OOS %':>9} {'trades':>7} {'top':>4} {'s':>6}")

            for seed in range(runs):
                t0 = time.perf_counter()
                params, bt, _ev, oos, ovf, top = optimize_strategy(
                    strat, df, {}, trials=trials, seed=seed
                )
                el = time.perf_counter() - t0
                out.append(RunResult(
                    strategy=strat, series=kind, seed=seed,
                    is_return=bt.total_return_pct, oos_return=oos, overfitted=ovf,
                    num_trades=bt.num_trades, shortlist=len(top),
                    params=params, seconds=el,
                ))
                oos_s = f"{oos:+9.1f}" if oos is not None else "        —"
                print(f"    {seed:>5} {bt.total_return_pct:>+10.1f} {oos_s} "
                      f"{bt.num_trades:>7} {len(top):>4} {el:>6.1f}")
    return out


def summarise(results: list[RunResult]) -> None:
    print("\n" + "=" * 96)
    print("BASELINE — dispersion caused by the seed alone (same data, same budget)")
    print("=" * 96)
    print(f"{'strategy':<38}{'series':<16}{'cv_is':>8}{'cv_oos':>9}{'spread':>9}{'param_dist':>12}")
    print("-" * 96)

    keys = sorted({(r.strategy, r.series) for r in results})
    for strat, series in keys:
        grp = [r for r in results if r.strategy == strat and r.series == series]
        is_vals = [r.is_return for r in grp]
        oos_vals = [r.oos_return for r in grp if r.oos_return is not None]

        cv_is = _cv(is_vals)
        cv_oos = _cv(oos_vals)
        pos = [v for v in is_vals if v > 0]
        spread = (max(pos) / min(pos)) if len(pos) >= 2 and min(pos) > 0 else None
        pdist = _param_distance([r.params for r in grp])

        def f(v, fmt):
            return format(v, fmt) if v is not None else "—"

        print(f"{strat:<38}{series:<16}{f(cv_is,'>8.1%')}{f(cv_oos,'>9.1%')}"
              f"{f(spread,'>8.1f')}x{f(pdist,'>12.3f')}")

    secs = [r.seconds for r in results]
    print("-" * 96)
    print(f"{len(results)} runs · {statistics.fmean(secs):.1f}s mean per run · "
          f"{sum(secs):.0f}s total")
    print("\nHow to read this: cv_oos is the headline. It is the run-to-run spread of the")
    print("number the user is shown, produced with identical inputs. Every point of it is")
    print("selection noise. spread is the same thing in the form it was first reported —")
    print("the ratio between the luckiest and unluckiest run, i.e. the '17x vs 40x' gap.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=12, help="seeds per (strategy, series)")
    ap.add_argument("--trials", type=int, default=200, help="optimiser budget per run")
    ap.add_argument("--candles", type=int, default=1200)
    ap.add_argument("--strategies", nargs="*", default=None)
    ap.add_argument("--series", nargs="*", default=["pump", "trending", "mean_reverting"])
    ap.add_argument("--csv", type=str, default=None, help="write per-run detail here")
    args = ap.parse_args(argv)

    strategies = args.strategies or list(_STRATEGY_SPACES)
    unknown = [s for s in strategies if s not in _STRATEGY_SPACES]
    if unknown:
        print(f"unknown strategies: {unknown}\navailable: {list(_STRATEGY_SPACES)}", file=sys.stderr)
        return 2

    results = bench(strategies, args.series, args.runs, args.trials, args.candles)
    summarise(results)

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["strategy", "series", "seed", "is_return_pct", "oos_return_pct",
                        "overfitted", "num_trades", "shortlist", "seconds", "params"])
            for r in results:
                w.writerow([r.strategy, r.series, r.seed, f"{r.is_return:.4f}",
                            "" if r.oos_return is None else f"{r.oos_return:.4f}",
                            r.overfitted, r.num_trades, r.shortlist,
                            f"{r.seconds:.3f}", r.params])
        print(f"\nper-run detail written to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
