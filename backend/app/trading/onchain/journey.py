"""The recorded evaluation path of one token, as a verifiable hash chain.

Lorenzo, 30/09: "metti un campo dove io compilo il ticker [...] mi carichi
la loro storia di quello che è stato il processo di valutazione [...] deve
essere tutto formalmente verificato e tracciabile".

Nothing here is inferred or generated: every step is one record that
already exists in a store (projects database, agent activity, DeepSeek
call journal, strategy lab). Each step carries the exact JSON of that
record as a string, `id = sha256(record)` and `link = sha256(prev_link + id)`,
so the page can recompute the chain and show whether it matches. As the
receipts spec says (docs/analysis-receipts/SPEC.md), a hash identifies
content and makes tampering in transit visible; it does not prove the
source was right, and the server owner could rewrite store and hash together.
No model calls.
"""
from __future__ import annotations

import hashlib
import json

from app.notify import deepseek_calls, deepseek_desk
from app.trading.onchain import projects_db, strategy_lab

GENESIS = "0" * 64
MAX_STEPS = 400

# Same node ids as frontend/static/onchain/agent-map-model.js.
_KIND_NODE = {"scan": "scan", "scanner": "scan", "manual": "scan", "study": "study", "research": "research",
              "judge": "research", "review": "research", "code": "code", "narratives": "narratives",
              "consistency": "consistency", "backtest": "backtest"}
_PURPOSE_NODE = {"code": "code", "site": "research", "site_legit": "research", "research": "research",
                 "judge": "research", "consistency": "consistency", "alert_manual": "scan",
                 "alert_batch": "scan", "recheck": "research"}


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _purpose_node(purpose: str) -> str:
    return _PURPOSE_NODE.get(purpose, _PURPOSE_NODE.get(purpose.split("/")[0], "other"))


def resolve(q: str, limit: int = 8) -> list[dict]:
    """Tokens whose symbol matches exactly (any case) or whose address is `q`.
    A ticker is not an identity: several tokens can share one."""
    q = (q or "").strip().lstrip("$")
    if not q:
        return []
    found: dict[str, dict] = {}

    def add(chain, token, symbol, status=None):
        if chain and token and f"{chain}:{token}" not in found and len(found) < limit:
            found[f"{chain}:{token}"] = {"chain": chain, "token": token, "symbol": symbol or "", "status": status}

    for p in projects_db.search(q=q, limit=50)["items"]:
        if p["token"] == q or (p.get("symbol") or "").lower() == q.lower():
            add(p["chain"], p["token"], p.get("symbol"), p.get("status"))
    for a in deepseek_desk.log(limit=deepseek_desk.ACTIVITY_KEEP):
        if a.get("token") == q or (a.get("symbol") or "").lower() == q.lower():
            add(a.get("chain"), a.get("token"), a.get("symbol"))
    return list(found.values())


def _pick(d: dict, keys: tuple[str, ...]) -> dict:
    return {k: d.get(k) for k in keys if d.get(k) is not None}


def _records(chain: str, token: str) -> list[tuple[float, str, str, dict]]:
    """(time, node, source, record) for every stored fact about this token.
    Each record is a fixed projection of the stored row (large blobs left out)."""
    from app.trading.onchain import alert_track, code_review, discovery, gem_track, judge, leaderboard, outcomes, research
    k = f"{chain}:{token}"
    out: list[tuple[float, str, str, dict]] = []
    p = projects_db.get(chain, token) or {}
    e = leaderboard._entries.get(k) or {}
    if p:
        out.append((p["first_seen"], "scan", "projects_db.first_seen",
                    {"key": k, "first_seen": p["first_seen"], "sources": p.get("sources")}))
        if p.get("analyzed_at"):
            out.append((p["analyzed_at"], "decision", "projects_db.verdict",
                        {"key": k, **_pick(p, ("analyzed_at", "status", "why", "score", "rank", "overall"))}))
    d = discovery._seen.get(f"dx:{k}")
    if d and d.get("at"):
        out.append((d["at"], "scan", "discovery", {"key": k, **_pick(d, ("at", "ok", "why"))}))
    if e.get("found_at"):
        out.append((e["found_at"], "scan", "leaderboard.found", {"key": k, **_pick(e, ("found_at", "source", "launched_at"))}))
    for name, at in (e.get("checked_at") or {}).items():
        pil = (e.get("pillars") or {}).get(name) or {}
        node = {"github": "code", "code": "code", "site": "research", "research": "research"}.get(name, "study")
        out.append((at, node, "leaderboard.pillar",
                    {"key": k, "pillar": name, "checked_at": at, **_pick(pil, ("score", "flags", "fatal"))}))
    if e.get("moved_at"):
        out.append((e["moved_at"], "decision", "leaderboard.rank",
                    {"key": k, **_pick(e, ("moved_at", "rank", "rank_before"))}))
    j = judge._cache.get(k)
    if j and j.get("at"):
        out.append((j["at"], "research", "judge", {"key": k, **_pick(j, ("at", "v", "verdict", "confidence", "reason", "why"))}))
    for suffix, label in (("", "research.dossier"), ("|ds", "research.reading")):
        r = research._cache.get(k + suffix)
        if r and r.get("at"):
            ai = r.get("ai") if isinstance(r.get("ai"), dict) else {}
            out.append((r["at"], "research", label, {"key": k, "at": r["at"], **_pick(ai, ("score", "verdict", "summary"))}))
    repo = e.get("github") or p.get("github")
    c = code_review._cache.get(repo) if repo else None
    if c and c.get("at"):
        out.append((c["at"], "code", "code_review", {"key": k, "repo": repo,
                    **_pick(c, ("at", "pushed_at", "score", "verdict", "summary", "flags"))}))
    for a in deepseek_desk.log(limit=deepseek_desk.ACTIVITY_KEEP):
        if a.get("token") == token and (not a.get("chain") or a.get("chain") == chain):
            out.append((a["t"], _KIND_NODE.get(a.get("kind"), "other"), "agent_activity", a))
    needles = {token.lower(), *(x.lower() for x in (repo, p.get("website")) if x)}
    for row in deepseek_calls.recent(deepseek_calls.KEEP):
        subj = (row.get("subject") or "").lower()
        if subj and any(n in subj for n in needles):
            out.append((row["t"], _purpose_node(row.get("purpose") or ""), "deepseek_call", row))
    lab = strategy_lab._results.get(strategy_lab.key_of(chain, token))
    if lab and lab.get("at"):
        out.append((lab["at"], "backtest", "strategy_lab",
                    {"key": k, "at": lab["at"], "pair": lab.get("pair"), "error": lab.get("error"),
                     "has_backtests": lab.get("backtests") is not None, "has_daily": lab.get("daily") is not None}))
    g = gem_track._track.get(k)
    if g and g.get("at"):
        out.append((g["at"], "decision", "gem_track.entry", {"key": k, **_pick(g, ("at", "price", "score", "rank", "market_cap"))}))
        for days, ret in sorted((g.get("returns") or {}).items(), key=lambda x: float(x[0])):
            out.append((g["at"] + float(days) * 86400, "outcomes", "gem_track.return",
                        {"key": k, "entered_at": g["at"], "days": days, "return": ret}))
    for store, label in ((outcomes._journal, "outcomes.journal"), (outcomes._archive, "outcomes.archive")):
        o = store.get(k)
        if o and o.get("at"):
            out.append((o["at"], "outcomes", label, {"key": k, **_pick(o, (
                "at", "decision", "reason", "source", "min_ret", "max_ret", "rug", "rug_at", "rug_why", "closed"))}))
    for ak, al in alert_track._alerts.items():
        if ak.endswith(":" + k) and al.get("at"):
            out.append((al["at"], "scan", "alert_track", {"id": ak, **_pick(al, (
                "at", "kind", "score", "cap0", "liq0", "entry", "entry_at", "returns", "max_ret", "min_ret", "closed"))}))
    return out


