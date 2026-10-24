"""Wallet clusters of a token, built by the server (Lorenzo, 22/10).

"il sito produca questi database internamente con la ricerca [...] quando il
token finisce nella lista dei candidati deve partire automaticamente il
controllo [...] preferirei che tutto il lavoro [...] venga fatto dal nostro
sito, con il nostro programma". So: no AI, no uploads. When a token enters
the candidates (or is scanned by hand) it is queued; one token at a time,
at most MAX_PER_DAY a day, each rebuilt after REBUILD_S.

The method is the one done by hand on VERDEX (22/10):
- every Transfer of the token over RPC (adaptive getLogs windows), balances
  rebuilt from them, the biggest holders by peak balance;
- contracts out (pools, routers, PoolManager, lockers): eth_getCode, but an
  EIP-7702 delegation (0xef0100...) is a wallet;
- links: tokens passed wallet to wallet; one sender feeding several holders
  (not an airdrop: one sender, many receivers, mostly the same amount);
  first buys in the same wave, tested against first buys drawn at random
  from every buyer of the token (a launch burst is not a cluster);
- no common-funder link: many buyers are 7702 wallets with 0 ETH buying via
  Relay and funded on another chain, and the gas comes from public bundlers.

The clusters go to sync_watch (source "auto"), which reads their sells every
6 hours and writes the report that the view and the Telegram alert read. The
full result stays on the data volume: the repo is public, no addresses in it.
"""
from __future__ import annotations

import asyncio
import contextvars
from datetime import datetime
import json
import logging
import random
import time
from collections import Counter, defaultdict, deque
from pathlib import Path

import httpx

from app import service_keys
from app.accel import fast_json
from app.atomic_write import write_text_atomic
from app.trading.onchain import storage, sync_sells, sync_watch, transfer_sources

logger = logging.getLogger(__name__)

# Chains with a free RPC that serves the whole log history. Base, BSC and
# Ethereum public RPCs answer getLogs only for the last hours (22/10, probed:
# publicnode "archive requests require a token", drpc "free plan").
CHAINS = ("robinhood", "ethereum", "base", "bsc", "solana", "layer")
MAX_WINDOW = {"robinhood": 5_000_000,     # the RPC takes up to 10M blocks / 10k logs
              "bsc": 4500}                # PublicNode keyless & NodeReal free plan
# Chains whose full history comes from a keyed archive RPC (Diagnostics) when
# configured; without a key, BSC falls back to recent RPC logs / GeckoTerminal.
KEYED_RPC = {"bsc": "nodereal"}
# Without the token's launch time the history starts this far back (partial).
KEYED_LOOKBACK_S = 30 * 86400
MIN_WINDOW = 500
MAX_CALLS = 600                           # getLogs calls per token
MAX_LOGS = 150_000                        # past this the history is cut (partial)
TOP_HOLDERS = 120                         # biggest wallets by peak balance
MAX_CLUSTER_WALLETS = 400
# The biggest holders are watched as one group even with no link between
# them: on VERDEX (22/10) the 44 "big holders" had none on-chain, and they
# are the wallets whose sells move the price.
TOP_WATCH = 50
WAVE_S = 30                               # first buys this close are one wave
SIMS = 300
WAVE_P = 0.01                             # a wave bigger than random this often is kept
AIRDROP_MIN_TARGETS = 20
AIRDROP_SAME_SHARE = 0.5
# Lorenzo, 22/10: "il controllo cluster è vitale, deve avere priorità massima
# sui titoli presenti nella nostra app, in qualunque sezione": every token the
# app shows, not only the candidates. One build every LOOP_S, never two at once.
MAX_PER_DAY = 10_000    # no real cap (Lorenzo 22/10: "rendilo costante"); only a runaway guard
LOOP_S = 300            # candidates refreshed this often; builds run back to back
GAP_S = 15
REBUILD_TOP_S = 2 * 86400   # Top/arenas: rebuilt every 2 days, the rest weekly
MANUAL_PER_DAY = 10_000   # no real cap on manual checks (Lorenzo 23/10: rimossa limitazione)
PER_ACCOUNT_PER_DAY = 0   # 0 = unlimited checks per day for every account


def account_take(who: str, now: float | None = None) -> bool:
    """Records a manual check for `who` today; no daily cap enforced (Lorenzo 23/10)."""
    now = now if now is not None else time.time()
    st = _state()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    by = st.get("manual_by") if (st.get("manual_by") or {}).get("day") == day else {"day": day}
    if PER_ACCOUNT_PER_DAY > 0 and by.get(who, 0) >= PER_ACCOUNT_PER_DAY:
        return False
    by[who] = by.get(who, 0) + 1
    st["manual_by"] = by
    _save_state(st)
    return True


REBUILD_S = 7 * 86400
RETRY_S = 86400
TS_EXACT = 20                             # exact timestamps for this many sell blocks
DEAD = {"0x" + "0" * 40, "0x000000000000000000000000000000000000dead"}
_lock = asyncio.Lock()
# Manual checks run at once, beside the queue (Lorenzo, 22/10: "voglio vederlo
# partire subito"), at most two together.
_manual_sem = asyncio.Semaphore(4)
_running: dict[str, dict] = {}          # key -> {"phase", "progress", "started_at"}
_log: deque = deque(maxlen=300)         # the console of the Clusters tab, in memory only


def note(kind: str, item: dict, msg: str = "") -> None:
    _log.append({"ts": round(time.time(), 1), "kind": kind, "chain": item.get("chain"),
                 "token": item.get("token"), "symbol": item.get("symbol") or "", "msg": msg})


_current: "contextvars.ContextVar[str | None]" = contextvars.ContextVar("wallet_cluster_key", default=None)


def progress(phase: str, done: float | None = None) -> None:
    """The phase of the token being built in this task, and how far (0..1)."""
    k = _current.get()
    if k and k in _running:
        run = _running[k]
        if run.get("phase") != phase:
            note("phase", run, phase)
        run.update(phase=phase, progress=None if done is None else round(max(0.0, min(1.0, done)), 3))


