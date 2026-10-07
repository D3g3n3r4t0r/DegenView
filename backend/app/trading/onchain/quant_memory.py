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

_path = None  # Tests inject one isolated database for every module.
HORIZONS = (86400, 7 * 86400, 30 * 86400)


@contextmanager
def connect(path=None):
    db = sqlite3.connect(path or _path or data_file("observatory.sqlite3"), timeout=5)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS quant_incidents "
                   "(digest TEXT PRIMARY KEY, project TEXT NOT NULL, observed REAL NOT NULL, payload TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS quant_incidents_project ON quant_incidents(project,observed)")
        db.execute("CREATE TABLE IF NOT EXISTS quant_research_cases "
                   "(project TEXT PRIMARY KEY, captured REAL NOT NULL, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS quant_candles "
                   "(project TEXT NOT NULL, t INTEGER NOT NULL, o REAL, h REAL, l REAL, c REAL, v REAL, observed REAL, PRIMARY KEY(project,t))")
        db.execute("CREATE TABLE IF NOT EXISTS quant_observations (project TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS quant_windows "
                   "(project TEXT NOT NULL, horizon INTEGER NOT NULL, captured REAL NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(project,horizon))")
        db.execute("CREATE TABLE IF NOT EXISTS quant_reports "
                   "(id TEXT PRIMARY KEY, at REAL NOT NULL, payload TEXT NOT NULL)")
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


def _legacy_export_cases(path=None):
    with connect(path) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT payload FROM quant_research_cases ORDER BY project")]


def project_key(a):
    chain, token = a["chain"], a.get("token_address") or a.get("token")
    if not isinstance(chain, str) or not isinstance(token, str) or not chain or not token:
        raise ValueError("project identity required")
    if chain in {"ethereum", "base", "bsc", "robinhood", "arbitrum", "polygon", "optimism", "avalanche", "arc"}:
        token = token.lower()
    return json.dumps([chain, token], separators=(",", ":"))


def store_bars(a, bars, now, path=None):
    """First observed CLOSED version wins. Live signals never revise past fills."""
    from app.trading.onchain.quant_engine import BASE, clean_bars
    rows = clean_bars(bars, limit=None)
    key = project_key(a)
    with connect(path) as db:
        before = db.total_changes
        db.executemany("INSERT OR IGNORE INTO quant_candles VALUES(?,?,?,?,?,?,?,?)",
                       [(key, *r, now) for r in rows if r[0] + BASE <= now])
        return db.total_changes - before


def candles(a, before, path=None):
    with connect(path) as db:
        return [list(r) for r in db.execute("SELECT t,o,h,l,c,v FROM quant_candles WHERE project=? AND t<? ORDER BY t",
                                           (project_key(a), before))]


def capture_case(a, bars, now, path=None):
    """Collect once-known eligibility and 1/7/30-day windows without an approval.

    Candles survive the alert tracker's rolling buffer. Completed windows freeze;
    partial windows are explicitly marked and cannot validate a policy.
    """
    from app.trading.onchain.quant_engine import BASE, FEED
    from app.trading.onchain import quant_runtime, projects_db, leaderboard, outcomes
    key = project_key(a)
    with connect(path) as db:
        old = db.execute("SELECT payload FROM quant_observations WHERE project=?", (key,)).fetchone()
    first = json.loads(old[0]) if old else None
    if first is None:
        ok, _ = quant_runtime.gem_verdict(a, now)
        if not ok or a.get("gone"):
            return False
        p = projects_db.get(a["chain"], a["token_address"])
        first = {"start": now, "born": p.get("launched_at"), "features": outcomes.features(leaderboard.db_entry(p), now),
                 "chain": a["chain"], "token": a["token_address"], "symbol": a.get("symbol")}
        with connect(path) as db:
            db.execute("INSERT OR IGNORE INTO quant_observations VALUES(?,?)", (key, json.dumps(first, allow_nan=False)))
            first = json.loads(db.execute("SELECT payload FROM quant_observations WHERE project=?", (key,)).fetchone()[0])
    a["quant_observed"] = first
    store_bars(a, bars, now, path)
    cutoff = int(now) // BASE * BASE
    if cutoff <= first["start"]:
        return True
    with connect(path) as db:
        for horizon in HORIZONS:
            end = int((first["start"] + horizon) // BASE) * BASE
            old = db.execute("SELECT captured FROM quant_windows WHERE project=? AND horizon=?", (key, horizon)).fetchone()
            if old and (old[0] >= end or cutoff - old[0] < 1800 and cutoff < end):
                continue
            row = {**first, "feed": FEED, "end": min(cutoff, end), "eligibility_at": first["start"],
                   "gem_eligible": True, "complete": cutoff >= end, "horizon": horizon,
                   "untradeable_at": (a.get("last") or {}).get("at") if a.get("gone") else None}
            db.execute("INSERT OR REPLACE INTO quant_windows VALUES(?,?,?,?)",
                       (key, horizon, row["end"], json.dumps(row, allow_nan=False)))
    return True


def export_cases(path=None, horizon=86400, complete_only=False):
    with connect(path) as db:
        records = db.execute("SELECT payload FROM quant_windows WHERE horizon=? ORDER BY project", (horizon,)).fetchall()
    rows = [json.loads(r[0]) for r in records]
    if not rows:
        return _legacy_export_cases(path) if horizon == 86400 and not complete_only else []
    return [{**r, "bars": candles(r, r["end"], path)} for r in rows if not complete_only or r["complete"]]


def save_report(report, path=None, now=None):
    check = dict(report)
    provided = check.pop("report_hash", None)
    key = fingerprint(check)
    if provided is not None and provided != key:
        raise ValueError("report hash mismatch")
    with connect(path) as db:
        db.execute("INSERT OR IGNORE INTO quant_reports VALUES(?,?,?)",
                   (key, time.time() if now is None else now, json.dumps({**check, "report_hash": key}, allow_nan=False)))
    return key


def report_by_id(key, path=None):
    with connect(path) as db:
        row = db.execute("SELECT payload FROM quant_reports WHERE id=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def status(path=None):
    with connect(path) as db:
        incidents = db.execute("SELECT count(*),count(DISTINCT project) FROM quant_incidents").fetchone()
        counts = {str(h): {"windows": n, "complete": done} for h, n, done in db.execute(
            "SELECT horizon,count(*),sum(json_extract(payload,'$.complete')=1) FROM quant_windows GROUP BY horizon")}
        reports = [{"id": key, "at": at, "status": json.loads(payload).get("status"),
                    "selected": json.loads(payload).get("selected"), "reason": json.loads(payload).get("reason")}
                   for key, at, payload in db.execute("SELECT id,at,payload FROM quant_reports ORDER BY at DESC LIMIT 20")]
        projects = [json.loads(p[0]) for p in db.execute("SELECT payload FROM quant_observations ORDER BY rowid DESC LIMIT 100")]
        n_candles = db.execute("SELECT count(*) FROM quant_candles").fetchone()[0]
    return {"incident_versions": incidents[0], "incident_projects": incidents[1], "windows": counts,
            "candles": n_candles, "reports": reports, "projects": projects, "llm_calls": 0}


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Export local quantitative evidence without any model call")
    parser.add_argument("kind", choices=("cases", "incidents"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--horizon-days", type=int, choices=(1, 7, 30), default=1)
    args = parser.parse_args()
    rows = export_cases(horizon=args.horizon_days * 86400, complete_only=True) if args.kind == "cases" else export_latest()
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(rows, target, indent=2, allow_nan=False)
