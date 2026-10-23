"""Coordinated sells: wallets that sell one token together, read and alerted.

Lorenzo, 22/10: a tool for coordinated sells, first token
0x96f455a90a80dcf0c2df6703ea4ba3bedf286e43 on Robinhood Chain. The engine
(another module) finds the clusters and writes one report per token; this
module only reads the reports, serves them to the app (whitekobra only) and
sends a Telegram alert when a cluster sells together.

Report contract, version 1: one file per token,
backend/data/coordinated_sells/<chain>-<token lowercase>.json

    {
      "version": 1,
      "chain": "robinhood",
      "token": "0x...",                 # lowercase
      "symbol": "XYZ",
      "updated_at": 1761100000,         # unix seconds
      "risk": {"score": 0-100, "reasons": ["..."]},
      "clusters": [{
        "id": "c1",                     # stable across runs
        "wallets": [{"address": "0x...", "share": 0.012}],   # share of supply, 0..1
        "share": 0.083,                 # whole cluster, 0..1
        "links": ["same_funder", "same_block_sells", "same_amounts"],
        "risk": 0-100,
        "edges": [["0xa", "0xb"]]       # optional: wallet pairs the engine linked (map lines)
      }],
      "events": [{
        "id": "c1-1761099000",          # stable: never reused for another sell
        "cluster": "c1",
        "ts": 1761099000,               # first sell of the wave
        "window_s": 90,                 # first to last sell
        "wallets": 5,                   # how many of the cluster sold
        "share_sold": 0.021,            # of supply, 0..1
        "usd": 41000.0,                 # optional
        "txs": ["0x..."],               # optional
        "sellers": ["0x..."]            # optional: who sold in the wave (lit on the map)
      }]
    }

Unknown fields are ignored, missing optional ones stay None. Shares are
fractions (0.021 = 2.1% of supply), never percentages. sync_sells.analyze()
turns into a report with from_analysis(), saved with write().
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from app.accel import fast_json
from app.atomic_write import write_text_atomic
from app.trading.onchain import storage

logger = logging.getLogger(__name__)

VERSION = 1
SAMPLE = Path(__file__).resolve().parents[2] / "data" / "coordinated_sells_sample.json"
# An alert needs at least this many wallets selling and this share of supply
# in one wave, and a wave older than ALERT_MAX_AGE_S is history, not news.
ALERT_MIN_WALLETS = 2
ALERT_MIN_SHARE = 0.005
ALERT_MAX_AGE_S = 6 * 3600
_SENT_KEEP = 2000


def _dir() -> Path:
    return storage.DATA_DIR / "coordinated_sells"


def _num(v, lo: float | None = None, hi: float | None = None) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def _norm(a: str) -> str:
    return a.lower() if a.startswith("0x") else a


def clean(raw: dict) -> dict | None:
    """One report as the app reads it, or None when it isn't one."""
    if not isinstance(raw, dict) or raw.get("version") != VERSION or not raw.get("token"):
        return None
    clusters = []
    for c in raw.get("clusters") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        wallets = [{"address": str(w.get("address", "")), "share": _num(w.get("share"), 0, 1)}
                   for w in c.get("wallets") or [] if isinstance(w, dict) and w.get("address")]
        clusters.append({"id": str(c["id"]), "wallets": wallets, "share": _num(c.get("share"), 0, 1),
                         "links": [str(x) for x in c.get("links") or []][:8], "risk": _num(c.get("risk"), 0, 100),
                         "edges": [[_norm(str(a)), _norm(str(b))] for a, b in
                                   (e for e in c.get("edges") or [] if isinstance(e, list) and len(e) == 2)][:2000]})
    ids = {c["id"] for c in clusters}
    events = []
    for e in raw.get("events") or []:
        if not isinstance(e, dict) or not e.get("id") or e.get("cluster") not in ids or _num(e.get("ts")) is None:
            continue
        events.append({"id": str(e["id"]), "cluster": str(e["cluster"]), "ts": _num(e["ts"]),
                       "window_s": _num(e.get("window_s"), 0), "wallets": int(_num(e.get("wallets"), 0) or 0),
                       "share_sold": _num(e.get("share_sold"), 0, 1), "usd": _num(e.get("usd"), 0),
                       "txs": [str(t) for t in e.get("txs") or []][:20],
                       "sellers": [_norm(str(a)) for a in e.get("sellers") or []][:200]})
    events.sort(key=lambda e: e["ts"], reverse=True)
    risk = dict(raw.get("risk")) if isinstance(raw.get("risk"), dict) else {}
    # The structure risk read from the clusters themselves (sync_sells.structure):
    # a report written before it, or by an older engine, cannot say 0 while
    # linked wallets hold 19% (Lorenzo, 22/10: "come fa a essere rischio 0?").
    from app.trading.onchain import sync_sells
    # Only on clusters built under today's rules (wallet_clusters.RULES): an
    # older build may hold an airdrop read as a cluster, rebuilt soon anyway.
    held = sum(c["share"] or 0 for c in clusters if c["id"] != "top" and len(c["wallets"]) >= 2)
    struct = round(100 * min(1.0, held / sync_sells.STRUCT_FULL))
    rules = (raw.get("coverage") or {}).get("rules") if isinstance(raw.get("coverage"), dict) else None
    if (rules or 0) >= 2 and struct > (_num(risk.get("score"), 0, 100) or 0):
        risk["reasons"] = [f"linked wallets hold {100 * held:.1f}% of supply"] + list(risk.get("reasons") or [])
        risk["score"] = struct
    return {"version": VERSION, "chain": str(raw.get("chain") or ""), "token": _norm(str(raw["token"])),
            "symbol": str(raw.get("symbol") or ""), "updated_at": _num(raw.get("updated_at")),
            "risk": {"score": _num(risk.get("score"), 0, 100), "reasons": [str(x) for x in risk.get("reasons") or []][:6]},
            "clusters": sorted(clusters, key=lambda c: -(c["share"] or 0)), "events": events,
            "coverage": _coverage(raw.get("coverage"))}