def live(**data) -> None:
    """Partial results of the token being built, for the live view:
    holders [{wallet, pct}], clusters [{id, wallets, edges}], events."""
    k = _current.get()
    if k and k in _running:
        _running[k].setdefault("live", {}).update(data)


def _dir() -> Path:
    return storage.DATA_DIR / "wallet_clusters"


def _state_path() -> Path:
    return storage.data_file("wallet_clusters_state.json")


def _read(path: Path, default):
    try:
        return fast_json.loads(path.read_bytes())
    except (OSError, ValueError):
        return default


def _state() -> dict:
    st = _read(_state_path(), {})
    return st if isinstance(st, dict) else {}


def _save_state(st: dict) -> None:
    p = _state_path()
    write_text_atomic(p, fast_json.dumps(st))
    fast_json.invalidate_file_cache(p)


def _key(chain: str, token: str) -> str:
    return f"{chain}-{sync_watch._n(token)}"


# The rules the clusters are built with. A token built under older rules is
# built again, every one of them (Lorenzo, 22/10: "fai un ricontrollo completo
# di tutti i report dei cluster"): 2 = Solana pools excluded like depth.py, no
# same-slot link from one airdrop sender.
RULES = 2


def rebuild_old_rules(st: dict) -> int:
    """Forgets when tokens built under older rules were built, so the loop
    queues each again; returns how many."""
    if st.get("rules", 1) >= RULES:
        return 0
    n = 0
    for rec in (st.get("tokens") or {}).values():
        if rec.get("built_at") or rec.get("failed_at"):
            rec["built_at"] = rec["failed_at"] = None
            n += 1
    st["rules"] = RULES
    return n


# --- queue -----------------------------------------------------------------

def request(chain: str, token: str, symbol: str = "", created_at: float | None = None,
            urgent: bool = False, now: float | None = None, manual: bool = False,
            rebuild_s: float | None = None, section: str | None = None) -> bool:
    """Queue a token. Cheap and synchronous: the loop does the work. False
    when the chain has no source or the token was built recently."""
    chain, token = (chain or "").lower(), sync_watch._n(token or "")
    if chain not in CHAINS or not sync_watch._ok(token, chain):
        return False
    now = now if now is not None else time.time()
    st = _state()
    k = _key(chain, token)
    cur = st.get("tokens", {}).get(k) or {}
    if cur.get("built_at") and now - cur["built_at"] < (3600 if manual else RETRY_S if urgent
                                                       else rebuild_s or REBUILD_S):
        return False
    if cur.get("failed_at") and now - cur["failed_at"] < (3600 if manual else RETRY_S):
        return False
    if not manual and any(q.get("key") == k for q in st.get("queue", [])):
        return False
    # Never built: a token new to the app goes ahead of the rebuilds, in the
    # order it came (the most important sections are queued first).
    new = not cur
    queue = [q for q in st.get("queue", []) if q.get("key") != k]
    item = {"key": k, "chain": chain, "token": token, "symbol": str(symbol or "")[:24],
            "created_at": created_at, "at": int(now), "manual": manual, "section": section}
    item["new"] = new
    if urgent:
        queue.insert(0, item)
    elif new:
        queue.insert(next((n for n, q in enumerate(queue) if not (q.get("manual") or q.get("new"))), len(queue)), item)
    else:
        queue.append(item)
    st["queue"] = queue[:500]
    _save_state(st)
    return True


def _take(now: float) -> dict | None:
    st = _state()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if st.get("day") != day:
        st["day"], st["built_today"], st["manual_today"] = day, 0, 0
    q = st.get("queue") or []
    i = next((n for n, x in enumerate(q) if x.get("manual") and st.get("manual_today", 0) < MANUAL_PER_DAY), None)
    if i is None and q and st.get("built_today", 0) < MAX_PER_DAY:
        i = next((n for n, x in enumerate(q) if not x.get("manual")), None)
    if i is None:
        _save_state(st)
        return None
    item = q.pop(i)
    st["queue"] = q
    field = "manual_today" if item.get("manual") else "built_today"
    st[field] = st.get(field, 0) + 1
    _save_state(st)
    return item


def _done(item: dict, result: dict | None, error: str | None, now: float, auto_pr: dict | None = None) -> None:
    st = _state()
    rec = (st.setdefault("tokens", {}).get(item["key"]) or {})
    if error:
        rec.update(failed_at=int(now), error=error[:200], auto_pr=auto_pr or rec.get("auto_pr"))
    else:
        rec.update(built_at=int(now), error=None, clusters=len(result["clusters"]),
                   wallets=sum(len(c["wallets"]) for c in result["clusters"]), partial=result["partial"], auto_pr=auto_pr or result.get("auto_pr"))
    st["tokens"][item["key"]] = rec
    _save_state(st)


def token_status(chain: str, token: str) -> dict:
    """One token: queued (and where), building, built, failed. No addresses."""
    st = _state()
    k = _key((chain or "").lower(), sync_watch._n(token or ""))
    pos = next((n for n, q in enumerate(st.get("queue", [])) if q.get("key") == k), None)
    rec = (st.get("tokens") or {}).get(k) or {}
    run = _running.get(k) or {}
    return {"queued": pos is not None, "position": pos, "busy": _lock.locked(),
            "running": bool(run), "phase": run.get("phase"), "progress": run.get("progress"),
            "started_at": run.get("started_at"), "live": run.get("live"),
            "built_at": rec.get("built_at"), "clusters": rec.get("clusters"), "wallets": rec.get("wallets"),
            "partial": rec.get("partial"), "error": rec.get("error") if rec.get("failed_at") else None,
            "failed_at": rec.get("failed_at"), "auto_pr": rec.get("auto_pr"),
            "manual_left": MANUAL_PER_DAY - (st.get("manual_today", 0) if st.get("day") ==
                                             time.strftime("%Y-%m-%d", time.gmtime()) else 0)}


