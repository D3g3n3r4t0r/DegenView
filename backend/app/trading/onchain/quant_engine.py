"""Deterministic, budgeted timeframe research. No network, LLM or order execution.

OHLCV timestamps are candle OPEN times. Signals use only complete, contiguous
candles; a fill uses the following base candle's open. Policy changes while
flat only: an open position retains its entry timeframe. Dataset labels and
point-in-time eligibility are supplied by the collector, never reconstructed
from today's leaderboard.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

VERSION = "quant-v1"
BASE = 300
ALLOWED = (300, 900, 3600, 14400, 28800, 86400)
MAX_CANDIDATES = 32
MAX_CASES = 2000
MAX_BARS = 30000
MAX_TOTAL_BARS = 250000
FEED = "engine_5m_mixed_v1"


def strategy_code_hash():
    return hashlib.sha256((Path(__file__).parents[2] / "analysis/strategies.py").read_bytes()).hexdigest()


def fingerprint(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


@dataclass(frozen=True)
class Policy:
    # (minimum token age in seconds, timeframe in seconds); search inputs,
    # not a production schedule. Ages/timeframes must increase monotonically.
    stages: tuple[tuple[int, int], ...]
    strategy: str = "Lorenzo HF (minuti on-chain)"

    def __post_init__(self):
        if not self.stages or len(self.stages) > 6 or self.stages[0][0] != 0:
            raise ValueError("policy must start at age zero with at most six stages")
        if self.strategy not in ("Lorenzo HF (minuti on-chain)", "Lorenzo (trend-follower)"):
            raise ValueError("only existing trend followers are supported")
        for i, (age, tf) in enumerate(self.stages):
            if type(age) is not int or age < 0 or type(tf) is not int or tf not in ALLOWED:
                raise ValueError("invalid age/timeframe")
            if i and (age <= self.stages[i - 1][0] or tf <= self.stages[i - 1][1]):
                raise ValueError("stages must increase in age and timeframe")

    @property
    def id(self):
        return fingerprint(asdict(self))[:20]

    def interval(self, age):
        return next(tf for minimum, tf in reversed(self.stages) if age >= minimum)


def candidates(timeframes, transitions, strategy="Lorenzo HF (minuti on-chain)"):
    """Explicit bounded grid; fixed baselines plus two-stage hypotheses."""
    tfs = sorted(set(timeframes))
    out = [Policy(((0, tf),), strategy) for tf in tfs]
    out += [Policy(((0, a), (age, b)), strategy) for age in sorted(set(transitions))
            for a in tfs for b in tfs if b > a]
    if not out or len(out) > MAX_CANDIDATES:
        raise ValueError("candidate budget exceeded or empty")
    return out


def clean_bars(rows):
    if len(rows) > MAX_BARS:
        raise ValueError("bar budget exceeded")
    result = []
    previous = -1
    for row in rows:
        if len(row) != 6 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                or not math.isfinite(v) for v in row):
            raise ValueError("invalid OHLCV")
        t, o, h, low, c, v = row
        if t != int(t) or t % BASE or t <= previous or min(o, h, low, c) <= 0 or v < 0:
            raise ValueError("unordered, duplicate, unaligned or invalid candle")
        if h < max(o, c, low) or low > min(o, c, h):
            raise ValueError("inconsistent OHLC")
        result.append(list(row))
        previous = t
    return result


def aggregate(rows, tf, now):
    """Never fill gaps or complete a partial candle with future information."""
    groups = {}
    for r in rows:
        key = int(r[0]) // tf * tf
        if key + tf <= now:
            groups.setdefault(key, []).append(r)
    out = []
    for key, block in sorted(groups.items()):
        if [r[0] for r in block] != list(range(key, key + tf, BASE)):
            continue
        out.append([key, block[0][1], max(r[2] for r in block), min(r[3] for r in block),
                    block[-1][4], sum(r[5] for r in block)])
    return out


def existing_signals(rows, strategy):
    """Reuse the application's actual trend implementation, not an imitation."""
    import pandas as pd
    from app.analysis.strategies import STRATEGY_REGISTRY, spot_only
    if len(rows) < 3:
        return [(False, False)] * len(rows)
    frame = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"])
    frame.index = pd.to_datetime(frame.pop("t"), unit="s", utc=True)
    sig = spot_only(STRATEGY_REGISTRY[strategy](frame.astype(float), None))
    return [(bool(a), bool(b)) for a, b in zip(sig.entry_long.fillna(False), sig.exit_long.fillna(False))]


