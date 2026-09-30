"""Append-only incident evidence in the shared observatory SQLite file.

Legacy 'rug' means a detector fired, not verified fraud. Never silently promote
that label. This archive also keeps non-rugs/unknowns to expose selection bias.
No network or language model calls; exact immutable versions are deduplicated.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from contextlib import contextmanager

from app.trading.onchain.quant_engine import fingerprint
from app.trading.onchain.storage import data_file


@contextmanager
def connect(path=None):
    db = sqlite3.connect(path or data_file("observatory.sqlite3"), timeout=5)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS quant_incidents "
                   "(digest TEXT PRIMARY KEY, project TEXT NOT NULL, observed REAL NOT NULL, payload TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS quant_incidents_project ON quant_incidents(project,observed)")
        db.execute("CREATE TABLE IF NOT EXISTS quant_research_cases "
                   "(project TEXT PRIMARY KEY, captured REAL NOT NULL, payload TEXT NOT NULL)")
        with db:
            yield db
    finally:
        db.close()


def record(entries, *, path=None, now=None):
    """Copy exact existing public outcome facts, including missingness, before pruning."""
    now = time.time() if now is None else now
    count = 0
    with connect(path) as db:
        for e in entries:
            if not e.get("chain") or not e.get("token_address"):
                continue
            row = {k: e.get(k) for k in ("chain", "token_address", "symbol", "at", "features", "decision",
                                        "entry", "rug", "rug_at", "rug_why", "max_ret", "min_ret", "closed")}
            row["classification"] = "suspected_incident" if e.get("rug") else "observed_non_rug" if e.get("rug") is False else "unknown"
            row["label_source"] = "outcomes_heuristic_v1"
            row["confirmed_fraud"] = False
            payload = json.dumps(row, sort_keys=True, allow_nan=False)
            key = json.dumps([e["chain"], e["token_address"]])
            cursor = db.execute("INSERT OR IGNORE INTO quant_incidents VALUES(?,?,?,?)",
                                (fingerprint(row), key, now, payload))
            count += cursor.rowcount
    return count


def pattern_report(rows, feature, threshold, *, direction="le", min_support=20):
    """Descriptive threshold audit only. Input must be point-in-time features.

    No automatic blacklist: incident associations require held-out confirmation
    and an approved false-rejection budget before affecting eligibility.
    """
    if direction not in ("le", "ge") or min_support < 2:
        raise ValueError("invalid pattern audit")
    matched, unmatched, unknown = [], [], 0
    for r in rows:
        value = (r.get("features") or {}).get(feature)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or type(r.get("rug")) is not bool:
            unknown += 1
            continue
        hit = value <= threshold if direction == "le" else value >= threshold
        (matched if hit else unmatched).append(bool(r["rug"]))
    healthy = sum(not v for v in matched + unmatched)
    false_rejects = sum(not v for v in matched)
    return {"feature": feature, "threshold": threshold, "direction": direction,
            "matched": len(matched), "incident_matches": sum(matched), "unmatched": len(unmatched),
            "unknown": unknown, "false_rejections": false_rejects,
            "false_rejection_rate": false_rejects / healthy if healthy else None,
            "incident_rate_matched": sum(matched) / len(matched) if matched else None,
            "incident_rate_unmatched": sum(unmatched) / len(unmatched) if unmatched else None,
            "status": "hypothesis" if min(len(matched), len(unmatched)) >= min_support else "insufficient_data",
            "automatic_veto": False, "label_warning": "Legacy incidents are not confirmed fraud"}


def validate_patterns(rows, rules, *, train_end, validation_end, min_support=20, max_false_rejection=.05):
    """Select one threshold on train; validate its incident lift AND healthy cost.

    Caller supplies observed_at (features) and label_at (outcome availability).
    Windows crossing cutoffs are purged, and repeated projects are rejected.
    A passed result remains a review proposal, never a self-installed blacklist.
    """
    if not 1 <= len(rules) <= 32 or min_support < 2 or not 0 <= max_false_rejection <= .2:
        raise ValueError("invalid pattern budget")
    if train_end >= validation_end or len(rows) > 10000:
        raise ValueError("invalid dataset bounds")
    keys = [(r["chain"], r["token_address"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate project in pattern dataset")
    groups = [[], [], []]
    for r in rows:
        if r["label_at"] < r["observed_at"]:
            raise ValueError("outcome predates features")
        if r["label_at"] <= train_end:
            groups[0].append(r)
        elif r["observed_at"] >= train_end and r["label_at"] <= validation_end:
            groups[1].append(r)
        elif r["observed_at"] >= validation_end:
            groups[2].append(r)
    def audit(rule, group):
        return pattern_report(group, rule["feature"], rule["threshold"],
                              direction=rule.get("direction", "le"), min_support=min_support)
    def passes(r):
        return (r["status"] == "hypothesis" and r["false_rejection_rate"] is not None
                and r["false_rejection_rate"] <= max_false_rejection
                and r["incident_matches"] >= min_support
                and r["incident_rate_matched"] > r["incident_rate_unmatched"])
    ranked = sorted(((rule, audit(rule, groups[0])) for rule in rules),
                    key=lambda pair: (-(pair[1]["incident_rate_matched"] or 0), fingerprint(pair[0])))
    selected = next(((rule, stats) for rule, stats in ranked if passes(stats)), None)
    report = {"status": "not_validated", "automatic_veto": False, "dataset_hash": fingerprint(rows),
              "cohort_sizes": [len(g) for g in groups], "rules_tested": len(rules),
              "min_support": min_support, "max_false_rejection": max_false_rejection}
    if selected is None:
        return {**report, "reason": "no training rule meets support and false-rejection budget"}
    rule, train = selected
    validation, test = audit(rule, groups[1]), audit(rule, groups[2])
    report.update(rule=rule, train=train, validation=validation, test=test)
    if passes(validation) and passes(test):
        report["status"] = "review_required"
    return report


def export_latest(path=None):
    """Latest immutable version per project. Import time is not backdated."""
    with connect(path) as db:
        rows = db.execute("SELECT payload,observed FROM quant_incidents q WHERE rowid = "
                          "(SELECT max(rowid) FROM quant_incidents x WHERE x.project=q.project)").fetchall()
    return [{**json.loads(payload), "label_at": observed,
             "observed_at": json.loads(payload).get("at")} for payload, observed in rows]


def capture_case(a, bars, now, path=None):
    """Prospective 24h dataset independent of approval; never relabel old gems.

    Latest window stays mutable while collecting, then freezes. Experiments
    hash the complete exported dataset. Gaps remain gaps and fail validation.
    """
    from app.trading.onchain.quant_engine import BASE, FEED
    from app.trading.onchain import quant_runtime, projects_db, leaderboard, outcomes
    if not a.get("quant_observed"):
        ok, _ = quant_runtime.gem_verdict(a, now)
        if not ok:
            return
        p = projects_db.get(a["chain"], a["token_address"])
        e = leaderboard.db_entry(p)
        a["quant_observed"] = {"start": now, "born": p.get("launched_at"),
                               "features": outcomes.features(e, now)}
    first = a["quant_observed"]
    key = json.dumps([a["chain"], a["token_address"]])
    with connect(path) as db:
        old = db.execute("SELECT captured FROM quant_research_cases WHERE project=?", (key,)).fetchone()
        end = (int(first["start"] + 86400) // BASE) * BASE
        if old and (old[0] >= end or now - old[0] < 1800):
            return
        cutoff = min(end, int(now) // BASE * BASE)
        if cutoff <= first["start"]:
            return
        row = {"chain": a["chain"], "token": a["token_address"], "feed": FEED,
               "start": first["start"], "end": cutoff, "born": first["born"],
               "features": first["features"], "eligibility_at": first["start"], "gem_eligible": True,
               "bars": [b for b in bars if b[0] < cutoff],
               "untradeable_at": (a.get("last") or {}).get("at") if a.get("gone") else None}
        db.execute("INSERT OR REPLACE INTO quant_research_cases VALUES(?,?,?)", (key, cutoff, json.dumps(row, allow_nan=False)))


def export_cases(path=None):
    with connect(path) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT payload FROM quant_research_cases ORDER BY project")]


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Export local quantitative evidence without any model call")
    parser.add_argument("kind", choices=("cases", "incidents"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = export_cases() if args.kind == "cases" else export_latest()
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(rows, target, indent=2, allow_nan=False)