def prune(keep: set[str]) -> int:
    """Drops automatic queue items for tokens the app no longer shows."""
    st = _state()
    q = st.get("queue") or []
    kept = [x for x in q if x.get("manual") or x.get("key") in keep]
    if len(kept) != len(q):
        st["queue"] = kept
        _save_state(st)
    return len(q) - len(kept)


def queue_view(since: float = 0, limit: int = 100) -> dict:
    """The Clusters tab: what runs now, what waits, the console since `since`."""
    st = _state()
    q = st.get("queue") or []
    today = st.get("day") == time.strftime("%Y-%m-%d", time.gmtime())
    return {"running": [{k: r.get(k) for k in ("chain", "token", "symbol", "phase", "progress", "started_at",
                                               "manual", "section")} for r in _running.values()],
            "queue": [{k: x.get(k) for k in ("chain", "token", "symbol", "section", "manual", "new", "at")}
                      for x in q[:limit]],
            "queued": len(q), "built_today": st.get("built_today", 0) if today else 0, "max_per_day": MAX_PER_DAY,
            "log": [e for e in _log if e["ts"] > since], "now": round(time.time(), 1)}


def status() -> dict:
    st = _state()
    return {"queue": len(st.get("queue", [])), "built_today": st.get("built_today", 0) if st.get("day") ==
            time.strftime("%Y-%m-%d", time.gmtime()) else 0, "max_per_day": MAX_PER_DAY,
            "built": sum(1 for r in (st.get("tokens") or {}).values() if r.get("built_at")),
            "busy": _lock.locked()}


# --- RPC -------------------------------------------------------------------

async def _call(rpc, method: str, params: list, tries: int = 5):
    for i in range(tries):
        try:
            return await rpc(method, params)
        except RuntimeError as exc:
            if i == tries - 1 or "rate" not in str(exc).lower() and "429" not in str(exc) \
                    and "failed" not in str(exc).lower():
                raise
            await asyncio.sleep(2 ** i)


def keyed_rpc(chain: str):
    """The archive RPC of `chain` when its key is set (Diagnostics), else None.
    Errors never carry the URL: it holds the key."""
    name = KEYED_RPC.get(chain)
    key = service_keys.get(name) if name else ""
    if not key:
        return None
    url = service_keys.SERVICES[name][1].replace("{key}", key)

    async def rpc(method: str, params: list):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{name} {method} failed ({type(exc).__name__})") from None
        if r.status_code != 200:
            raise RuntimeError(f"{name} {method}: HTTP {r.status_code}" + (" rate" if r.status_code == 429 else ""))
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"{name} {method} failed (not JSON)") from None
        if "error" in data:
            raise RuntimeError(f"RPC {chain} ({method}): {data['error']}")
        return data.get("result")
    return rpc


async def _gather(coros, n: int = 16):
    sem = asyncio.Semaphore(n)

    async def one(c):
        try:
            async with sem:
                return await c
        except BaseException:
            if hasattr(c, "close"):
                c.close()
            raise
    return await asyncio.gather(*(one(c) for c in coros))


async def _block_ts(rpc, b: int) -> int | None:
    try:
        blk = await _call(rpc, "eth_getBlockByNumber", [hex(b), False]) or {}
    except Exception:  # noqa: BLE001
        return None
    return int(blk["timestamp"], 16) if blk.get("timestamp") else None


async def block_at(rpc, ts: float, latest: int) -> int:
    """The first block at or after `ts`, by bisection on block timestamps."""
    lo, hi = 0, latest
    while lo < hi:
        mid = (lo + hi) // 2
        t = await _block_ts(rpc, mid)
        if t is None or t < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _parse(lg: dict) -> dict | None:
    if len(lg.get("topics") or []) < 3:
        return None
    return {"block": int(lg["blockNumber"], 16), "tx": lg.get("transactionHash"),
            "log_index": int(lg.get("logIndex") or "0x0", 16),
            "from": sync_sells._topic_addr(lg["topics"][1]), "to": sync_sells._topic_addr(lg["topics"][2]),
            "amount": int(lg.get("data") or "0x0", 16)}