def _coverage(c) -> dict | None:
    """How much history the clusters were built from: a partial one is said,
    not hidden behind a risk figure."""
    if not isinstance(c, dict):
        return None
    return {"source": str(c.get("source") or "")[:40], "partial": bool(c.get("partial")), "rules": c.get("rules"),
            "from_ts": _num(c.get("from_ts")), "transfers": int(_num(c.get("transfers"), 0) or 0)}


def from_analysis(a: dict, chain: str, token: str, wallets: list[str], symbol: str = "",
                  holdings: dict[str, float] | None = None, now: float | None = None) -> dict:
    """A report v1 from sync_sells.analyze(): its watched wallets are one
    cluster, each of its groups one wave. `holdings` (address -> share of
    supply, 0..1) fills the cluster's share when the caller has it.
    sync_sells gives percentages; the report wants fractions."""
    held = {w.lower(): (holdings or {}).get(w.lower()) for w in wallets}
    known = [v for v in held.values() if v is not None]
    events = [{"id": f"c1-{g['first_block']}", "cluster": "c1", "ts": g.get("first_ts"),
               "window_s": (g["last_ts"] - g["first_ts"]) if g.get("first_ts") and g.get("last_ts") else None,
               "wallets": len(g.get("wallets") or []), "share_sold": (g.get("supply_pct") or 0) / 100}
              for g in a.get("groups") or [] if g.get("first_ts")]
    reasons = [f"{a.get('sellers', 0)} of {a.get('wallets', 0)} watched wallets moved tokens",
               f"{(a.get('sync_pct') or 0):.2f}% of supply moved in coordinated waves"]
    return clean({"version": VERSION, "chain": chain, "token": token, "symbol": symbol,
                  "updated_at": time.time() if now is None else now,
                  "risk": {"score": (a.get("risk") or {}).get("score"), "reasons": reasons},
                  "clusters": [{"id": "c1", "wallets": [{"address": w, "share": v} for w, v in held.items()],
                                "share": sum(known) if known else None,
                                "links": ["same_block_sells"] if any(g.get("same_block") for g in a.get("groups") or []) else [],
                                "risk": (a.get("risk") or {}).get("score")}],
                  "events": events})


_report_cache: dict[str, tuple[int, int, dict | None]] = {}


def write(report: dict) -> Path:
    """Where the engine saves a report: the view and the alert read it."""
    path = _dir() / f"{report['chain']}-{report['token'].lower()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, fast_json.dumps(report))
    _report_cache.pop(str(path), None)
    return path


def _read(path: Path) -> dict | None:
    key = str(path)
    try:
        st = path.stat()
        hit = _report_cache.get(key)
        if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        cleaned = clean(fast_json.loads(path.read_bytes()))
        _report_cache[key] = (st.st_mtime_ns, st.st_size, cleaned)
        return cleaned
    except (OSError, ValueError):
        logger.warning("coordinated sells: unreadable report %s", path.name)
        return None


