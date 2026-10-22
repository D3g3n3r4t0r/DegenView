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
        "risk": 0-100
      }],
      "events": [{
        "id": "c1-1761099000",          # stable: never reused for another sell
        "cluster": "c1",
        "ts": 1761099000,               # first sell of the wave
        "window_s": 90,                 # first to last sell
        "wallets": 5,                   # how many of the cluster sold
        "share_sold": 0.021,            # of supply, 0..1
        "usd": 41000.0,                 # optional
        "txs": ["0x..."]                # optional
      }]
    }

Unknown fields are ignored, missing optional ones stay None. Shares are
fractions (0.021 = 2.1% of supply), never percentages.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

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
                         "links": [str(x) for x in c.get("links") or []][:8], "risk": _num(c.get("risk"), 0, 100)})
    ids = {c["id"] for c in clusters}
    events = []
    for e in raw.get("events") or []:
        if not isinstance(e, dict) or not e.get("id") or e.get("cluster") not in ids or _num(e.get("ts")) is None:
            continue
        events.append({"id": str(e["id"]), "cluster": str(e["cluster"]), "ts": _num(e["ts"]),
                       "window_s": _num(e.get("window_s"), 0), "wallets": int(_num(e.get("wallets"), 0) or 0),
                       "share_sold": _num(e.get("share_sold"), 0, 1), "usd": _num(e.get("usd"), 0),
                       "txs": [str(t) for t in e.get("txs") or []][:20]})
    events.sort(key=lambda e: e["ts"], reverse=True)
    risk = raw.get("risk") if isinstance(raw.get("risk"), dict) else {}
    return {"version": VERSION, "chain": str(raw.get("chain") or ""), "token": str(raw["token"]).lower(),
            "symbol": str(raw.get("symbol") or ""), "updated_at": _num(raw.get("updated_at")),
            "risk": {"score": _num(risk.get("score"), 0, 100), "reasons": [str(x) for x in risk.get("reasons") or []][:6]},
            "clusters": sorted(clusters, key=lambda c: -(c["share"] or 0)), "events": events}


def _read(path: Path) -> dict | None:
    try:
        return clean(json.loads(path.read_text(encoding="utf-8")))
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


def due(report: dict, sent: set[str], now: float) -> list[dict]:
    """The waves of this report worth a Telegram alert and not sent yet."""
    return [e for e in report["events"]
            if e["id"] not in sent and now - e["ts"] <= ALERT_MAX_AGE_S
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


async def notify_once(send, url: str, now: float | None = None) -> int:
    """One pass: alerts every new wave of the engine's reports (never the
    sample's). `send` is telegram.send_message. Returns how many went out."""
    found, sample = reports()
    if sample:
        return 0
    now = time.time() if now is None else now
    sent_list = load_sent()
    sent = set(sent_list)
    n = 0
    for r in found:
        for e in sorted(due(r, sent, now), key=lambda e: e["ts"]):
            if await send(message(r, e, url)):
                sent.add(e["id"])
                sent_list.append(e["id"])
                n += 1
    if n:
        save_sent(sent_list)
    return n