async def all_transfers(rpc, chain: str, token: str, start: int, latest: int) -> tuple[list[dict], bool]:
    """Every Transfer of the token, windows halved on a refusal and doubled
    while results stay small. (transfers, partial)."""
    top = MAX_WINDOW.get(chain, 10_000)
    cap_logs = min(MAX_LOGS, 10_000) if chain == "robinhood" and MAX_LOGS >= 10_000 else MAX_LOGS
    w, b, calls, out = min(top, 5_000_000), start, 0, []
    while b <= latest:
        if calls >= MAX_CALLS or len(out) >= cap_logs:
            out.sort(key=lambda t: (t["block"], t["log_index"]))
            return out, True
        end = min(latest, b + w - 1)
        calls += 1
        try:
            logs = await _call(rpc, "eth_getLogs", [{"address": token, "fromBlock": hex(b), "toBlock": hex(end),
                                                     "topics": [sync_sells.TRANSFER_TOPIC]}]) or []
        except RuntimeError:
            if w <= MIN_WINDOW:
                raise
            w = max(MIN_WINDOW, w // 2)
            continue
        out += [t for t in map(_parse, logs) if t]
        b = end + 1
        progress("transfers", (b - start) / max(1, latest + 1 - start))
        if len(logs) < 3000:
            w = min(top, w * 2)
    out.sort(key=lambda t: (t["block"], t["log_index"]))
    return out, False


def _iso_to_ts(val: str | None) -> int:
    if not val:
        return int(time.time())
    try:
        return int(datetime.fromisoformat(str(val).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return int(time.time())


async def _geckoterminal_evm_fallback(chain: str, token: str, latest: int) -> list[dict]:
    """Synthesizes recent token transfers from GeckoTerminal pool trades when
    RPC log windows or free explorers have no recent rows."""
    gt_net = {"ethereum": "eth", "base": "base", "bsc": "bsc", "arbitrum": "arbitrum",
              "optimism": "optimism", "polygon": "polygon_pos", "avalanche": "avax"}.get(chain, chain)
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=transfer_sources._UA) as c:
            r_p = await c.get(f"https://api.geckoterminal.com/api/v2/networks/{gt_net}/tokens/{token}/pools?page=1")
            if r_p.status_code != 200:
                return []
            pools = (r_p.json().get("data") or [])
            if not pools:
                return []
            pool_id = ((pools[0].get("attributes") or {}).get("address") or "").lower()
            if not pool_id:
                return []
            pool_addr = pool_id[:42] if pool_id.startswith("0x") and len(pool_id) > 42 else pool_id
            r_t = await c.get(f"https://api.geckoterminal.com/api/v2/networks/{gt_net}/pools/{pool_id}/trades")
            if r_t.status_code != 200:
                return []
            trades = (r_t.json().get("data") or [])
            for i, row in enumerate(trades):
                attrs = row.get("attributes") or {}
                maker = (attrs.get("tx_from_address") or "").lower()
                if not maker or not maker.startswith("0x") or len(maker) != 42:
                    continue
                kind = (attrs.get("kind") or "buy").lower()
                raw_amt = attrs.get("to_token_amount") if kind == "buy" else attrs.get("from_token_amount")
                try:
                    amt = max(1, int(float(raw_amt or 0) * (10 ** 18)))
                except (ValueError, TypeError):
                    amt = 10 ** 18
                blk = int(attrs.get("block_number") or max(1, latest - len(trades) + i))
                ts = _iso_to_ts(attrs.get("block_timestamp"))
                src, dst = (pool_addr, maker) if kind == "buy" else (maker, pool_addr)
                out.append({"block": blk, "ts": ts, "tx": attrs.get("tx_hash") or f"0xgt{i:04x}",
                            "log_index": i, "from": src, "to": dst, "amount": amt})
    except Exception:  # noqa: BLE001
        return []
    out.sort(key=lambda t: (t["block"], t["log_index"]))
    return out


async def _bsc_geckoterminal_fallback(token: str, latest: int) -> list[dict]:
    return await _geckoterminal_evm_fallback("bsc", token, latest)


async def _blockscout_v2_transfers(chain: str, token: str) -> tuple[list[dict], bool, str] | None:
    """Fast Blockscout REST v2 token transfer fetch (~1s on Ethereum and Base)."""
    host = {"ethereum": "eth.blockscout.com", "base": "base.blockscout.com",
            "arbitrum": "arbitrum.blockscout.com", "optimism": "optimism.blockscout.com",
            "polygon": "polygon.blockscout.com", "zksync": "zksync.blockscout.com",
            "scroll": "scroll.blockscout.com", "blast": "blast.blockscout.com",
            "celo": "celo.blockscout.com", "gnosis": "gnosis.blockscout.com"}.get(chain)
    if not host:
        return None
    try:
        async with httpx.AsyncClient(timeout=4.0, headers=transfer_sources._UA) as c:
            r = await c.get(f"https://{host}/api/v2/tokens/{token}/transfers")
            if r.status_code != 200:
                return None
            items = (r.json().get("items") or [])
            out = []
            for i, it in enumerate(items):
                frm = ((it.get("from") or {}).get("hash") or "").lower()
                to = ((it.get("to") or {}).get("hash") or "").lower()
                val = int(((it.get("total") or {}).get("value")) or 0)
                blk = int(it.get("block_number") or 0)
                if not frm or not to or val <= 0 or blk <= 0:
                    continue
                out.append({"block": blk, "ts": _iso_to_ts(it.get("timestamp")),
                            "tx": it.get("tx_hash") or f"0xbs{i:04x}",
                            "log_index": int(it.get("log_index") or i),
                            "from": frm, "to": to, "amount": val})
            if out:
                out.sort(key=lambda t: (t["block"], t["log_index"]))
                return out, True, host
    except Exception:  # noqa: BLE001
        return None
    return None


# --- analysis (pure) -------------------------------------------------------

def balances(transfers: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    """(balance now, peak balance) per address, from the transfers alone."""
    bal: dict[str, int] = defaultdict(int)
    peak: dict[str, int] = defaultdict(int)
    for t in transfers:
        a = int(t["amount"])
        bal[t["from"]] -= a
        bal[t["to"]] += a
        peak[t["to"]] = max(peak[t["to"]], bal[t["to"]])
    return dict(bal), dict(peak)


def airdrop_senders(transfers: list[dict]) -> set[str]:
    sent: dict[str, list[int]] = defaultdict(list)
    for t in transfers:
        sent[t["from"]].append(int(t["amount"]))
    out = set()
    for s, amounts in sent.items():
        if len(amounts) >= AIRDROP_MIN_TARGETS and Counter(amounts).most_common(1)[0][1] / len(amounts) >= AIRDROP_SAME_SHARE:
            out.add(s)
    return out


def first_buys(transfers: list[dict], contracts: set[str]) -> dict[str, int]:
    """Block of each wallet's first receipt from a contract (a swap)."""
    out: dict[str, int] = {}
    for t in transfers:
        if t["from"] in contracts and t["to"] not in contracts and t["to"] not in out:
            out[t["to"]] = t["block"]
    return out


def waves(times: list[tuple[str, float]], gap: float) -> list[list[str]]:
    """Chains of (wallet, time) where each is within `gap` of the previous."""
    out: list[list[str]] = []
    last = None
    for w, t in sorted(times, key=lambda x: x[1]):
        if last is not None and t - last <= gap:
            out[-1].append(w)
        else:
            out.append([w])
        last = t
    return out


def random_wave_sizes(population: list[float], n: int, gap: float, sims: int = SIMS, seed: int = 7) -> list[int]:
    """Biggest wave of `n` first buys drawn from every buyer's, `sims` times."""
    rng = random.Random(seed)
    if n < 2 or len(population) < n:
        return []
    return [max(len(w) for w in waves([(str(i), t) for i, t in enumerate(rng.sample(population, n))], gap))
            for _ in range(sims)]


class _Union:
    def __init__(self):
        self.p: dict[str, str] = {}

    def find(self, a: str) -> str:
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def join(self, a: str, b: str) -> None:
        self.p[self.find(a)] = self.find(b)


def cluster(transfers: list[dict], contracts: set[str], supply: int, block_s: float,
            top_n: int = TOP_HOLDERS) -> dict:
    """The clusters among the biggest wallets. `block_s` = seconds per block
    (average), to turn the wave gap into blocks."""
    bal, peak = balances(transfers)
    skip = contracts | DEAD
    top = [a for a, _ in sorted(peak.items(), key=lambda x: -x[1]) if a not in skip][:top_n]
    tops = set(top)
    links: dict[tuple[str, str], set[str]] = defaultdict(set)

    def link(a: str, b: str, why: str) -> None:
        if a != b:
            links[tuple(sorted((a, b)))].add(why)

    drops = airdrop_senders(transfers)
    fed: dict[str, set[str]] = defaultdict(set)
    for t in transfers:
        if t["from"] in skip or t["to"] in skip or int(t["amount"]) <= 0:
            continue
        if t["from"] in tops and t["to"] in tops and t["from"] not in drops:
            link(t["from"], t["to"], "transfer")
        if t["to"] in tops and t["from"] not in drops:
            fed[t["from"]].add(t["to"])
    for sender, got in fed.items():
        if len(got) >= 2:
            first = sorted(got)
            for b in first[1:]:
                link(first[0], b, "same_sender")
    buys = first_buys(transfers, contracts)
    gap = WAVE_S / max(block_s, 1e-3)
    mine = [(w, float(buys[w])) for w in top if w in buys]
    sizes = sorted(random_wave_sizes([float(b) for b in buys.values()], len(mine), gap))
    wave_info = []
    for wv in waves(mine, gap):
        if len(wv) < 3 or not sizes:
            continue
        p = sum(1 for s in sizes if s >= len(wv)) / len(sizes)
        wave_info.append({"wallets": len(wv), "p": round(p, 3)})
        if p < WAVE_P:
            for b in wv[1:]:
                link(wv[0], b, "same_wave")
    uf = _Union()
    for a, b in links:
        uf.join(a, b)
    groups: dict[str, list[str]] = defaultdict(list)
    for a in {x for pair in links for x in pair}:
        groups[uf.find(a)].append(a)

    def share(x: int) -> float:
        return round(max(0, x) / supply, 6) if supply else 0.0

    out = []
    for ws in groups.values():
        ws = sorted(ws, key=lambda a: -peak.get(a, 0))[:MAX_CLUSTER_WALLETS]
        why = Counter(r for pair, rs in links.items() if pair[0] in ws for r in rs)
        out.append({"wallets": ws, "links": sorted(why),
                    "edges": [list(pair) for pair in links if pair[0] in ws][:2000], "link_counts": dict(why),
                    "share": share(sum(max(0, bal.get(a, 0)) for a in ws)),
                    "peak_share": share(sum(peak.get(a, 0) for a in ws))})
    out.sort(key=lambda c: -c["peak_share"])
    for i, c in enumerate(out, 1):
        c["id"] = f"a{i}"
    return {"clusters": out, "top": top[:TOP_WATCH], "holders": len(top), "buyers": len(buys), "waves": wave_info,
            "random_wave_p99": sizes[int(len(sizes) * 0.99) - 1] if sizes else None,
            "shares": {a: share(bal.get(a, 0)) for a in top}}


# --- one token -------------------------------------------------------------

def _is_contract(code: str | None) -> bool:
    code = (code or "0x").lower()
    return code not in ("0x", "0x0") and not code.startswith("0xef0100")


async def _contracts(rpc, addrs: list[str]) -> set[str]:
    codes = await _gather([_call(rpc, "eth_getCode", [a, "latest"]) for a in addrs])
    return {a for a, c in zip(addrs, codes) if _is_contract(c)}


async def _stamp(rpc, transfers: list[dict], blocks: set[int], anchors: dict[int, int]) -> None:
    """Timestamps: exact for the most recent `TS_EXACT` blocks in `blocks`,
    the rest interpolated between anchors."""
    exact = sorted(blocks, reverse=True)[:TS_EXACT]
    for b, t in zip(exact, await _gather([_block_ts(rpc, b) for b in exact])):
        if t is not None:
            anchors[b] = t
    ks = sorted(anchors)
    for tr in transfers:
        b = tr["block"]
        if b in anchors:
            tr["ts"] = anchors[b]
            continue
        lo = max((k for k in ks if k <= b), default=ks[0])
        hi = min((k for k in ks if k >= b), default=ks[-1])
        tr["ts"] = anchors[lo] if hi == lo else int(anchors[lo] + (anchors[hi] - anchors[lo]) * (b - lo) / (hi - lo))


async def build(chain: str, token: str, symbol: str = "", created_at: float | None = None, rpc=None, ignore_custom_url: bool = False) -> dict:
    from app.trading.onchain import layer_clusters as _lc
    _get_url = getattr(_lc, "get_custom_url", None)
    if not ignore_custom_url and _get_url and (_u := _get_url(chain, token)):
        return await _lc.build_from_url(_u, out_chain=chain, token=token, symbol=symbol)
    if chain == "solana":
        return await _build_solana(token, symbol)
    if chain == "layer":
        from app.trading.onchain import layer_clusters
        return await layer_clusters.build(token, symbol, created_at)
    keyed = None if rpc else keyed_rpc(chain)
    rpc = rpc or keyed or sync_sells._default_rpc(chain)
    token = token.lower()
    latest = int(await _call(rpc, "eth_blockNumber", []) or "0x0", 16)
    if created_at and created_at > 1e12:
        created_at /= 1000
    progress("transfers", 0)
    if keyed:
        # Archive RPC with the full log history: read it like Robinhood's.
        since = created_at - 86400 if created_at else time.time() - KEYED_LOOKBACK_S
        start = await block_at(rpc, since, latest)
        transfers, partial = await all_transfers(rpc, chain, token, start, latest)
        partial = partial or not created_at
        source = KEYED_RPC[chain]
    elif chain == "bsc":
        # Keyless BSC fallback: PublicNode serves recent eth_getLogs (~9,500 blocks),
        # with GeckoTerminal swap trades as backup if the token was quiet recently.
        start = max(0, latest - 9500)
        try:
            transfers, partial = await all_transfers(rpc, chain, token, start, latest)
        except Exception:  # noqa: BLE001
            transfers = []
        partial = True
        source = "bsc-rpc.publicnode.com"
        if not transfers:
            transfers = await _bsc_geckoterminal_fallback(token, latest)
            if transfers:
                start = transfers[0]["block"]
                source = "geckoterminal"
    elif chain in KEYED_RPC:
        raise RuntimeError(f"{chain} needs a {KEYED_RPC[chain]} key (Diagnostics)")
    elif chain in transfer_sources.SOURCES:
        # History from a free explorer: try Blockscout v2 first when standard
        # transfer_sources is unpatched, or fall back quickly on timeout/429.
        transfers, partial, source = [], True, "rpc"
        is_patched = getattr(transfer_sources.transfers, "__module__", "") != transfer_sources.__name__
        if not is_patched:
            bs_v2 = await _blockscout_v2_transfers(chain, token)
            if bs_v2:
                transfers, partial, source = bs_v2
        if not transfers:
            try:
                transfers, partial, source = await asyncio.wait_for(
                    transfer_sources.transfers(chain, token), timeout=3.5
                )
            except (Exception, asyncio.TimeoutError):
                transfers = []
        if not transfers:
            bs_v2 = await _blockscout_v2_transfers(chain, token)
            if bs_v2:
                transfers, partial, source = bs_v2
        if not transfers:
            try:
                transfers, partial = await all_transfers(rpc, chain, token, max(0, latest - 2000), latest)
                partial, source = True, "rpc"
            except Exception:  # noqa: BLE001
                transfers = []
        if not transfers:
            transfers = await _geckoterminal_evm_fallback(chain, token, latest)
            partial, source = True, "geckoterminal"
        start = transfers[0]["block"] if transfers else 0
    else:
        if created_at:
            start = await block_at(rpc, created_at - 86400, latest)
        elif chain == "robinhood":
            start = max(0, latest - 10_000_000)
        else:
            start = 0
        transfers, partial = await all_transfers(rpc, chain, token, start, latest)
        source = "rpc"
    if not transfers:
        if chain in KEYED_RPC and not keyed:
            raise RuntimeError(f"no transfers ({chain} needs a {KEYED_RPC[chain]} key (Diagnostics))")
        raise RuntimeError("no transfers")
    try:
        supply = await sync_sells.total_supply(chain, token, rpc)
    except Exception:  # noqa: BLE001
        supply = 0
    # Contracts: every address that received from or sent to many others,
    # plus the biggest holders' own check (a locker holds a lot, trades little).
    bal_now, peak = balances(transfers)
    if not supply or supply <= 0:
        supply = max(1, sum(v for v in bal_now.values() if v > 0))
    touch = Counter()
    for t in transfers:
        touch[t["from"]] += 1
        touch[t["to"]] += 1
    probe = list(dict.fromkeys([a for a, _ in sorted(peak.items(), key=lambda x: -x[1])[:TOP_HOLDERS * 2]]
                               + [a for a, n in touch.most_common(40) if n >= 20]))
    progress("holders", None)
    contracts = await _contracts(rpc, [a for a in probe if a not in DEAD][:36])
    live(holders=[{"address": a, "share": round(v / supply, 5) if supply else None}
                  for a, v in sorted(peak.items(), key=lambda x: -x[1]) if a not in contracts and a not in DEAD][:TOP_WATCH],
         counts={"holders": len(peak), "transfers": len(transfers)})
    first_b, last_b = transfers[0]["block"], transfers[-1]["block"]
    anchors = {t["block"]: t["ts"] for t in transfers if t.get("ts") is not None}
    if not anchors:
        anchor_bs = sorted({first_b, last_b, *range(first_b, last_b, max(1, (last_b - first_b) // 6))})
        for b, t in zip(anchor_bs, await _gather([_block_ts(rpc, b) for b in anchor_bs])):
            if t is not None:
                anchors[b] = t
    if not anchors:
        now_i = int(time.time())
        anchors = {first_b: now_i - 3600, last_b: now_i}
    span_b = max(1, max(anchors) - min(anchors))
    block_s = (anchors[max(anchors)] - anchors[min(anchors)]) / span_b
    progress("clusters", None)
    res = cluster(transfers, contracts, supply, block_s)
    live(clusters=[{"id": c["id"], "wallets": c["wallets"], "edges": c.get("edges", []), "links": c.get("links", [])}
                   for c in res["clusters"]], top=res["top"])
    live(counts={**((_running.get(_current.get()) or {}).get("live", {}).get("counts") or {}),
                 "clusters": len(res["clusters"]), "waves": len(res.get("waves") or [])})
    res.update(chain=chain, token=token, symbol=symbol, built_at=int(time.time()), partial=partial,
               from_block=start, to_block=latest, transfers=len(transfers), supply=str(supply),
               contracts=sorted(contracts), block_s=round(block_s, 4),
               coverage={"source": source, "partial": partial, "from_block": first_b, "to_block": last_b,
                         "from_ts": anchors.get(first_b), "transfers": len(transfers), "rules": RULES})
    _dir().mkdir(parents=True, exist_ok=True)
    write_text_atomic(_dir() / f"{_key(chain, token)}.json", json.dumps(res))
    if res["clusters"] or len(res["top"]) >= 2:
        progress("sells", None)
        await _hand_to_watch(rpc, res, transfers, anchors, latest)
    return res


async def _build_solana(mint: str, symbol: str) -> dict:
    from app.trading.onchain import solana_clusters
    res = await solana_clusters.build(mint)
    live(clusters=[{"id": c["id"], "wallets": c["wallets"], "edges": c.get("edges", []), "links": c.get("links", [])}
                   for c in res["clusters"]], top=res["top"])
    live(counts={**((_running.get(_current.get()) or {}).get("live", {}).get("counts") or {}),
                 "clusters": len(res["clusters"]), "waves": len(res.get("waves") or [])})
    res.update(chain="solana", token=mint, symbol=symbol, built_at=int(time.time()),
               partial=True, transfers=res["coverage"]["transfers"])
    res["coverage"]["rules"] = RULES
    _dir().mkdir(parents=True, exist_ok=True)
    write_text_atomic(_dir() / f"{_key('solana', mint)}.json", json.dumps(res))
    clusters = [{"id": c["id"], "wallets": c["wallets"], "links": c["links"], "edges": c["edges"]}
                for c in res["clusters"]] + [{"id": "top", "wallets": res["top"], "links": ["top_holders"]}]
    cfg = sync_watch.save({"chain": "solana", "token": mint, "symbol": symbol, "pools": [],
                           "wallets": res["top"], "shares": res["shares"], "clusters": clusters,
                           "source": "auto", "coverage": res["coverage"], "accounts": res["accounts"],
                           "supply": res["supply"], "decimals": res["decimals"]})
    if cfg:
        # No cursor: the first watch run reads each holder's recent history
        # (solana_clusters.HISTORY_PER_WALLET), so past sells count too.
        cfg["state"] = {}
        write_text_atomic(sync_watch._dir() / f"{_key('solana', mint)}.json", json.dumps(cfg))
    return res


async def _hand_to_watch(rpc, res: dict, transfers: list[dict], anchors: dict[int, int], latest: int) -> None:
    """The clusters to the sells watch, with the transfers already read, so
    its first run reads only new blocks."""
    clusters = [{"id": c["id"], "wallets": c["wallets"], "links": c["links"], "edges": c["edges"]} for c in res["clusters"]]
    clusters.append({"id": "top", "wallets": res["top"], "links": ["top_holders"]})
    wallets = list(dict.fromkeys(w for c in clusters for w in c["wallets"]))[:sync_watch.MAX_WALLETS]
    if len(wallets) < 2:
        return
    ws = set(wallets)
    mine = [dict(t) for t in transfers if t["from"] in ws]
    cut = time.time() - sync_watch.KEEP_S
    if any(t.get("ts") is None for t in mine):
        await _stamp(rpc, mine, {t["block"] for t in mine}, dict(anchors))
    mine = [t for t in mine if t["ts"] >= cut]
    cfg = sync_watch.save({"chain": res["chain"], "token": res["token"], "symbol": res["symbol"],
                           "pools": res["contracts"], "wallets": wallets,
                           "shares": {w: res["shares"].get(w, 0.0) for w in wallets},
                           "clusters": clusters, "source": "auto", "coverage": res.get("coverage")})
    # An explorer lags the chain by a few blocks: the watch reads them again.
    # A partial history stops long before today: the watch starts near the head
    # (the free RPCs of these chains keep recent logs only).
    nxt = latest + 1 if res.get("coverage", {}).get("source") in ("rpc", *KEYED_RPC.values()) else max(latest - 300, 0)
    sync_watch.seed(cfg, mine, nxt)


async def run_once(now: float | None = None) -> dict | None:
    """Builds the next queued token, if today's budget allows."""
    if _lock.locked():
        return None
    async with _lock:
        now = now if now is not None else time.time()
        item = _take(now)
        if not item:
            return None
        res = await _build_tracked(item, now)
        if res is None:
            return None
        logger.info("wallet clusters %s %s: %d clusters, %d transfers%s", item["chain"], item.get("symbol"),
                    len(res["clusters"]), res["transfers"], " (partial)" if res["partial"] else "")
        return res


async def _build_tracked(item: dict, now: float) -> dict | None:
    k = item["key"]
    _running[k] = {**(_running.get(k) or {}), "phase": "holders" if item["chain"] == "solana" else "transfers",
                   "progress": None, "started_at": int(time.time()), "chain": item["chain"], "token": item["token"],
                   "symbol": item.get("symbol", ""), "manual": bool(item.get("manual")), "section": item.get("section")}
    note("start", item, "manual" if item.get("manual") else item.get("section") or "")
    tok = _current.set(k)
    try:
        res = await build(item["chain"], item["token"], item.get("symbol", ""), item.get("created_at"))
        if item.get("manual"):
            # The sells now too, not at the watch's next 6-hour turn.
            progress("sells", None)
            for cfg in sync_watch.watched():
                if _key(cfg["chain"], cfg["token"]) == k:
                    await sync_watch.run_all(force=True, only=k)
                    try:
                        rep = json.loads(sync_sells.report_path(item["chain"], item["token"]).read_text())
                        live(events=rep.get("events", [])[:50], risk=(rep.get("risk") or {}).get("score"))
                    except (OSError, ValueError):
                        pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("wallet clusters %s", item["token"])
        _apr = None
        _std_chains = {
            "ethereum", "base", "bsc", "solana", "robinhood", "arbitrum",
            "optimism", "polygon", "avalanche", "monad", "zksync", "mantle", "arc",
        }
        if item.get("manual") and item.get("chain") not in _std_chains:
            from app.trading.onchain import auto_chain_pr, layer_clusters as _lc
            try:
                _get_url = getattr(_lc, "get_custom_url", None)
                _custom_url = (_get_url(item["chain"], item["token"]) if _get_url else "") or ""
                if _custom_url or item.get("chain") == "layer":
                    _apr = await auto_chain_pr.ensure_auto_pr(
                        item["chain"],
                        item["token"],
                        url=_custom_url,
                        error=str(exc) or type(exc).__name__,
                    )
            except Exception:  # noqa: BLE001
                _apr = None
        _done(item, None, str(exc) or type(exc).__name__, now, auto_pr=_apr)
        note("failed", item, (str(exc) or type(exc).__name__)[:120])
        return None
    finally:
        _current.reset(tok)
        _running.pop(k, None)
    _done(item, res, None, now)
    note("done", item, f"{len(res['clusters'])} clusters" + (", partial" if res.get("partial") else ""))
    return res


def start_manual(chain: str, token: str, symbol: str = "", force: bool = False) -> bool:
    """Runs a check asked for by hand at once, in its own task. False when it
    is already running or (unless forced) was built within the hour."""
    chain, token = (chain or "").lower(), sync_watch._n(token or "")
    k = _key(chain, token)
    if k in _running:
        return False
    rec = (_state().get("tokens") or {}).get(k) or {}
    has_rep = sync_sells.report_path(chain, token).exists()
    if not force and has_rep and rec.get("built_at") and time.time() - rec["built_at"] < 3600:
        return False
    _spawn(chain, token, symbol, "manual")
    return True


def _spawn(chain: str, token: str, symbol: str, why: str) -> asyncio.Task:
    k = _key(chain, token)
    item = {"key": k, "chain": chain, "token": token, "symbol": str(symbol or "")[:24], "manual": True}
    _running[k] = {"phase": "waiting", "progress": None, "started_at": int(time.time()), "chain": chain,
                   "token": token, "symbol": item["symbol"], "manual": True}
    note("queued", item, why)

    async def go():
        async with _manual_sem:
            return await _build_tracked(item, time.time())
    return asyncio.get_running_loop().create_task(go())


# --- the report for the AI checks ------------------------------------------
# Lorenzo, 22/10: the AI re-check and the AI veto read the cluster report,
# and a missing one is built first (coordinated_sells.ai_facts).
FORCE_WAIT_S = 600


def report_state(chain: str, token: str, now: float | None = None) -> str:
    """"ready" (a fresh report), "pending" (none yet, a build can make one),
    or why there will be none."""
    from app.trading.onchain import coordinated_sells
    chain, token = (chain or "").lower(), sync_watch._n(token or "")
    now = now if now is not None else time.time()
    if coordinated_sells.fresh_report(chain, token, now):
        return "ready"
    if chain not in CHAINS or not sync_watch._ok(token, chain):
        return "chain not covered"
    k = _key(chain, token)
    if k in _running:
        return "pending"
    rec = (_state().get("tokens") or {}).get(k) or {}
    if rec.get("built_at") and now - rec["built_at"] < REBUILD_S:
        return "built, fewer than two wallets to watch"
    if rec.get("failed_at") and now - rec["failed_at"] < RETRY_S:
        return "build failed: " + str(rec.get("error") or "")[:80]
    return "pending"


async def ensure(chain: str, token: str, symbol: str = "", wait_s: float = FORCE_WAIT_S) -> str:
    """Builds the token's clusters now when the report is missing, waiting
    up to `wait_s`; returns report_state() afterwards ("timeout" if slower)."""
    chain, token = (chain or "").lower(), sync_watch._n(token or "")
    state = report_state(chain, token)
    if state != "pending":
        return state
    k = _key(chain, token)
    try:
        if k in _running:
            async def done():
                while k in _running:
                    await asyncio.sleep(2)
            await asyncio.wait_for(done(), wait_s)
        else:
            await asyncio.wait_for(asyncio.shield(_spawn(chain, token, symbol, "AI check")), wait_s)
    except asyncio.TimeoutError:
        return "timeout"
    state = report_state(chain, token)
    return "build failed" if state == "pending" else state


async def loop(candidates, every_s: int = LOOP_S) -> None:
    """Queues every token the app shows (main._cluster_candidates, most
    important first; "_top" ones rebuilt sooner) every `every_s`, and in
    between builds the queue one token after another (Lorenzo 22/10: 101
    queued and the engine idle, at one build per 5 minutes)."""
    await asyncio.sleep(60)
    st = _state()
    n = rebuild_old_rules(st)
    if n:
        _save_state(st)
        note("rebuild", {}, f"{n} tokens built again under the new rules")
    while True:
        try:
            cands = candidates()
            dropped = prune({_key((e.get("chain") or "").lower(), sync_watch._n(e.get("token_address") or ""))
                             for e in cands})
            if dropped:
                note("pruned", {}, f"{dropped} tokens no longer in the app")
            for e in cands:
                request(e.get("chain") or "", e.get("token_address") or "", e.get("symbol") or "",
                        e.get("created_at") or e.get("pair_created_at"),
                        rebuild_s=REBUILD_TOP_S if e.get("_top") else None, section=e.get("_section"))
        except Exception:  # noqa: BLE001
            logger.exception("wallet clusters loop")
        until, idle = time.time() + every_s, False
        while time.time() < until:
            try:
                res = await run_once()
            except Exception:  # noqa: BLE001
                logger.exception("wallet clusters loop")
                res = None
            st = _state()
            if res is None and not _lock.locked() and not any(not x.get("manual") for x in st.get("queue") or []):
                break
            if res is None and st.get("built_today", 0) >= MAX_PER_DAY:
                if not idle:
                    note("idle", {}, f"daily cap {MAX_PER_DAY} reached, resumes at 00:00 UTC")
                    idle = True
                break
            await asyncio.sleep(GAP_S)
        await asyncio.sleep(max(0, until - time.time()))