def reports() -> tuple[list[dict], bool]:
    """Every token's report, newest first, and whether they are the sample
    (the engine has written nothing yet)."""
    d = _dir()
    found = [r for p in sorted(d.glob("*.json")) if (r := _read(p))] if d.is_dir() else []
    if found:
        return sorted(found, key=lambda r: -(r["updated_at"] or 0)), False
    sample = _read(SAMPLE)
    return ([sample] if sample else []), True


# Lorenzo, 23/10 ("Applica A e C"): the "top" group (the 50 biggest holders,
# no on-chain link between them) stays in the report and its risk, but its
# waves are not alerts: two big holders selling in the same minutes is the
# market, not a cluster, and it flooded the gems chats.
ALERT_SKIP_CLUSTERS = {"top"}


def due(report: dict, sent: set[str], now: float) -> list[dict]:
    """The waves of this report worth a Telegram alert and not sent yet."""
    return [e for e in report["events"]
            if e["id"] not in sent and e.get("cluster") not in ALERT_SKIP_CLUSTERS
            and now - e["ts"] <= ALERT_MAX_AGE_S
            and e["wallets"] >= ALERT_MIN_WALLETS and (e["share_sold"] or 0) >= ALERT_MIN_SHARE]


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.2f}%".replace(".", ",")


def message(report: dict, event: dict, url: str) -> str:
    """The alert, in Italian like every Telegram message."""
    cluster = next((c for c in report["clusters"] if c["id"] == event["cluster"]), {})
    sym = report["symbol"] or report["token"][:10]
    win = event["window_s"]
    when = f" in {int(win // 60)} min" if win and win >= 60 else f" in {int(win)} s" if win else ""
    usd = f" (~${event['usd']:,.0f})".replace(",", ".") if event["usd"] else ""
    risk = report["risk"]["score"]
    lines = [f"🚨 <b>Vendita coordinata su {sym}</b>",
             f"{event['wallets']} wallet dello stesso cluster hanno venduto insieme{when}: "
             f"{_pct(event['share_sold'])} della supply{usd}.",
             f"Il cluster tiene {_pct(cluster.get('share'))} della supply"
             + (f", rischio token {int(risk)}/100." if risk is not None else "."),
             f'<a href="{url}">Apri la scheda</a>']
    return "\n".join(lines)


_SENT_FILE = "coordinated_sells_sent.json"


