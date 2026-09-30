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
MAX_STEPS = 120

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


def _records(chain: str, token: str) -> list[tuple[float, str, str, dict]]:
    """(time, node, source, record) for every stored fact about this token."""
    out: list[tuple[float, str, str, dict]] = []
    p = projects_db.get(chain, token)
    if p:
        out.append((p["first_seen"], "scan", "projects_db.first_seen",
                    {"key": p["key"], "first_seen": p["first_seen"], "sources": p.get("sources")}))
        if p.get("analyzed_at"):
            out.append((p["analyzed_at"], "decision", "projects_db.verdict",
                        {"key": p["key"], "analyzed_at": p["analyzed_at"], "status": p.get("status"),
                         "why": p.get("why"), "score": p.get("score"), "rank": p.get("rank")}))
    for a in deepseek_desk.log(limit=deepseek_desk.ACTIVITY_KEEP):
        if a.get("token") == token and (not a.get("chain") or a.get("chain") == chain):
            out.append((a["t"], _KIND_NODE.get(a.get("kind"), "other"), "agent_activity", a))
    needle = token.lower()
    for c in deepseek_calls.recent(deepseek_calls.KEEP):
        if needle in (c.get("subject") or "").lower():
            out.append((c["t"], _purpose_node(c.get("purpose") or ""), "deepseek_call", c))
    lab = strategy_lab._results.get(strategy_lab.key_of(chain, token))
    if lab and lab.get("at"):
        out.append((lab["at"], "backtest", "strategy_lab",
                    {"key": f"{chain}:{token}", "at": lab["at"], "pair": lab.get("pair"), "error": lab.get("error"),
                     "has_backtests": lab.get("backtests") is not None, "has_daily": lab.get("daily") is not None}))
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
            "limits": "Stored records only. The verdict row is the latest one (older verdicts are overwritten); "
                      "agent activity keeps the last 1000 events. A hash shows the record was not altered in "
                      "transit, not that its source was right."}