def _text(source: str, r: dict) -> str:
    if source == "agent_activity":
        return r.get("text") or r.get("kind") or ""
    if source == "deepseek_call":
        state = "failed: " + r["err"] if r.get("err") else "answered"
        if r.get("json_ok") is False:
            state += ", answer did not parse"
        if r.get("same_out"):
            state += ", repeat of an identical request"
        return f"DeepSeek {r.get('purpose')} call {state}"
    if source == "projects_db.first_seen":
        return "First seen by " + ", ".join(r.get("sources") or ["an unknown source"])
    if source == "projects_db.verdict":
        score = f" · score {r['score']:.0f}" if isinstance(r.get("score"), (int, float)) else ""
        return f"Latest verdict: {r.get('status')}{score}" + (f" · {r['why']}" if r.get("why") else "")
    if source == "discovery":
        return ("Passed discovery checks" if r.get("ok") else "Discarded at discovery") + (f": {r['why']}" if r.get("why") else "")
    if source == "leaderboard.found":
        return f"Entered the research queue from {r.get('source') or 'an unknown source'}"
    if source == "leaderboard.pillar":
        sc = f" · score {r['score']}" if r.get("score") is not None else ""
        return f"{r['pillar'].capitalize()} pillar checked{sc}" + (f" · fatal: {r['fatal']}" if r.get("fatal") else "")
    if source == "leaderboard.rank":
        return f"Rank moved {r.get('rank_before') or 'new'} → {r.get('rank') or 'out'}"
    if source == "judge":
        return f"Judge verdict: {r.get('verdict')}" + (f" · {r['reason']}" if isinstance(r.get("reason"), str) else "")
    if source in ("research.dossier", "research.reading"):
        return "Site and docs read" + (f" · score {r['score']}" if r.get("score") is not None else "")
    if source == "code_review":
        return f"Code of {r.get('repo')} reviewed" + (f" · {r['verdict']}" if r.get("verdict") else "")
    if source == "gem_track.entry":
        return f"Entered the Top at rank {r.get('rank')} · price {r.get('price')}"
    if source == "gem_track.return":
        ret = r.get("return")
        return f"Price after {r['days']} days: {ret * 100:+.1f}%" if isinstance(ret, (int, float)) else f"Price after {r['days']} days"
    if source.startswith("outcomes."):
        return f"Outcome tracked: {r.get('decision')}" + (f" · rug: {r['rug_why']}" if r.get("rug") else "")
    if source == "alert_track":
        return f"Alert raised ({r.get('kind')})"
    if source == "strategy_lab":
        return "Backtest stored" if r.get("has_backtests") else f"Backtest not run: {r.get('error') or 'no result'}"
    return ""


def journey(chain: str, token: str) -> dict:
    rows = sorted(_records(chain, token), key=lambda x: (x[0], x[2]))[-MAX_STEPS:]
    steps, link = [], GENESIS
    for t, node, source, rec in rows:
        record = _canon(rec)
        sid = _sha(record)
        link = _sha(link + sid)
        steps.append({"t": t, "node": node, "source": source, "text": _text(source, rec)[:240],
                      "record": record, "id": sid, "link": link})
    p = projects_db.get(chain, token) or {}
    return {"chain": chain, "token": token, "symbol": p.get("symbol") or "", "genesis": GENESIS,
            "head": link, "steps": steps,
            "limits": "Every stored record about this token. Stores that keep only the latest value (verdict, judge, "
                      "pillar checks) show their latest; agent activity keeps the last 1000 events. A hash shows the record was not altered in "
                      "transit, not that its source was right."}