def load_sent() -> list[str]:
    """The waves already alerted, oldest first."""
    try:
        return [str(x) for x in json.loads(storage.data_file(_SENT_FILE).read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return []


def save_sent(sent: list[str]) -> None:
    write_text_atomic(storage.data_file(_SENT_FILE), json.dumps(sent[-_SENT_KEEP:]))


def _addr(v: str) -> str:
    v = v or ""
    return v.lower() if v.startswith("0x") else v


def shown_key(chain: str, token: str) -> str:
    return f"{(chain or '').lower()}:{_addr(token)}"


async def notify_once(send, url: str, now: float | None = None, shown: set[str] | None = None) -> int:
    """One pass: alerts every new wave of the engine's reports (never the
    sample's). `send` is telegram.send_message. Returns how many went out.
    shown: the tokens on screen now (Top and Early, shown_key), the only ones
    alerted (Lorenzo, 23/10); a wave of another token is not marked as sent,
    so it still alerts if the token enters the Top within ALERT_MAX_AGE_S."""
    found, sample = reports()
    if sample:
        return 0
    now = time.time() if now is None else now
    sent_list = load_sent()
    sent = set(sent_list)
    n = 0
    for r in found:
        token = shown_key(r.get("chain"), r.get("token"))
        if shown is not None and token not in shown:
            continue
        for e in sorted(due(r, set(), now), key=lambda e: e["ts"]):
            # A wave id ("c1-<ts>") is unique within its token only: the
            # sent key carries the token. A bare id is an older entry.
            key = f"{token}:{e['id']}"
            if key in sent or e["id"] in sent:
                continue
            if await send(message(r, e, url)):
                sent.add(key)
                sent_list.append(key)
                n += 1
    if n:
        save_sent(sent_list)
    return n


# Lorenzo, 22/10 (decision card): a coordinated-sell risk of 60 or more takes
# the token out of the Top for every account, like a crash.
EXCLUDE_RISK = 60
EXCLUDE_MAX_AGE_S = 7 * 86400
_excl_cache: tuple[float, dict[str, int]] = (0.0, {})


def report_for(chain: str, token: str) -> dict | None:
    from app.trading.onchain import sync_sells
    path = sync_sells.report_path((chain or "").lower(), token or "")
    return _read(path) if path.is_file() else None


def fresh_report(chain: str, token: str, now: float | None = None) -> dict | None:
    rep = report_for(chain, token)
    now = now if now is not None else time.time()
    return rep if rep and now - (rep.get("updated_at") or 0) <= EXCLUDE_MAX_AGE_S else None


# Lorenzo, 22/10: "il recheck di deepseek o parere ai anti rug deve considerare
# il report del cluster esclusivamente e se manca lo forza per averlo". The
# AI's holder and rug judgement rests on this report, measured on chain,
# never on its own guesses about the holders. No addresses: counts and shares.
def ai_facts(chain: str, token: str, now: float | None = None) -> dict | None:
    rep = fresh_report(chain, token, now)
    if not rep:
        return None
    now = now if now is not None else time.time()
    linked = [c for c in rep["clusters"] if c["id"] != "top"]
    top = next((c for c in rep["clusters"] if c["id"] == "top"), None)
    waves = rep["events"]
    pct = lambda x: round(100 * (x or 0), 2)  # noqa: E731
    return {"risk": rep["risk"]["score"], "risk_reasons": rep["risk"]["reasons"],
            "linked_clusters": len(linked), "linked_wallets": sum(len(c["wallets"]) for c in linked),
            "linked_supply_pct": pct(sum(c["share"] or 0 for c in linked)),
            "biggest_cluster_pct": pct(max((c["share"] or 0 for c in linked), default=0)),
            "links": sorted({x for c in linked for x in c["links"]}),
            "top_holders_supply_pct": pct(top["share"]) if top and top["share"] is not None else None,
            "sell_waves": len(waves), "sell_waves_7d": sum(now - e["ts"] <= 7 * 86400 for e in waves),
            "supply_sold_in_waves_pct": pct(sum(e["share_sold"] or 0 for e in waves)),
            "last_wave_hours_ago": round((now - waves[0]["ts"]) / 3600, 1) if waves else None,
            "report_age_hours": round((now - (rep.get("updated_at") or now)) / 3600, 1),
            "coverage": rep.get("coverage")}


def ai_text(facts: dict | None, state: str = "") -> str:
    """The report as one evidence line for the AI's prompt."""
    if not facts:
        return (f"Wallet cluster report: not available ({state or 'no report'}); "
                "holder coordination and rug risk from holders are unverified.")
    cov = facts.get("coverage") or {}
    parts = [f"risk {facts['risk']:.0f}/100" if facts.get("risk") is not None else "risk unknown",
             f"{facts['linked_clusters']} linked clusters, {facts['linked_wallets']} wallets holding "
             f"{facts['linked_supply_pct']}% of supply (biggest {facts['biggest_cluster_pct']}%)",
             "links: " + (", ".join(facts["links"]) or "none")]
    if facts.get("top_holders_supply_pct") is not None:
        parts.append(f"top holders hold {facts['top_holders_supply_pct']}%")
    parts.append(f"{facts['sell_waves']} coordinated sell waves ({facts['sell_waves_7d']} in the last 7 days), "
                 f"{facts['supply_sold_in_waves_pct']}% of supply sold in them")
    if cov:
        parts.append(f"history from {cov.get('source') or '?'}" + (", partial" if cov.get("partial") else ""))
    return "Wallet cluster report (measured on chain by our engine): " + "; ".join(parts) + "."


def exclusion(chain: str, token: str, now: float | None = None) -> str:
    """"" unless the token's fresh report has risk >= EXCLUDE_RISK."""
    global _excl_cache
    now = now if now is not None else time.time()
    if now - _excl_cache[0] > 60:
        risky = {}
        d = _dir()
        for p in d.glob("*.json") if d.is_dir() else []:
            rep = _read(p)
            score = ((rep or {}).get("risk") or {}).get("score") or 0
            if rep and score >= EXCLUDE_RISK and now - (rep.get("updated_at") or 0) <= EXCLUDE_MAX_AGE_S:
                risky[f"{rep['chain']}:{rep['token']}"] = round(score)
        _excl_cache = (now, risky)
    score = _excl_cache[1].get(f"{(chain or '').lower()}:{_norm(token or '')}")
    return f"coordinated sells: risk {score}" if score else ""
