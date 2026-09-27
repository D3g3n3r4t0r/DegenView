"""The system, trading the Robinhood Chain wallet on its own.

Lorenzo: "voglio semplicemente che con un tasto io attivo la strategia e che
faccio operazioni sul wallet disponibile [...] ho depositato una cifra sul
wallet di Robinhood, quindi voglio che automaticamente la strategia faccia i
suoi ingressi, le sue uscite e che utilizzi sempre la totalita' del saldo
[...] uno seleziona il 100% del saldo, il 50, il 25 [...] devi considerare
sempre le fee, in modo tale che le operazioni vadano sempre in porto".
His answers when asked: the balance is USDG; one token at a time; no limit
other than the chosen share; simulated first.

- mode: "off", "sim" (every decision and a real quote, nothing sent, a
  virtual USDG balance) or "real";
- pct: the share of the USDG balance each entry spends (10/25/50/100);
- the signals are the system's (system.py) on the Meme Sniper's Robinhood
  alerts: a buy the system made within FRESH_S, while flat, opens the
  position; the system leaving that token (sell, 48h, rug) closes it.
  Turning the switch off stops new entries only: an open position is still
  closed by its exit, never left behind with no one watching it;
- sizing: pct of the USDG balance, one base unit less so rounding never
  asks for more than there is. The pool fee is inside the amount; gas is
  paid in ETH, so an entry is skipped (and says why) if the wallet has not
  enough ETH for approve + swap; min out is the live quote minus SLIPPAGE;
- real orders go through execute.execute_order (ledger, idempotency, the
  server's onchain_execution_enabled switch) with the risk guards off, as
  chosen; only Uniswap v3 routes can be signed today, so a token reachable
  only through an aggregator is skipped in real mode and says so.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.trading.onchain import alert_track
from app.trading.onchain.storage import data_file

logger = logging.getLogger(__name__)

_STORE_FILE = data_file("onchain_autotrader.json")
CHAIN = "robinhood"
USDG = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
USDG_DECIMALS = 6
MODES = ("off", "sim", "real")
PCTS = (10, 25, 50, 100)
FRESH_S = 15 * 60          # a buy older than this is not chased
SLIPPAGE = 0.05            # memes move: tight limits make orders fail
GAS_UNITS = 300_000 + 80_000   # swap + a possible approve
KEEP_TRADES = 60
SIM_START_USDG = 100.0     # virtual balance when the wallet holds no USDG

_state: dict[str, dict] = {}


def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        _state.update({k: v for k, v in raw.items() if isinstance(v, dict)})


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps(_state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def reset_for_tests() -> None:
    _state.clear()


def _user(uid: str) -> dict:
    return _state.setdefault(uid, {"mode": "off", "pct": 100, "position": None, "sim_usdg": None,
                                   "sim_start": None, "trades": [], "note": ""})


def settings(uid: str) -> dict:
    u = _user(uid)
    return {"mode": u["mode"], "pct": u["pct"]}


def configure(uid: str, mode: str | None = None, pct: int | None = None, usdg_now: float | None = None) -> dict:
    """Switch mode or share. Entering "sim" starts the virtual balance from
    the wallet's real USDG (or SIM_START_USDG if it has none)."""
    u = _user(uid)
    if pct is not None:
        if pct not in PCTS:
            raise ValueError(f"pct must be one of {PCTS}")
        u["pct"] = pct
    if mode is not None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if mode == "sim" and u["mode"] != "sim":
            start = usdg_now if usdg_now and usdg_now > 0 else SIM_START_USDG
            u.update(sim_usdg=round(start, 6), sim_start=round(start, 6))
            if u["position"] and u["position"].get("mode") == "sim":
                u["position"] = None
        u["mode"] = mode
        u["note"] = ""
    _save()
    return view(uid)


def _price(alert: dict | None) -> float | None:
    last = (alert or {}).get("last") or {}
    return last.get("price") or (alert or {}).get("entry")


