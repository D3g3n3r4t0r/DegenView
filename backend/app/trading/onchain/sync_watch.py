"""The tokens whose wallet clusters the server watches, uploaded from the site.

Lorenzo, 22/10: "sta roba deve andare nel sito e non su github". The repo
is public, so the cluster (token, its wallets, its pools) never lives in it:
whitekobra uploads it from the Coordinated sells view, it is saved on the
data volume, and every run reads the new Transfer logs of those wallets,
keeps them, and rewrites the token's report (sync_sells.report) that the
view and the Telegram alert read.

Upload format: sync_sells.SAMPLE's, the file the cluster research writes:
{"chain", "token", "symbol"?, "decimals"?, "pools": [..], "wallets": [..],
 "extra_wallets"?: [..], "details"?: [{"address", "pct_now"}],
 "shares"?: {address: 0..1}, "from_block"?: int}. Unknown fields are ignored.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from app.atomic_write import write_text_atomic
from app.trading.onchain import storage, sync_sells

logger = logging.getLogger(__name__)

CHAINS = ("robinhood", "ethereum", "base", "bsc")
MAX_WALLETS = 500
RUN_EVERY_S = 6 * 3600
# A first run without "from_block" reads this far back (~3 days at the
# Robinhood Chain's ~0.1 s blocks): the whole history is thousands of calls.
FIRST_BLOCKS = 2_600_000
KEEP_S = 30 * 86400      # transfers older than this drop out of the report
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_lock = asyncio.Lock()


def _dir() -> Path:
    return storage.DATA_DIR / "coordinated_sells_watch"


def _key(chain: str, token: str) -> str:
    return f"{chain}-{token.lower()}"


def _addrs(v, field: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(a, str) and _ADDR.match(a) for a in v):
        raise ValueError(f"{field}: a list of 0x addresses")
    return list(dict.fromkeys(a.lower() for a in v))


def clean(raw: dict) -> dict:
    """The upload, checked. Raises ValueError with what is wrong."""
    if not isinstance(raw, dict):
        raise ValueError("Not a JSON object")
    chain = str(raw.get("chain") or "").lower()
    if chain not in CHAINS:
        raise ValueError(f"chain: one of {', '.join(CHAINS)}")
    token = str(raw.get("token") or "")
    if not _ADDR.match(token):
        raise ValueError("token: a 0x address")
    wallets = _addrs(raw.get("wallets"), "wallets") + _addrs(raw.get("extra_wallets"), "extra_wallets")
    wallets = list(dict.fromkeys(wallets))
    if not 2 <= len(wallets) <= MAX_WALLETS:
        raise ValueError(f"wallets: between 2 and {MAX_WALLETS}")
    shares = {}
    for d in raw.get("details") or []:
        if isinstance(d, dict) and isinstance(d.get("address"), str) and isinstance(d.get("pct_now"), (int, float)):
            shares[d["address"].lower()] = max(0.0, min(1.0, d["pct_now"] / 100))
    for a, v in (raw.get("shares") or {}).items() if isinstance(raw.get("shares"), dict) else []:
        if isinstance(a, str) and isinstance(v, (int, float)):
            shares[a.lower()] = max(0.0, min(1.0, float(v)))
    from_block = raw.get("from_block")
    return {"chain": chain, "token": token.lower(), "symbol": str(raw.get("symbol") or "")[:24],
            "decimals": int(raw.get("decimals") or 18), "pools": _addrs(raw.get("pools"), "pools"),
            "wallets": wallets, "shares": shares,
            "from_block": int(from_block) if isinstance(from_block, int) and from_block > 0 else None,
            "uploaded_at": int(time.time())}


def save(raw: dict) -> dict:
    cfg = clean(raw)
    path = _dir() / f"{_key(cfg['chain'], cfg['token'])}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = _load(path)
    # Same wallets: keep what was already read; new wallets: read again.
    if old and old.get("wallets") == cfg["wallets"]:
        cfg["state"] = old.get("state") or {}
    write_text_atomic(path, json.dumps(cfg))
    return cfg


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def watched() -> list[dict]:
    d = _dir()
    if not d.is_dir():
        return []
    return [c for p in sorted(d.glob("*.json"))
            if not p.name.endswith(".transfers.json") and isinstance(c := _load(p), dict)]


def summary() -> list[dict]:
    """What the view lists: no addresses beyond the token."""
    return [{"chain": c["chain"], "token": c["token"], "symbol": c.get("symbol", ""),
             "wallets": len(c.get("wallets") or []), "pools": len(c.get("pools") or []),
             "last_run": (c.get("state") or {}).get("last_run"), "error": (c.get("state") or {}).get("error")}
            for c in watched()]


def remove(chain: str, token: str) -> bool:
    key = _key(chain, token)
    found = False
    for p in (_dir() / f"{key}.json", _dir() / f"{key}.transfers.json"):
        if p.exists():
            p.unlink()
            found = True
    return found


async def run_one(cfg: dict, rpc=None) -> dict:
    """Reads the new blocks, keeps the transfers, rewrites the report."""
    rpc = rpc or sync_sells._default_rpc(cfg["chain"])
    key = _key(cfg["chain"], cfg["token"])
    tpath = _dir() / f"{key}.transfers.json"
    state = dict(cfg.get("state") or {})
    latest = int(await rpc("eth_blockNumber", []) or "0x0", 16)
    start = state.get("next_block") or cfg.get("from_block") or max(0, latest - FIRST_BLOCKS)
    transfers = (_load(tpath) or []) if state.get("next_block") else []
    if start <= latest:
        transfers += await sync_sells.fetch_transfers(cfg["chain"], cfg["token"], cfg["wallets"], start, latest, rpc)
        cut = time.time() - KEEP_S
        transfers = [t for t in transfers if t.get("ts") is None or t["ts"] >= cut]
        write_text_atomic(tpath, json.dumps(transfers))
    supply = await sync_sells.total_supply(cfg["chain"], cfg["token"], rpc)
    rep = sync_sells.report(cfg["chain"], cfg["token"], transfers, [{"id": "c1", "wallets": cfg["wallets"]}],
                            cfg["pools"], supply, cfg.get("symbol", ""), cfg.get("shares"))
    sync_sells.write_report(rep)
    state.update(next_block=latest + 1, last_run=int(time.time()), error=None)
    return state


def busy() -> bool:
    return _lock.locked()


async def run_all(force: bool = False) -> int:
    """Every watched token due a run (or all with force). Returns how many ran."""
    n = 0
    async with _lock:
        for cfg in watched():
            st = cfg.get("state") or {}
            if not force and time.time() - (st.get("last_run") or 0) < RUN_EVERY_S:
                continue
            try:
                cfg["state"] = await run_one(cfg)
                n += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("sync watch %s", cfg.get("token"))
                cfg["state"] = {**st, "last_run": int(time.time()), "error": str(exc)[:200]}
            path = _dir() / f"{_key(cfg['chain'], cfg['token'])}.json"
            now = _load(path)
            # Re-uploaded or removed while this ran: the new upload wins.
            if now and now.get("uploaded_at") == cfg.get("uploaded_at"):
                write_text_atomic(path, json.dumps(cfg))
    return n
