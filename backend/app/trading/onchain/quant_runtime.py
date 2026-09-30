"""Read-only bridge from reviewed research to signal-only sniper entries.

No report is activated by research. An operator must install an approved
manifest on the server after review/paper testing. Missing evidence fails closed
for new entries; legacy positions keep their existing exit implementation.
"""
from __future__ import annotations

import json
import logging
import math

from app.trading.onchain.quant_engine import BASE, VERSION, FEED, Policy, fingerprint, replay, strategy_code_hash
from app.trading.onchain.storage import data_file

logger = logging.getLogger(__name__)


def approved(path=None):
    try:
        manifest = json.loads((path or data_file("quant_approved.json")).read_text(encoding="utf-8"))
        report = manifest["report"]
        check = dict(report)
        checksum = check.pop("report_hash")
        if checksum != fingerprint(check) or report["version"] != VERSION or report["status"] != "review_required":
            return None
        if report.get("strategy_code_hash") != strategy_code_hash() or report.get("feed") != FEED:
            return None
        if manifest.get("approved") is not True or not manifest.get("reviewer") or not manifest.get("paper_run_id"):
            return None
        if not isinstance(manifest.get("active_from"), (int, float)) or not math.isfinite(manifest["active_from"]):
            return None
        selected = report["selected"]
        policy = Policy(tuple(tuple(s) for s in selected["stages"]), selected["strategy"])
        patterns = report.get("patterns")
        if patterns and patterns.get("status") != "review_required":
            return None
        return {"policy": policy, "report_hash": checksum, "active_from": manifest["active_from"],
                "costs": report["costs"], "pattern": patterns.get("rule") if patterns else None}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def gem_verdict(a, now):
    """Reuse current gem qualification; never grant a CEX or meme bypass."""
    from app.sniper.quality import _looks_like_meme
    from app.trading.onchain import leaderboard, projects_db
    if a.get("meme") or _looks_like_meme(a.get("symbol", ""), a.get("name", "")):
        return False, "meme excluded"
    p = projects_db.get(a["chain"], a["token_address"])
    if not p or p.get("status") not in ("ranked", "studied"):
        return False, "gem analysis unavailable"
    if not (0 <= now - (p.get("market_at") or 0) <= projects_db.MARKET_TTL_S):
        return False, "gem market evidence expired"
    e = leaderboard.db_entry(p)
    reason = leaderboard.qualifies(e, now)
    if reason:
        return False, reason
    # Existing leaderboard allows missing liquidity. Entries cannot assume it.
    if not e.get("liquidity_usd") or not e.get("overall") or e["overall"].get("pending"):
        return False, "gem evidence incomplete"
    return True, "gem rules passed"


def refresh(a, bars, now, manifest=None):
    """Pin policy at first eligible observation; later changes affect new tokens only."""
    manifest = manifest or approved()
    if not a.get("quant_policy") and (not manifest or now < manifest["active_from"]):
        a["quant_status"] = "no reviewed policy for this alert"
        return
    if not a.get("quant_policy"):
        ok, why = gem_verdict(a, now)
        a["quant_status"] = why
        if not ok:
            return
        if not a.get("launched_at"):
            a["quant_status"] = "verified token birth required"
        # Token birth must come from project evidence, never from the alert time.
        if not a.get("launched_at"):
            from app.trading.onchain import projects_db
            p = projects_db.get(a["chain"], a["token_address"])
            a["launched_at"] = (p or {}).get("launched_at")
        if not a.get("launched_at"):
            return
        a["quant_policy"] = {"stages": manifest["policy"].stages, "strategy": manifest["policy"].strategy,
                             "report_hash": manifest["report_hash"], "costs": manifest["costs"],
                             "eligible_at": now, "pattern": manifest.get("pattern")}
        if not a.get("gone"):
            a["closed"] = False
    pinned = a["quant_policy"]
    policy = Policy(tuple(tuple(s) for s in pinned["stages"]), pinned["strategy"])
    end = int(now) // BASE * BASE
    start = pinned["eligible_at"]
    if end <= start:
        return
    case = {"bars": bars, "start": start, "end": end, "born": a.get("launched_at"),
            "gem_eligible": True, "eligibility_at": start}
    result = replay(case, policy, **pinned["costs"])
    result.update(evaluated_at=now, report_hash=pinned["report_hash"])
    a["quant_system"] = result
    a["quant_status"] = result.get("reason") or result["state"]


def can_enter(a, now):
    if approved() is None:
        return False
    r = a.get("quant_system") or {}
    if a.get("gone") or r.get("state") != "in" or not r.get("eligible"):
        return False
    if not (0 <= now - (r.get("in_at") or 0) <= 900 and 0 <= now - (r.get("evaluated_at") or 0) <= 600):
        return False
    # Revalidate after research: a new fatal finding must stop an entry.
    try:
        if not gem_verdict(a, now)[0]:
            return False
        rule = (a.get("quant_policy") or {}).get("pattern")
        if rule:
            from app.trading.onchain import outcomes, leaderboard, projects_db
            p = projects_db.get(a["chain"], a["token_address"])
            value = outcomes.features(leaderboard.db_entry(p), now).get(rule["feature"])
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                return False
            matched = value <= rule["threshold"] if rule.get("direction", "le") == "le" else value >= rule["threshold"]
            if matched:
                a["quant_status"] = "reviewed incident pattern matched"
                return False
        return True
    except Exception:
        logger.exception("Gem entry evidence unavailable")
        return False