def view(uid: str) -> dict:
    u = _user(uid)
    pos = u["position"]
    pos_view = None
    if pos:
        a = alert_track._alerts.get(pos["alert"])
        price = _price(a)
        qty = pos["qty_raw"] / 10 ** pos["decimals"]
        value = qty * price if price else None
        pos_view = {**{k: pos[k] for k in ("symbol", "token", "pair", "at", "cost_usdg", "mode", "route")},
                    "value_usdg": round(value, 4) if value is not None else None,
                    "ret": round(value / pos["cost_usdg"] - 1, 4) if value and pos["cost_usdg"] else None,
                    "image": (a or {}).get("image")}
    sim = None
    if u["sim_start"]:
        equity = (u["sim_usdg"] or 0) + ((pos_view or {}).get("value_usdg") or 0 if pos and pos["mode"] == "sim" else 0)
        sim = {"usdg": u["sim_usdg"], "start": u["sim_start"], "equity": round(equity, 4),
               "ret": round(equity / u["sim_start"] - 1, 4) if u["sim_start"] else None}
    closed = [t for t in u["trades"] if t.get("side") == "sell" and t.get("ok") and t.get("ret") is not None]
    return {"mode": u["mode"], "pct": u["pct"], "pcts": list(PCTS), "chain": CHAIN, "position": pos_view,
            "sim": sim, "trades": u["trades"][-20:][::-1], "note": u["note"],
            "stats": {"closed": len(closed), "wins": sum(1 for t in closed if t["ret"] > 0),
                      "sum_ret": round(sum(t["ret"] for t in closed), 4) if closed else None},
            "system": alert_track.system_board("meme")["chosen"]}


# --------------------------------------------------------------- decisions

def _system_of(a: dict, label: str) -> dict | None:
    return (a.get("system") or {}).get(label)


def entry_candidate(label: str, now: float) -> dict | None:
    """The freshest Robinhood alert where the system just bought."""
    best = None
    for a in alert_track._alerts.values():
        if a["kind"] != "meme" or a["chain"] != CHAIN or a.get("gone"):
            continue
        s = _system_of(a, label)
        if not s or s.get("state") != "in" or not s.get("in_at"):
            continue
        if now - s["in_at"] > FRESH_S:
            continue
        if best is None or s["in_at"] > best[1]:
            best = (a, s["in_at"])
    return best[0] if best else None


def should_exit(pos: dict, label: str) -> str | None:
    a = alert_track._alerts.get(pos["alert"])
    if a is None:
        return "alert no longer tracked"
    if a.get("gone"):
        return "pool gone"
    s = _system_of(a, label)
    if not s:
        return None
    if s.get("state") != "in":
        last = (s.get("events") or [{}])[-1]
        return {"sell": "system sold", "rug": "pool gone"}.get(last.get("side"), "system out") \
            if last.get("why") != "48h" else "48h window over"
    return None


