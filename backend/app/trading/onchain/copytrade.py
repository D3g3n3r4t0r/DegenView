"""Copy trading of Solana wallets (classic site, Trading tab).

Asked on 22/10: "scrivendo l'indirizzo del wallet, si puo' fare copy
trading praticamente quasi istantaneo [...] scegliere se copiare solo
l'ingresso o sia ingresso che uscita [...] una percentuale [...] rispetto al
trade originale [...] oppure una quota fissa, per esempio 50 dollari ogni
posizione che si apre nuova". Choices made when asked: re-buys ignored with
the fixed amount; caps $100 a trade, $500 a day, 10 open positions; every
account can use it, real money only after the account's own consent and the
server's switch; simulated first.

How it works:
- detection: one WebSocket (Helius with the key saved in Diagnostics, else
  the public node) with a logsSubscribe per followed wallet, plus a poll of
  the latest signatures as a safety net. Both feed handle_signature(),
  which dedupes on the leader's signature;
- reading: getTransaction (jsonParsed) and parse_swap(): how the wallet's
  SOL, WSOL, USDC/USDT and token balances moved. One token up = buy, one
  token down = sell; anything else (transfers, token-to-token) is ignored;
- sizing: pct of the leader's USD, or a fixed amount per new position;
  exits copy the share of his position he sold, never his dollars;
- guards: chase (our price vs his), buy price impact, a sell route on
  Jupiter (no route = possible honeypot), freeze/mint authority, min $5,
  the caps above, a trade older than FRESH_S is never chased;
- execution: "sim" quotes Jupiter and books the fill; "real" goes through
  execute.execute_order (ledger, idempotency on the leader's signature,
  settings.onchain_execution_enabled) with a priority fee.
Solana only for now: the chain-specific parts are parse_swap, the watcher
and the quotes, so another chain is a second set of those.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx

from app.atomic_write import write_text_atomic
from app.trading.onchain import quotes
from app.trading.onchain.storage import data_file

logger = logging.getLogger(__name__)

STORE_FILE = data_file("copytrade.json")
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
           "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT"}
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
PUBLIC_WS = "wss://api.mainnet-beta.solana.com"

MODES = ("off", "sim", "real")
COPIES = ("entry", "both")
SIZINGS = ("pct", "fixed")
# $50 a trade since 23/10 ("max $50 a trade, $500 al giorno, max 10 posizioni"); it was $100.
DEFAULT_LIMITS = {"max_trade_usd": 50.0, "max_day_usd": 500.0, "max_open": 10}
_OLD_MAX_TRADE = 100.0
DEFAULT_FOLLOW = {"mode": "sim", "copy": "both", "sizing": "pct", "pct": 10.0, "fixed_usd": 50.0,
                  "max_chase_pct": 15.0, "slippage_pct": 5.0}
MIN_USD = 5.0              # below this the fees eat the trade
MAX_IMPACT_PCT = 8.0       # our own buy moving the pool more than this: skipped
MAX_ROUNDTRIP_LOSS_PCT = 40.0  # buying then selling straight back must not lose more
FRESH_S = 90               # a leader trade older than this is not chased
MIN_LEADER_SOL = 0.005     # less than this spent is rent or a fee, not a buy
SOL_RESERVE = 0.02         # always left for fees and token accounts
PRIORITY_MAX_LAMPORTS = 2_000_000
MAX_FOLLOWS = 20
KEEP_TRADES = 300
POLL_S_HELIUS, POLL_S_PUBLIC = 6, 20

_store: dict | None = None
_locks: dict[str, asyncio.Lock] = {}
_handled: set[str] = set()
_mint_cache: dict[str, tuple[float, dict]] = {}
status: dict = {"ws": "off", "source": None, "last_event": None, "addresses": 0, "error": ""}


# ── store ─────────────────────────────────────────────────────────────────

def _load() -> dict:
    global _store
    if _store is None:
        try:
            _store = json.loads(STORE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _store = {}
        _store.setdefault("users", {})
    return _store


def _save() -> None:
    write_text_atomic(STORE_FILE, json.dumps(_load(), separators=(",", ":")))


def account(owner_id: str) -> dict:
    users = _load()["users"]
    acc = users.setdefault(owner_id, {})
    acc.setdefault("limits", dict(DEFAULT_LIMITS))
    if not acc.get("limits_set_at") and acc["limits"].get("max_trade_usd") == _OLD_MAX_TRADE:
        acc["limits"]["max_trade_usd"] = DEFAULT_LIMITS["max_trade_usd"]   # the old default, never chosen by hand
    acc.setdefault("follows", {})
    acc.setdefault("positions", {})
    acc.setdefault("trades", [])
    acc.setdefault("spent", {"day": "", "usd": 0.0})
    acc.setdefault("real_ok_at", None)
    return acc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def spent_today(acc: dict) -> float:
    s = acc["spent"]
    return s["usd"] if s.get("day") == _today() else 0.0


def _add_spent(acc: dict, usd: float) -> None:
    if acc["spent"].get("day") != _today():
        acc["spent"] = {"day": _today(), "usd": 0.0}
    acc["spent"]["usd"] += usd


def open_count(acc: dict) -> int:
    return sum(len(p) for p in acc["positions"].values())


def watched(kind: str | None = None) -> dict[str, list[str]]:
    """Leader address -> owners following it with a mode other than off.
    kind "solana" or "evm" keeps only those addresses: the Solana socket must
    never be asked to subscribe to a 0x address (copytrade_evm.py)."""
    from app.trading.onchain import copytrade_evm
    out: dict[str, list[str]] = {}
    for owner, acc in _load()["users"].items():
        for addr, f in acc.get("follows", {}).items():
            if f.get("mode") == "off":
                continue
            if kind is not None and copytrade_evm.is_evm(addr) != (kind == "evm"):
                continue
            out.setdefault(addr, []).append(owner)
    return out


def valid_address(addr: str) -> bool:
    from solders.pubkey import Pubkey
    try:
        return len(addr) >= 32 and str(Pubkey.from_string(addr)) == addr
    except Exception:  # noqa: BLE001
        return False


def set_follow(owner_id: str, address: str, fields: dict) -> dict:
    """Add or change a followed wallet; raises ValueError on a bad value.
    A 0x address is an EVM wallet (copytrade_evm.py), copied on the chains
    picked in fields["chains"] (every supported one by default)."""
    from app.trading.onchain import copytrade_evm
    evm = copytrade_evm.is_evm(address)
    if evm:
        address = copytrade_evm.norm(address)
    elif not valid_address(address):
        raise ValueError("Not a Solana or EVM wallet address.")
    acc = account(owner_id)
    if address not in acc["follows"] and len(acc["follows"]) >= MAX_FOLLOWS:
        raise ValueError(f"At most {MAX_FOLLOWS} wallets.")
    f = {**DEFAULT_FOLLOW, "address": address, "label": "", "added_at": time.time(),
         **acc["follows"].get(address, {})}
    for k, v in fields.items():
        if v is not None and k in ("label", "mode", "copy", "sizing", "pct", "fixed_usd", "max_chase_pct", "slippage_pct"):
            f[k] = v
    if f["mode"] not in MODES or f["copy"] not in COPIES or f["sizing"] not in SIZINGS:
        raise ValueError("Unknown mode.")
    if not (0 < float(f["pct"]) <= 1000) or not (0 < float(f["fixed_usd"]) <= 1_000_000):
        raise ValueError("Size out of range.")
    if not (0 < float(f["max_chase_pct"]) <= 500) or not (0.1 <= float(f["slippage_pct"]) <= 50):
        raise ValueError("Chase or slippage out of range.")
    if f["mode"] == "real" and not acc["real_ok_at"]:
        raise ValueError("Confirm real money for this account first.")
    if evm:
        if f["mode"] == "real":
            # Phase 3 of the EVM plan (HANDOVER.md): only after the simulation has been watched.
            raise ValueError("EVM wallets are copied in Simulated for now: real money on EVM networks comes later.")
        chains = fields.get("chains") if fields.get("chains") is not None else f.get("chains") or list(copytrade_evm.CHAINS)
        chains = [c for c in copytrade_evm.CHAINS if c in set(chains)]
        if not chains:
            raise ValueError("Pick at least one network.")
        f["chains"] = chains
    f["label"] = str(f["label"])[:40]
    acc["follows"][address] = f
    _save()
    return f


def remove_follow(owner_id: str, address: str) -> None:
    from app.trading.onchain import copytrade_evm
    acc = account(owner_id)
    acc["follows"].pop(copytrade_evm.norm(address) if copytrade_evm.is_evm(address) else address, None)
    _save()


def set_limits(owner_id: str, limits: dict) -> dict:
    acc = account(owner_id)
    for k in DEFAULT_LIMITS:
        if limits.get(k) is not None:
            v = float(limits[k])
            if v <= 0:
                raise ValueError(f"{k} must be above zero.")
            acc["limits"][k] = int(v) if k == "max_open" else v
    acc["limits_set_at"] = time.time()
    _save()
    return acc["limits"]


def set_real_ok(owner_id: str, ok: bool) -> None:
    acc = account(owner_id)
    acc["real_ok_at"] = time.time() if ok else None
    if not ok:
        for f in acc["follows"].values():
            if f["mode"] == "real":
                f["mode"] = "sim"
    _save()


def _log(acc: dict, row: dict) -> dict:
    acc["trades"].insert(0, {"t": time.time(), **row})
    del acc["trades"][KEEP_TRADES:]
    return row


# ── reading a transaction ─────────────────────────────────────────────────

def _key(k) -> str:
    return k["pubkey"] if isinstance(k, dict) else k


def parse_swap(tx: dict, wallet: str) -> dict | None:
    """The wallet's swap in a jsonParsed getTransaction, or None when the
    transaction is not one (failed, a transfer, token-to-token, dust).

    {side, mint, decimals, units, sol, stable_usd, frac, block_time}: units is
    the token amount bought/sold, sol/stable_usd what was paid or received,
    frac the share of his position a sell took (1.0 when it emptied it)."""
    meta = (tx or {}).get("meta") or {}
    if meta.get("err") is not None or not tx.get("transaction"):
        return None
    keys = [_key(k) for k in tx["transaction"]["message"].get("accountKeys", [])]
    if wallet not in keys:
        return None
    i = keys.index(wallet)
    lamports = meta["postBalances"][i] - meta["preBalances"][i]
    if i == 0:
        lamports += meta.get("fee", 0)          # the network fee is not the trade
    deltas: dict[str, list] = {}               # mint -> [pre_raw, post_raw, decimals]
    for name, slot in (("preTokenBalances", 0), ("postTokenBalances", 1)):
        for b in meta.get(name) or []:
            if b.get("owner") != wallet:
                continue
            ui = b.get("uiTokenAmount") or {}
            row = deltas.setdefault(b["mint"], [0, 0, ui.get("decimals", 0)])
            row[slot] += int(ui.get("amount") or 0)
    sol = lamports / 1e9
    stable = 0.0
    tokens = {}
    for mint, (pre, post, dec) in deltas.items():
        if mint == WSOL:
            sol += (post - pre) / 1e9
        elif mint in STABLES:
            stable += (post - pre) / 10 ** dec
        elif post != pre:
            tokens[mint] = (pre, post, dec)
    if len(tokens) != 1:
        return None
    mint, (pre, post, dec) = next(iter(tokens.items()))
    side = "buy" if post > pre else "sell"
    if side == "buy" and not (-sol >= MIN_LEADER_SOL or -stable >= 1.0):
        return None                              # tokens arrived, nothing paid: a transfer
    if side == "sell" and not (sol > 0 or stable > 0):
        return None                              # tokens left, nothing received: a transfer
    frac = 1.0 if side == "buy" or post == 0 or pre <= 0 else min(1.0, (pre - post) / pre)
    return {"side": side, "mint": mint, "decimals": dec, "units": abs(post - pre) / 10 ** dec,
            "sol": abs(sol), "stable_usd": abs(stable), "frac": frac,
            "block_time": tx.get("blockTime")}


def leader_usd(swap: dict, sol_price: float) -> float:
    return swap["sol"] * sol_price + swap["stable_usd"]


def buy_impact_pct(lamports: int, out: int, probe: int, probe_out: int) -> float:
    """Our own price impact: what our size gets per SOL against a tiny
    probe. Jupiter's priceImpactPct is not usable here: on Pump.fun AMM
    pools it read a flat 80% for 0.01 SOL and 0.4 SOL alike (22/10)."""
    if not (lamports and out and probe and probe_out):
        return 100.0
    return max(0.0, (1 - (out / lamports) / (probe_out / probe)) * 100)


def size_buy(follow: dict, limits: dict, swap_usd: float, spent: float, n_open: int,
             holding: bool) -> tuple[float | None, str]:
    """How many dollars to put in, or None and why not."""
    if holding and follow["sizing"] == "fixed":
        return None, "already holding: re-buys are not copied with a fixed amount"
    if not holding and n_open >= limits["max_open"]:
        return None, f"{limits['max_open']} positions already open"
    usd = swap_usd * follow["pct"] / 100 if follow["sizing"] == "pct" else follow["fixed_usd"]
    usd = min(usd, limits["max_trade_usd"])
    if usd < MIN_USD:
        return None, f"${usd:.2f} is under the ${MIN_USD:.0f} minimum"
    if spent + usd > limits["max_day_usd"] + 1e-9:
        return None, f"daily cap ${limits['max_day_usd']:.0f} reached"
    return usd, ""


# ── network ───────────────────────────────────────────────────────────────

def _helius() -> str:
    from app import service_keys
    try:
        return service_keys.get("helius") or ""
    except Exception:  # noqa: BLE001
        return ""


def _rpc_url() -> str:
    key = _helius()
    return f"https://mainnet.helius-rpc.com/?api-key={key}" if key else PUBLIC_RPC


async def rpc(method: str, params: list):
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(_rpc_url(), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        except httpx.HTTPError as exc:
            err = f"RPC unreachable ({type(exc).__name__})"     # never the URL: it holds the key
        else:
            if r.status_code == 200:
                d = r.json()
                if "error" in d:
                    raise RuntimeError(f"{method}: {str(d['error'])[:160]}")
                return d.get("result")
            err = f"RPC {r.status_code}"
        if attempt == 2:
            raise RuntimeError(err)
        await asyncio.sleep(0.4 * (attempt + 1))


async def get_tx(sig: str) -> dict | None:
    # Right after the "confirmed" log the node may not serve it yet.
    for wait in (0, 0.4, 0.8, 1.5):
        if wait:
            await asyncio.sleep(wait)
        tx = await rpc("getTransaction", [sig, {"encoding": "jsonParsed", "commitment": "confirmed",
                                               "maxSupportedTransactionVersion": 1}])
        if tx:
            return tx
    return None


async def quote(input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> dict:
    """Jupiter's free API answers 429 in bursts (seen 22/10): wait a moment
    and ask again rather than miss the copy."""
    for wait in (0.6, 1.2, None):
        try:
            return await quotes.jupiter_quote(input_mint, output_mint, amount, slippage_bps)
        except RuntimeError as exc:
            if wait is None or "429" not in str(exc):
                raise
            await asyncio.sleep(wait)


async def mint_risk(mint: str) -> str:
    """Why a token is unsafe to buy ('' when it is fine): a live freeze or
    mint authority lets its creator lock or dilute what we buy."""
    hit = _mint_cache.get(mint)
    if hit and time.time() - hit[0] < 600:
        info = hit[1]
    else:
        acc = await rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        info = (((acc or {}).get("value") or {}).get("data") or {}).get("parsed", {}).get("info", {})
        _mint_cache[mint] = (time.time(), info)
    if info.get("freezeAuthority"):
        return "freeze authority still active"
    if info.get("mintAuthority"):
        return "mint authority still active"
    return ""


async def token_balance_raw(owner: str, mint: str) -> int:
    res = await rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
    return sum(int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for a in (res or {}).get("value", []))


async def sol_balance(owner: str) -> float:
    res = await rpc("getBalance", [owner])
    return (res or {}).get("value", 0) / 1e9


async def sol_price() -> float | None:
    from app.trading.onchain import prices
    return await prices.native_price_usd("solana")


# ── copying ───────────────────────────────────────────────────────────────

def _lock(owner_id: str, mint: str) -> asyncio.Lock:
    return _locks.setdefault(f"{owner_id}:{mint}", asyncio.Lock())


async def handle_signature(leader: str, sig: str) -> None:
    """One transaction of a followed wallet, from the socket or the poll."""
    if sig in _handled:
        return
    _handled.add(sig)
    if len(_handled) > 20_000:
        _handled.clear()
        _handled.add(sig)
    owners = watched("solana").get(leader, [])
    if not owners:
        return
    try:
        tx = await get_tx(sig)
    except RuntimeError as exc:
        logger.warning("copytrade: %s unreadable: %s", sig, exc)
        return
    swap = parse_swap(tx, leader)
    if swap is None:
        return
    age = time.time() - (swap["block_time"] or time.time())
    status["last_event"] = time.time()
    price = await sol_price()
    if not price:
        logger.warning("copytrade: no SOL price, %s skipped", sig)
        return
    for owner in owners:
        acc = account(owner)
        f = acc["follows"].get(leader)
        if not f or f["mode"] == "off" or any(t.get("leader_sig") == sig for t in acc["trades"]):
            continue
        base = {"leader": leader, "label": f.get("label", ""), "leader_sig": sig, "side": swap["side"],
                "mint": swap["mint"], "leader_usd": round(leader_usd(swap, price), 2),
                "latency_s": round(age, 1), "mode": f["mode"]}
        if age > FRESH_S:
            _log(acc, {**base, "status": "skipped", "reason": f"seen {age:.0f}s late"})
            _save()
            continue
        try:
            async with _lock(owner, swap["mint"]):
                row = await (_copy_buy if swap["side"] == "buy" else _copy_sell)(owner, acc, f, swap, price, base)
        except Exception as exc:  # noqa: BLE001
            logger.exception("copytrade: %s for %s failed", sig, owner)
            row = {**base, "status": "failed", "reason": str(exc)[:200]}
        if row:
            row["latency_s"] = round(time.time() - (swap["block_time"] or time.time()), 1)
            _log(acc, row)
            _save()


def _wallet_of(owner_id: str) -> tuple[object, str] | None:
    from app import auth
    user = auth.get_user(owner_id)
    w = (user.onchain_wallets or {}).get("solana") if user else None
    return (user, w.address) if w else None


WALLET_OFF = "the Solana wallet is switched off: turn on \"Wallet active\" in On-chain wallet → Limits"


def wallet_enabled(owner_id: str) -> bool:
    from app.trading.onchain import risk
    return risk.check_wallet_enabled(owner_id, "solana")[0]


def _real_block(acc: dict, owner_id: str) -> str:
    """Why a real copy cannot go out now ('' when it can). The wallet switch
    is checked here too: execute_order refuses a switched-off wallet, and a
    new wallet starts off, so the first real copy failed with no hint of
    where the switch is (Trading tab check, 23/10)."""
    from app.config import settings
    if not settings.onchain_execution_enabled:
        return "real execution is switched off on the server"
    if not acc["real_ok_at"]:
        return "real money not confirmed for this account"
    if not wallet_enabled(owner_id):
        return WALLET_OFF
    return ""


async def _copy_buy(owner: str, acc: dict, f: dict, swap: dict, price: float, base: dict) -> dict:
    mint = swap["mint"]
    held = acc["positions"].get(f["address"], {}).get(mint)
    usd, why = size_buy(f, acc["limits"], base["leader_usd"], spent_today(acc), open_count(acc), held is not None)
    if usd is None:
        return {**base, "status": "skipped", "reason": why}
    risk = await mint_risk(mint)
    if risk:
        return {**base, "status": "skipped", "reason": risk, "usd": round(usd, 2)}
    lamports = int(usd / price * 1e9)
    probe = max(lamports // 100, 100_000)
    try:
        q, small = await asyncio.gather(quote(WSOL, mint, lamports, int(f["slippage_pct"] * 100)),
                                        quote(WSOL, mint, probe, int(f["slippage_pct"] * 100)))
    except RuntimeError as exc:
        return {**base, "status": "skipped", "reason": f"Jupiter can't trade it ({str(exc)[:80]})", "usd": round(usd, 2)}
    impact = buy_impact_pct(lamports, q["out_amount"], probe, small["out_amount"])
    q["price_impact_pct"] = impact
    units = q["out_amount"] / 10 ** swap["decimals"]
    our_price, his_price = usd / units, base["leader_usd"] / swap["units"]
    chase = (our_price / his_price - 1) * 100
    row = {**base, "usd": round(usd, 2), "qty": units, "price": our_price, "leader_price": his_price,
           "chase_pct": round(chase, 1), "impact_pct": round(impact, 2)}
    if chase > f["max_chase_pct"]:
        return {**row, "status": "skipped", "reason": f"price already {chase:.0f}% above his"}
    if impact > MAX_IMPACT_PCT:
        return {**row, "status": "skipped", "reason": f"price impact {impact:.1f}%"}
    try:
        back = await quote(mint, WSOL, q["out_amount"], 1000)
    except RuntimeError:
        back = None
    if not back or (1 - back["out_amount"] / lamports) * 100 > MAX_ROUNDTRIP_LOSS_PCT:
        return {**row, "status": "skipped", "reason": "no way to sell it back (possible honeypot)"}

    if f["mode"] == "real":
        block = _real_block(acc, owner)
        if block:
            return {**row, "status": "skipped", "reason": block}
        found = _wallet_of(owner)
        if not found:
            return {**row, "status": "skipped", "reason": "no Solana wallet on this account"}
        user, address = found
        if await sol_balance(address) < lamports / 1e9 + SOL_RESERVE:
            return {**row, "status": "skipped", "reason": "not enough SOL in the wallet"}
        res = await _execute(user, mint, "buy", usd, our_price, q, base)
        if not res.get("accepted"):
            return {**row, "status": "failed", "reason": res.get("reason", "not sent"), "tx": res.get("tx_signature")}
        row.update(status="submitted", tx=res.get("tx_signature"))
    else:
        row["status"] = "sim"
    pos = acc["positions"].setdefault(f["address"], {}).setdefault(
        mint, {"mint": mint, "decimals": swap["decimals"], "qty": 0.0, "cost_usd": 0.0,
               "opened_at": time.time(), "real": f["mode"] == "real"})
    pos["qty"] += units
    pos["cost_usd"] += usd
    _add_spent(acc, usd)
    return row


async def _execute(user, mint: str, side: str, usd: float, price_usd: float, q: dict, base: dict) -> dict:
    from app import auth
    from app.trading.onchain import execute
    key = auth.get_decrypted_onchain_private_key(user, "solana")
    q = {**q, "priority_max_lamports": PRIORITY_MAX_LAMPORTS}
    return await execute.execute_order(
        user.id, "solana", mint, "copytrade", side, usd, q["price_impact_pct"], price_usd, key, q,
        guards=False, intent_id=f"copy:{base['leader_sig'][:60]}:{side}")


async def _copy_sell(owner: str, acc: dict, f: dict, swap: dict, price: float, base: dict,
                     frac: float | None = None) -> dict | None:
    mint = swap["mint"]
    pos = acc["positions"].get(f["address"], {}).get(mint)
    if pos is None:
        return None                       # bought before we followed him, or never copied
    if f["copy"] != "both" and frac is None:
        return {**base, "status": "skipped", "reason": "exits are not copied (entry only)"}
    frac = swap["frac"] if frac is None else frac
    if frac >= 0.98:
        frac = 1.0
    qty = pos["qty"] * frac
    if pos.get("real"):
        found = _wallet_of(owner)
        if not found:
            return {**base, "status": "failed", "reason": "no Solana wallet on this account"}
        user, address = found
        raw = int(await token_balance_raw(address, mint) * frac)
    else:
        raw = int(qty * 10 ** pos["decimals"])
    if raw <= 0:
        _close(acc, f["address"], mint)
        return {**base, "status": "skipped", "reason": "nothing left to sell"}
    q = await quote(mint, WSOL, raw, int(f["slippage_pct"] * 100))
    usd = q["out_amount"] / 1e9 * price
    cost = pos["cost_usd"] * frac
    units = raw / 10 ** pos["decimals"]
    row = {**base, "usd": round(usd, 2), "qty": units, "price": usd / units if units else None,
           "frac": round(frac, 3), "pnl_usd": round(usd - cost, 2), "impact_pct": round(q["price_impact_pct"], 2)}
    if pos.get("real"):
        block = _real_block(acc, owner)
        if block:
            return {**row, "status": "skipped", "reason": block}
        res = await _execute(user, mint, "sell", usd, row["price"] or 0.0, q, base)
        if not res.get("accepted"):
            return {**row, "status": "failed", "reason": res.get("reason", "not sent"), "tx": res.get("tx_signature")}
        row.update(status="submitted", tx=res.get("tx_signature"))
    else:
        row["status"] = "sim"
    pos["qty"] -= qty
    pos["cost_usd"] -= cost
    if frac >= 1.0 or pos["qty"] <= 0:
        _close(acc, f["address"], mint)
    return row


def _close(acc: dict, leader: str, mint: str) -> None:
    acc["positions"].get(leader, {}).pop(mint, None)
    if not acc["positions"].get(leader):
        acc["positions"].pop(leader, None)


async def close_position(owner_id: str, leader: str, mint: str) -> dict:
    """Sell a copied position by hand (the only exit with "entry only")."""
    from app.trading.onchain import copytrade_evm
    if copytrade_evm.is_evm(leader):
        return await copytrade_evm.close_position(owner_id, copytrade_evm.norm(leader), mint)
    acc = account(owner_id)
    pos = acc["positions"].get(leader, {}).get(mint)
    if pos is None:
        raise ValueError("No such position.")
    f = acc["follows"].get(leader) or {**DEFAULT_FOLLOW, "address": leader, "copy": "both", "label": ""}
    price = await sol_price()
    if not price:
        raise ValueError("No SOL price right now, try again.")
    sig = f"manual-{uuid.uuid4().hex[:16]}"
    base = {"leader": leader, "label": f.get("label", ""), "leader_sig": sig, "side": "sell", "mint": mint,
            "leader_usd": None, "latency_s": None, "mode": "real" if pos.get("real") else "sim", "manual": True}
    async with _lock(owner_id, mint):
        row = await _copy_sell(owner_id, acc, f, {"mint": mint}, price, base, frac=1.0)
    row = _log(acc, row or {**base, "status": "skipped", "reason": "nothing to sell"})
    _save()
    return row


def stats(acc: dict) -> dict:
    done = [t for t in acc["trades"] if t.get("status") in ("sim", "submitted")]
    lat = sorted(t["latency_s"] for t in done if t.get("latency_s") is not None)
    return {"realized_usd": round(sum(t.get("pnl_usd") or 0 for t in done), 2),
            "copied": len(done),
            "skipped": sum(1 for t in acc["trades"] if t.get("status") == "skipped"),
            "median_latency_s": lat[len(lat) // 2] if lat else None}


# ── watcher ───────────────────────────────────────────────────────────────

async def _poll_once() -> None:
    for leader in list(watched("solana")):
        try:
            rows = await rpc("getSignaturesForAddress", [leader, {"limit": 15, "commitment": "confirmed"}])
        except RuntimeError as exc:
            status["error"] = str(exc)
            continue
        now = time.time()
        for r in reversed(rows or []):
            if r.get("err") is None and (r.get("blockTime") or 0) >= now - FRESH_S:
                await handle_signature(leader, r["signature"])


async def _poll_loop() -> None:
    while True:
        try:
            await _poll_once()
        except Exception:  # noqa: BLE001
            logger.exception("copytrade poll failed")
        await asyncio.sleep(POLL_S_HELIUS if _helius() else POLL_S_PUBLIC)


async def _ws_loop() -> None:
    import websockets
    while True:
        leaders = sorted(watched("solana"))
        status["addresses"] = len(leaders)
        if not leaders:
            status["ws"] = "idle"
            await asyncio.sleep(5)
            continue
        key = _helius()
        url = f"wss://mainnet.helius-rpc.com/?api-key={key}" if key else PUBLIC_WS
        status["source"] = "helius" if key else "public"
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
                subs: dict[int, str] = {}
                for i, leader in enumerate(leaders, 1):
                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": i, "method": "logsSubscribe",
                                              "params": [{"mentions": [leader]}, {"commitment": "confirmed"}]}))
                pending = {i: leader for i, leader in enumerate(leaders, 1)}
                status.update(ws="connected", error="")
                while True:
                    if sorted(watched("solana")) != leaders:
                        break                     # the list changed: subscribe again
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    if "id" in msg and msg.get("id") in pending:
                        if "result" in msg:
                            subs[msg["result"]] = pending.pop(msg["id"])
                        continue
                    params = msg.get("params") or {}
                    leader = subs.get(params.get("subscription"))
                    value = ((params.get("result") or {}).get("value")) or {}
                    if leader and value.get("signature") and value.get("err") is None:
                        asyncio.create_task(handle_signature(leader, value["signature"]))
        except Exception as exc:  # noqa: BLE001
            status.update(ws="reconnecting", error=f"{type(exc).__name__}")   # never the URL: it holds the key
            await asyncio.sleep(3)


async def loop() -> None:
    """Started by main's lifespan: the socket and the safety-net poll."""
    await asyncio.gather(_ws_loop(), _poll_loop())