def signal_table(rows, tf, now, strategy, provider):
    bars = aggregate(rows, tf, now)
    table = {}
    # Indicators are restarted after gaps. A discontinuous series is not
    # silently treated as a regular timeframe.
    blocks = []
    for r in bars:
        if not blocks or r[0] != blocks[-1][-1][0] + tf:
            blocks.append([])
        blocks[-1].append(r)
    for block in blocks:
        signals = provider(block, strategy)
        if len(signals) != len(block):
            raise ValueError("signal provider length mismatch")
        for r, sig in zip(block, signals):
            table[r[0] + tf] = sig
    return table


def replay(case, policy, *, commission=0.003, slippage=0.01, provider=existing_signals, tables=None):
    """One token, one normalized unit of capital. No overlapping portfolio claim."""
    rows = clean_bars(case["bars"])
    start, end, born = case["start"], case["end"], case.get("born")
    if not (0 <= commission < 0.1 and 0 <= slippage < 0.5):
        raise ValueError("invalid costs")
    if not (isinstance(start, (int, float)) and isinstance(end, (int, float))
            and math.isfinite(start) and math.isfinite(end) and end > start):
        raise ValueError("invalid observation window")
    if born is None or not isinstance(born, (int, float)) or not math.isfinite(born) or born > start:
        return {"state": "unavailable", "reason": "verified token birth required", "eligible": False}
    if case.get("gem_eligible") is not True or case.get("eligibility_at", end + 1) > start:
        return {"state": "unavailable", "reason": "point-in-time gem eligibility required", "eligible": False}
    if case.get("risk_blocked") is True:
        return {"eligible": True, "state": "out", "ret": 0.0, "drawdown": 0.0, "entries": 0,
                "events": [], "reason": "reviewed incident rule", "policy_id": policy.id}
    if not rows or rows[-1][0] + BASE < end or rows[0][0] > start:
        return {"state": "unavailable", "reason": "incomplete observation window", "eligible": False}
    # Check only post-alert market coverage. Gaps must not improve a backtest.
    observed = [r[0] for r in rows if start <= r[0] < end]
    if not observed or observed[0] - start >= BASE or end - observed[-1] > BASE or any(b - a != BASE for a, b in zip(observed, observed[1:])):
        return {"state": "unavailable", "reason": "missing base candles", "eligible": False}
    tf_tables = tables if tables is not None else {}
    for _, tf in policy.stages:
        key = (tf, policy.strategy)
        if key not in tf_tables:
            tf_tables[key] = signal_table(rows, tf, end, policy.strategy, provider)
    cash, qty, peak, dd = 1.0, 0.0, 1.0, 0.0
    entry_tf, entry_at, entry_price = None, None, None
    events = []
    last_mark = None
    shock_at = case.get("untradeable_at")
    for t, o, h, low, c, vol in rows:
        if t < start or t >= end:
            continue
        if shock_at is not None and t >= shock_at:
            if qty:
                events.append({"t": t, "side": "loss", "reason": "untradeable", "price": 0})
                cash, qty = 0.0, 0.0
                dd = 1.0
            break
        tf = entry_tf if qty else policy.interval(t - born)
        buy, sell = tf_tables[(tf, policy.strategy)].get(t, (False, False))
        # Alert and a past trend are never entry signals. The signal candle
        # must begin no earlier than the eligibility/observation start.
        if qty and sell:
            cash = qty * o * (1 - slippage) * (1 - commission)
            qty = 0.0
            events.append({"t": t, "side": "sell", "price": o, "tf": tf, "reason": "trend_exit"})
        elif not qty and buy and not sell and t - tf >= start:
            qty = cash * (1 - commission) / (o * (1 + slippage))
            cash = 0.0
            entry_tf, entry_at, entry_price = tf, t, o
            events.append({"t": t, "side": "buy", "price": o, "tf": tf, "reason": "trend_entry"})
        # Mark only complete base candles. Use liquidation value after costs.
        if t + BASE <= end:
            last_mark = c
            value = cash + qty * c * (1 - slippage) * (1 - commission)
            peak = max(peak, value)
            dd = max(dd, 1 - value / peak)
    value = cash + qty * (last_mark or entry_price or 0) * (1 - slippage) * (1 - commission)
    return {"eligible": True, "state": "in" if qty else "out", "ret": value - 1,
            "drawdown": dd, "entries": sum(e["side"] == "buy" for e in events), "events": events,
            "in_at": entry_at if qty else None, "entry": entry_price if qty else None,
            "mark": last_mark, "timeframe": entry_tf if qty else None, "policy_id": policy.id}


def metrics(results):
    usable = [r for r in results if r.get("eligible")]
    returns = [r["ret"] for r in usable]
    return {"n": len(usable), "unavailable": len(results) - len(usable),
            "median_return": statistics.median(returns) if returns else None,
            "worst_return": min(returns) if returns else None,
            "max_drawdown": max((r["drawdown"] for r in usable), default=None),
            "entries": sum(r["entries"] for r in usable)}


