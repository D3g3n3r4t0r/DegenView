"""What the contracts holding a token are, and when their tokens unlock.

Lorenzo, 30/09: "pool e vesting devi anche trovare lo sblocco che tempi ha".
GoPlus marks a holder `is_contract` and rarely tags it, so "33% held by
contracts" said nothing. On HYDX (Robinhood) the contracts were:

- EIP-7702 accounts (code 0xef0100 + delegate): wallets with a smart
  account attached, not contracts - they count as wallets;
- a launchpad locker holding 8% of the supply and the LP position
  (`isLocked(token)` true, `lockedPositions(token)` an NFT id).

For each contract holder this reads, over plain RPC, the views the common
vesting and lock contracts expose (OpenZeppelin VestingWallet start/
duration, TokenTimelock releaseTime, unlockTime/lockedUntil/endTime/cliff,
a locker's isLocked(token)) and whether the bytecode carries a function
that can release tokens (release/withdraw/unlock/claim). A contract with
none of these stays "unknown": no date is invented.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx
from eth_utils import keccak

from app.trading.onchain import rpc_client

logger = logging.getLogger(__name__)

RPC = {"base": "https://mainnet.base.org", "ethereum": "https://ethereum-rpc.publicnode.com",
       "bsc": "https://bsc-dataseed.bnbchain.org"}
MAX_PROBED = 6
SOON_DAYS = 30
TS_MIN, TS_MAX = 1_400_000_000, 4_200_000_000     # a plausible unix time


def _sel(sig: str) -> str:
    return keccak(text=sig)[:4].hex()


TIME_VIEWS = ("releaseTime()", "unlockTime()", "unlockDate()", "lockedUntil()", "lockEnd()",
              "endTime()", "vestingEnd()", "end()", "cliff()")
RELEASE = ("release()", "release(address)", "withdraw()", "withdraw(uint256)", "withdraw(address)",
           "withdraw(address,uint256)", "unlock()", "unlock(uint256)", "unlock(address)", "claim()",
           "claim(address)", "emergencyWithdraw()", "withdrawTokens(address,uint256)")
_RELEASE_SEL = {_sel(s) for s in RELEASE}


async def _rpc(chain: str, method: str, params: list, client: httpx.AsyncClient):
    if chain == "robinhood":
        return await rpc_client.call_rpc("robinhood", method, params, timeout=10.0)
    url = RPC.get(chain)
    if not url:
        return None
    r = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=10.0)
    return (r.json() or {}).get("result")


async def _call(chain: str, to: str, sig: str, client: httpx.AsyncClient, arg: str = "") -> int | None:
    data = "0x" + _sel(sig) + (arg.lower().removeprefix("0x").rjust(64, "0") if arg else "")
    try:
        out = await _rpc(chain, "eth_call", [{"to": to, "data": data}, "latest"], client)
    except Exception:
        return None
    if not out or out == "0x" or len(out) < 66:
        return None
    try:
        return int(out[2:66], 16)
    except ValueError:
        return None


def _ts(v: int | None) -> int | None:
    return v if v is not None and TS_MIN <= v <= TS_MAX else None


async def probe(chain: str, token: str, address: str, client: httpx.AsyncClient) -> dict:
    """{kind, unlock_at?, start?, end?, can_release?, note}. kind: wallet
    (EIP-7702), vesting, timelock, locker, contract (nothing readable)."""
    try:
        code = await _rpc(chain, "eth_getCode", [address, "latest"], client) or "0x"
    except Exception:
        return {"kind": "unknown", "note": "code not readable"}
    code = code.lower()
    if code in ("0x", ""):
        return {"kind": "wallet", "note": "no code"}
    if code.startswith("0xef0100"):
        return {"kind": "wallet", "note": "wallet with a smart account (EIP-7702)"}
    can_release = any(f"63{s}" in code for s in _RELEASE_SEL)
    start, duration = await _call(chain, address, "start()", client), await _call(chain, address, "duration()", client)
    if _ts(start) and duration and 0 < duration < 20 * 365 * 86400:
        return {"kind": "vesting", "start": start, "end": start + duration, "can_release": True,
                "note": f"linear vesting to {time.strftime('%Y-%m-%d', time.gmtime(start + duration))}"}
    for sig in TIME_VIEWS:
        at = _ts(await _call(chain, address, sig, client))
        if at:
            return {"kind": "timelock", "unlock_at": at, "can_release": can_release,
                    "note": f"unlocks {time.strftime('%Y-%m-%d', time.gmtime(at))} ({sig[:-2]})"}
    if await _call(chain, address, "isLocked(address)", client, token) == 1:
        pos = await _call(chain, address, "lockedPositions(address)", client, token)
        return {"kind": "locker", "can_release": can_release,
                "note": "locker: token locked" + (" with its LP position" if pos else "")
                        + ("" if can_release else ", no release function found")}
    return {"kind": "contract", "can_release": can_release,
            "note": "contract, no unlock schedule readable" + (", can release tokens" if can_release else "")}


async def annotate(chain: str, token: str, info: dict, client: httpx.AsyncClient,
                   skip: set[str] | None = None) -> list[dict]:
    """Probe the biggest contract holders and write what they are into
    GoPlus's holder rows: EIP-7702 wallets lose `is_contract`, lockers and
    vesting get a tag (tagged locks leave the concentration limits). Returns
    [{pct, kind, note, unlock_at?}] for the facts."""
    skip = {s.lower() for s in (skip or set())}
    rows = [h for h in info.get("holders") or []
            if str(h.get("is_contract")) == "1" and (h.get("address") or "").lower() not in skip]
    rows = sorted(rows, key=lambda h: -float(h.get("percent") or 0))[:MAX_PROBED]
    found = await asyncio.gather(*(probe(chain, token, h["address"], client) for h in rows), return_exceptions=True)
    out = []
    for h, f in zip(rows, found):
        if isinstance(f, BaseException):
            continue
        if f["kind"] == "wallet":
            h["is_contract"] = 0
        elif f["kind"] in ("locker", "timelock", "vesting") and not h.get("tag"):
            h["tag"] = f"{f['kind']} lock"
        out.append({"pct": round(float(h.get("percent") or 0) * 100, 2), **{k: v for k, v in f.items()
                                                                            if k != "can_release"}})
    return out


def soon(unlocks: list[dict], now: float | None = None) -> list[str]:
    """Flags for a sizeable unlock within SOON_DAYS."""
    now = now or time.time()
    out = []
    for u in unlocks:
        at = u.get("unlock_at") or u.get("end")
        if at and now <= at <= now + SOON_DAYS * 86400 and u.get("pct", 0) >= 3:
            out.append(f"{u['pct']:.0f}% unlocks on {time.strftime('%Y-%m-%d', time.gmtime(at))}")
    return out