def buy_amount(balance_raw: int, pct: int) -> int:
    """pct of the balance, one base unit less: never more than there is."""
    return max(0, balance_raw * pct // 100 - 1)


# ----------------------------------------------------------------- market

@dataclass
class Market:
    """What the autotrader needs from the chain; the defaults are real, tests
    pass fakes."""
    usdg_balance: Callable[[str], Awaitable[int]]
    token_balance: Callable[[str, str], Awaitable[int]]
    eth_balance_wei: Callable[[str], Awaitable[int]]
    gas_price_wei: Callable[[], Awaitable[int]]
    decimals: Callable[[str], Awaitable[int | None]]
    quote: Callable[[str, str, int], Awaitable[dict]]
    swap: Callable[..., Awaitable[dict]]


async def _default_market() -> Market:
    from app.trading.onchain import aggregator, balances, execution, quotes, token_metadata

    async def token_balance(owner: str, token: str) -> int:
        rows = await balances._robinhood_known_token_balances(owner, [token])
        return rows[0]["amount_raw"] if rows else 0

    async def usdg_balance(owner: str) -> int:
        return await token_balance(owner, USDG)

    async def eth_balance_wei(owner: str) -> int:
        return int(await execution._robinhood_rpc("eth_getBalance", [owner, "latest"]), 16)

    async def gas_price_wei() -> int:
        return int(await execution._robinhood_rpc("eth_gasPrice", []), 16)

    async def decimals(token: str) -> int | None:
        return await token_metadata.get_token_decimals(CHAIN, token)

    async def quote(token_in: str, token_out: str, amount_in: int) -> dict:
        try:
            found = await quotes.find_pool_and_fee(token_in, token_out)
        except Exception:
            found = None
        if found is not None:
            _pool, fee = found
            q = await quotes.uniswap_v3_quote(token_in, token_out, fee, amount_in)
            return {"out": int(q["amount_out"]), "route": "uniswap-v3", "fee": fee,
                    "impact": float(q.get("price_impact_pct") or 0)}
        q = await aggregator.quote(token_in, token_out, amount_in)
        return {"out": int(q["amount_out"]), "route": "aggregator", "fee": None,
                "impact": float(q.get("price_impact_pct") or 0)}

    return Market(usdg_balance, token_balance, eth_balance_wei, gas_price_wei, decimals, quote, real_swap)


async def _ensure_allowance(private_key_hex: str, owner: str, token: str, amount: int) -> str | None:
    """ERC-20 approve of SwapRouter02 when the allowance is short. Returns
    the approve tx hash, or None when none was needed. The swap that follows
    has the next nonce, so it can only land after it."""
    from eth_utils import to_checksum_address

    from app.trading.onchain import execution
    router = execution.ROBINHOOD_SWAP_ROUTER02
    data = "0xdd62ed3e" + owner[2:].lower().zfill(64) + router[2:].lower().zfill(64)
    allowance = int(await execution._robinhood_rpc("eth_call", [{"to": token, "data": data}, "latest"]), 16)
    if allowance >= amount:
        return None
    nonce = int(await execution._robinhood_rpc("eth_getTransactionCount", [owner, "pending"]), 16)
    gas_price = int(await execution._robinhood_rpc("eth_gasPrice", []), 16) * 12 // 10
    calldata = "0x095ea7b3" + router[2:].lower().zfill(64) + "f" * 64      # approve(router, max)
    tx = {"nonce": nonce, "to": to_checksum_address(token), "value": 0, "gas": 80_000, "gasPrice": gas_price,
          "chainId": 4663, "data": calldata}
    return await execution.send_signed_evm_tx(execution.sign_evm_transaction(private_key_hex, tx))


async def real_swap(*, user, token_in: str, token_out: str, amount_in: int, min_out: int, fee: int,
                    notional_usd: float, impact: float, price_usd: float, side: str, token: str) -> dict:
    from app import auth
    from app.config import settings as app_settings
    from app.trading.onchain import execute
    if not app_settings.onchain_execution_enabled:
        return {"ok": False, "reason": "real execution is switched off on this server"}
    owner = user.onchain_wallets[CHAIN].address
    private_key_hex = auth.get_decrypted_onchain_private_key(user, CHAIN)
    try:
        approve_tx = await _ensure_allowance(private_key_hex, owner, token_in, amount_in)
    except Exception as exc:
        return {"ok": False, "reason": f"approve failed: {exc}"}
    result = await execute.execute_order(
        user.id, CHAIN, token, "System", side, notional_usd, impact, price_usd, private_key_hex,
        {"token_in": token_in, "token_out": token_out, "fee": fee, "amount_in": amount_in,
         "amount_out_minimum": min_out},
        guards=False,
    )
    return {"ok": bool(result.get("accepted")), "reason": result.get("reason") or "",
            "tx": result.get("tx_signature"), "approve_tx": approve_tx}


# ------------------------------------------------------------------- tick

def _log(u: dict, row: dict) -> dict:
    last = u["trades"][-1] if u["trades"] else None
    if not row.get("ok") and last and not last.get("ok") and last.get("reason") == row.get("reason") \
            and last.get("symbol") == row.get("symbol") and last.get("side") == row.get("side"):
        last["t"] = row["t"]           # the same failure again: one row, not one a minute
        return last
    u["trades"].append(row)
    del u["trades"][:-KEEP_TRADES]
    return row


async def tick(users: list, now: float | None = None, market: Market | None = None,
               notify: Callable[[object, str], Awaitable[None]] | None = None) -> list[dict]:
    """One pass for every user whose switch is not off (or who still holds
    a position): exit first, then at most one entry."""
    now = now or time.time()
    label = alert_track.system_board("meme")["chosen"]
    done: list[dict] = []
    for user in users:
        u = _state.get(user.id)
        if not u or (u["mode"] == "off" and not u["position"]):
            continue
        wallet = (getattr(user, "onchain_wallets", {}) or {}).get(CHAIN)
        if wallet is None:
            u["note"] = "no Robinhood Chain wallet"
            continue
        market = market or await _default_market()
        try:
            if u["position"]:
                why = should_exit(u["position"], label)
                if why:
                    row = await _sell(user, u, why, now, market)
                    done.append(row)
                    if notify and row.get("ok"):
                        await notify(user, row)
            if not u["position"] and u["mode"] in ("sim", "real"):
                a = entry_candidate(label, now)
                if a and not any(t.get("alert") == alert_track.key_of(a) for t in u["trades"]):
                    row = await _buy(user, u, a, now, market)
                    done.append(row)
                    if notify and row.get("ok"):
                        await notify(user, row)
        except Exception as exc:
            logger.exception("autotrader %s", user.id)
            u["note"] = f"error: {exc}"[:200]
    if done:
        _save()
    return done


async def _buy(user, u: dict, a: dict, now: float, market: Market) -> dict:
    owner = user.onchain_wallets[CHAIN].address
    mode = u["mode"]
    base = {"t": now, "side": "buy", "symbol": a["symbol"], "token": a["token_address"], "alert": alert_track.key_of(a),
            "mode": mode, "ok": False}
    if mode == "sim":
        balance_raw = int((u["sim_usdg"] or 0) * 10 ** USDG_DECIMALS)
    else:
        balance_raw = await market.usdg_balance(owner)
        wei = await market.eth_balance_wei(owner)
        need = GAS_UNITS * await market.gas_price_wei() * 12 // 10
        if wei < need:
            return _log(u, {**base, "reason": f"not enough ETH for gas (need ~{need / 1e18:.6f} ETH)"})
    amount = buy_amount(balance_raw, u["pct"])
    if amount <= 0:
        return _log(u, {**base, "reason": "no USDG to spend"})
    decimals = await market.decimals(a["token_address"])
    if decimals is None:
        return _log(u, {**base, "reason": "token decimals unavailable"})
    q = await market.quote(USDG, a["token_address"], amount)
    usdg = amount / 10 ** USDG_DECIMALS
    base.update(usdg=round(usdg, 6), route=q["route"], impact=q["impact"])
    if q["out"] <= 0:
        return _log(u, {**base, "reason": "no market for this token"})
    if mode == "real":
        if q["route"] != "uniswap-v3":
            return _log(u, {**base, "reason": "only reachable through an aggregator: not signable yet"})
        res = await market.swap(user=user, token_in=USDG, token_out=a["token_address"], amount_in=amount,
                                min_out=int(q["out"] * (1 - SLIPPAGE)), fee=q["fee"], notional_usd=usdg,
                                impact=q["impact"], price_usd=_price(a) or 0.0, side="buy", token=a["token_address"])
        if not res["ok"]:
            return _log(u, {**base, "reason": res["reason"]})
        base["tx"] = res.get("tx")
        qty_raw = await market.token_balance(owner, a["token_address"]) or q["out"]
    else:
        u["sim_usdg"] = round((u["sim_usdg"] or 0) - usdg, 6)
        qty_raw = q["out"]
    u["position"] = {"alert": base["alert"], "symbol": a["symbol"], "token": a["token_address"],
                     "pair": a["pair_address"], "qty_raw": int(qty_raw), "decimals": decimals,
                     "cost_usdg": round(usdg, 6), "at": now, "mode": mode, "route": q["route"]}
    return _log(u, {**base, "ok": True, "qty": qty_raw / 10 ** decimals})


async def _sell(user, u: dict, why: str, now: float, market: Market) -> dict:
    pos = u["position"]
    owner = user.onchain_wallets[CHAIN].address
    base = {"t": now, "side": "sell", "symbol": pos["symbol"], "token": pos["token"], "alert": pos["alert"],
            "mode": pos["mode"], "why": why, "ok": False}
    qty_raw = pos["qty_raw"] if pos["mode"] == "sim" else await market.token_balance(owner, pos["token"])
    if qty_raw <= 0:
        u["position"] = None
        return _log(u, {**base, "reason": "nothing left to sell"})
    try:
        q = await market.quote(pos["token"], USDG, qty_raw)
    except Exception as exc:
        q = {"out": 0, "route": None, "impact": None}
        base["reason"] = f"no quote: {exc}"[:160]
    usdg = q["out"] / 10 ** USDG_DECIMALS
    base.update(route=q["route"], impact=q["impact"])
    if pos["mode"] == "real":
        if q["out"] <= 0 or q["route"] != "uniswap-v3":
            return _log(u, {**base, "reason": base.get("reason") or "no signable route to sell right now"})
        res = await market.swap(user=user, token_in=pos["token"], token_out=USDG, amount_in=qty_raw,
                                min_out=int(q["out"] * (1 - SLIPPAGE)), fee=q["fee"], notional_usd=usdg,
                                impact=q["impact"], price_usd=_price(alert_track._alerts.get(pos["alert"])) or 0.0,
                                side="sell", token=pos["token"])
        if not res["ok"]:
            return _log(u, {**base, "reason": res["reason"]})
        base["tx"] = res.get("tx")
    else:
        u["sim_usdg"] = round((u["sim_usdg"] or 0) + usdg, 6)
    u["position"] = None
    ret = usdg / pos["cost_usdg"] - 1 if pos["cost_usdg"] else None
    return _log(u, {**base, "ok": True, "usdg": round(usdg, 6), "ret": round(ret, 4) if ret is not None else None})


_load()