def experiment(cases, policies, *, train_end, validation_end, commission=0.003, slippage=0.01,
               min_cases=20, min_entries=10, provider=existing_signals):
    """Purged chronological train/validation/untouched-test cohorts by project.

    Winner is selected ONLY on train. Validation chooses it or the best fixed
    baseline; test may reject, never select another winner. No online promotion.
    """
    if not 1 <= len(policies) <= MAX_CANDIDATES or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError("research budget exceeded or empty input")
    if sum(len(c["bars"]) for c in cases) > MAX_TOTAL_BARS:
        raise ValueError("total candle budget exceeded")
    if min_cases < 2 or min_entries < 1 or train_end >= validation_end:
        raise ValueError("invalid research bounds")
    if any(c.get("feed") != FEED for c in cases):
        raise ValueError("declare the supported point-in-time Engine candle feed; other feeds need a separate adapter")
    if len({p.id for p in policies}) != len(policies):
        raise ValueError("duplicate policy")
    if not any(len(p.stages) == 1 for p in policies):
        raise ValueError("fixed baseline required")
    keys = [(c["chain"], c["token"]) for c in cases]
    if len(set(keys)) != len(keys):
        raise ValueError("one independent window per chain/token required")
    cohorts = [[], [], []]
    purged = 0
    for c in cases:
        if c["end"] <= train_end:
            cohorts[0].append(c)
        elif c["start"] >= train_end and c["end"] <= validation_end:
            cohorts[1].append(c)
        elif c["start"] >= validation_end:
            cohorts[2].append(c)
        else:
            purged += 1
    table_cache = {}
    def run(p, group):
        out = []
        for c in group:
            cache = table_cache.setdefault((c["chain"], c["token"]), {})
            out.append(replay(c, p, commission=commission, slippage=slippage, provider=provider, tables=cache))
        return metrics(out)
    train = {p.id: run(p, cohorts[0]) for p in policies}
    def rank(p):
        m = train[p.id]
        # Penalty is predeclared; never optimize this weight on holdout.
        utility = m["median_return"] - m["max_drawdown"] if m["n"] else -math.inf
        return (-utility, len(p.stages), p.id)
    eligible = [p for p in policies if train[p.id]["n"] >= min_cases and train[p.id]["entries"] >= min_entries and train[p.id]["unavailable"] == 0]
    report = {"version": VERSION, "strategy_code_hash": strategy_code_hash(), "feed": FEED,
              "dataset_hash": fingerprint(cases), "policies": [asdict(p) for p in policies],
              "costs": {"commission": commission, "slippage": slippage},
              "bounds": {"train_end": train_end, "validation_end": validation_end,
                         "min_cases": min_cases, "min_entries": min_entries},
              "train": train, "purged": purged, "cohort_sizes": [len(g) for g in cohorts],
              "status": "not_validated", "selected": None, "llm_calls": 0}
    fixed = sorted((p for p in eligible if len(p.stages) == 1), key=rank)
    if not fixed:
        report["reason"] = "insufficient training evidence for a fixed baseline"
        return report
    winner, baseline = sorted(eligible, key=rank)[0], fixed[0]
    val_w, val_b = run(winner, cohorts[1]), run(baseline, cohorts[1])
    def sufficient(m):
        return m["n"] >= min_cases and m["entries"] >= min_entries and m["unavailable"] == 0
    if not sufficient(val_w) or not sufficient(val_b):
        report["reason"] = "insufficient validation coverage/trades"
        return report
    if (val_w["median_return"] <= val_b["median_return"] or val_w["max_drawdown"] > val_b["max_drawdown"]):
        winner = baseline
    report["validation"] = {"candidate": val_w, "baseline": val_b}
    report["selected"] = asdict(winner)
    test = run(winner, cohorts[2])
    baseline_test = run(baseline, cohorts[2])
    stress = metrics([replay(c, winner, commission=commission, slippage=min(slippage * 2, 0.49), provider=provider,
                             tables=table_cache[(c["chain"], c["token"])]) for c in cohorts[2]])
    report.update(test=test, stress=stress, baseline_test=baseline_test)
    beats_fixed = winner.id == baseline.id or (sufficient(test) and sufficient(baseline_test)
                  and test["median_return"] > baseline_test["median_return"]
                  and test["max_drawdown"] <= baseline_test["max_drawdown"])
    if sufficient(test) and sufficient(stress) and beats_fixed and test["median_return"] > 0 and stress["median_return"] > 0:
        report.update(status="review_required", reason="holdout passed; human review and paper execution still required")
    else:
        report["reason"] = "holdout or cost stress failed; no production policy"
    return report
