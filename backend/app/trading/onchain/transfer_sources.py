"""Every Transfer of a token from a free explorer API (etherscan-compatible).

The free RPCs of Ethereum, Base and BSC answer eth_getLogs only for the
last hours (22/10: publicnode "archive requests require a token", drpc
"free plan"), so wallet_clusters reads the history from explorers:
Blockscout (Ethereum, Base) and Routescan (Ethereum, Base, BSC), no key,
one after the other when one refuses. Rate limits are tight: one call at a
time, a pause between calls, a capped number of pages; past the cap the
result says it is partial.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import time

import httpx

logger = logging.getLogger(__name__)

_RS = "https://api.routescan.io/v2/network/mainnet/evm/{}/etherscan/api"
SOURCES = {
    "ethereum": ["https://eth.blockscout.com/api", _RS.format(1)],
    "base": ["https://base.blockscout.com/api"],
    "arbitrum": ["https://arbitrum.blockscout.com/api"],
    "optimism": ["https://optimism.blockscout.com/api"],
    "polygon": ["https://polygon.blockscout.com/api"],
    "avalanche": [_RS.format(43114)],
    "mantle": [_RS.format(5000)],
    "metis": ["https://andromeda-explorer.metis.io/api", _RS.format(1088)],
    "zksync": ["https://zksync.blockscout.com/api"],
    "scroll": ["https://scroll.blockscout.com/api"],
    "blast": [_RS.format(81457)],
    "mode": ["https://explorer.mode.network/api"],
    "celo": ["https://celo.blockscout.com/api"],
    "gnosis": ["https://gnosis.blockscout.com/api"],
    "manta": ["https://pacific-explorer.manta.network/api"],
    # No BSC: Routescan answers "chain not supported" for 56 (22/10); BSC
    # reads its history from the NodeReal archive RPC (wallet_clusters.KEYED_RPC).
}
_RPC_FALLBACK_ENDPOINTS: dict[str, list[str]] = {
    "taiko": ["https://rpc.mainnet.taiko.xyz"],
    "linea": ["https://rpc.linea.build", "https://linea-rpc.publicnode.com"],
    "fantom": ["https://fantom-rpc.publicnode.com", "https://rpc.ftm.tools"],
}
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
_DEAD_ZERO = "0x0000000000000000000000000000000000000000"
PAGE = 1000            # Fast page size to avoid ReadTimeouts on Blockscout/Routescan
MAX_PAGES = 5          # Cap sequential v1 pages
PAUSE_S = 0.05         # Minimal inter-page pause to avoid stalling multi-page scans
HTTP_TIMEOUT_S = 8.0   # Fail fast on dead/rate-limited explorer endpoints
RETRY_DELAY_S = 0.25
_UA = {"user-agent": "Mozilla/5.0 (compatible; liquidityengine/1.0)", "accept": "application/json"}


def _row(r: dict, i: int) -> dict | None:
    try:
        return {"block": int(r["blockNumber"]), "ts": int(r["timeStamp"]), "tx": r.get("hash"),
                "log_index": int(r.get("logIndex") or r.get("transactionIndex") or 0) * 10_000 + i,
                "from": (r.get("from") or "").lower(), "to": (r.get("to") or "").lower(), "amount": int(r["value"])}
    except (KeyError, TypeError, ValueError):
        return None


def _parse_iso_ts(val: object) -> int | None:
    if isinstance(val, (int, float)):
        return int(val / 1000) if val > 1e12 else int(val)
    if isinstance(val, str) and val:
        try:
            return int(datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return None


def _parse_v2_transfer(it: dict, idx: int) -> dict | None:
    if not isinstance(it, dict):
        return None
    frm = ((it.get("from") or {}).get("hash") or "").lower() if isinstance(it.get("from"), dict) else ""
    to = ((it.get("to") or {}).get("hash") or "").lower() if isinstance(it.get("to"), dict) else ""
    tot = it.get("total")
    raw_val = tot.get("value") if isinstance(tot, dict) else it.get("value")
    try:
        val = int(str(raw_val or 0).split(".")[0] or 0)
        blk = int(it.get("block_number") or (idx + 1))
        log_idx = int(it.get("log_index") if it.get("log_index") is not None else idx)
    except (TypeError, ValueError):
        return None
    if not frm or not to or val <= 0:
        return None
    return {
        "block": blk,
        "ts": _parse_iso_ts(it.get("timestamp")),
        "tx": str(it.get("tx_hash") or it.get("transaction_hash") or it.get("hash") or f"bs-{idx}"),
        "log_index": log_idx,
        "from": frm,
        "to": to,
        "amount": val,
    }


async def _blockscout_v2_transfers(
    client: httpx.AsyncClient,
    origin: str,
    token: str,
) -> list[dict] | None:
    """Fast Blockscout REST v2 path: fetches `/api/v2/tokens/{token}/transfers`
    and `/holders` concurrently and prepends synthetic opening balances so
    `wallet_clusters.balances` reconstructs exact top holder shares."""
    t0 = time.perf_counter()
    try:
        r_tr, r_hd = await asyncio.gather(
            client.get(f"{origin}/api/v2/tokens/{token}/transfers", timeout=6.0, follow_redirects=True),
            client.get(f"{origin}/api/v2/tokens/{token}/holders", timeout=2.5, follow_redirects=True),
            return_exceptions=True,
        )
    except Exception:  # noqa: BLE001
        return None

    if isinstance(r_tr, Exception) or getattr(r_tr, "status_code", 0) in (429, 502, 503, 504):
        try:
            await asyncio.sleep(0.4)
            r_tr = await client.get(f"{origin}/api/v2/tokens/{token}/transfers", timeout=6.0, follow_redirects=True)
        except Exception:  # noqa: BLE001
            r_tr = None

    out: list[dict] = []
    seen: set[tuple[str, str, str, int]] = set()
    next_params: dict | None = None

    if r_tr is not None and not isinstance(r_tr, Exception) and getattr(r_tr, "status_code", 0) == 200:
        try:
            d_tr = r_tr.json()
        except ValueError:
            d_tr = None
        if isinstance(d_tr, dict) and isinstance(d_tr.get("items"), list):
            for idx, it in enumerate(d_tr["items"]):
                tr = _parse_v2_transfer(it, idx)
                if tr is not None:
                    k = (tr["tx"], tr["from"], tr["to"], tr["amount"])
                    if k not in seen:
                        seen.add(k)
                        out.append(tr)
            np = d_tr.get("next_page_params")
            if isinstance(np, dict) and np:
                next_params = np

    # Optionally fetch 1 more page if page 1 was fast (< 1.2s)
    if next_params and (time.perf_counter() - t0) < 1.2:
        try:
            r_tr2 = await client.get(
                f"{origin}/api/v2/tokens/{token}/transfers",
                params=next_params,
                timeout=2.5,
                follow_redirects=True,
            )
            if r_tr2.status_code == 200:
                d_tr2 = r_tr2.json()
                if isinstance(d_tr2, dict) and isinstance(d_tr2.get("items"), list):
                    base_idx = len(out)
                    for idx, it in enumerate(d_tr2["items"]):
                        tr = _parse_v2_transfer(it, base_idx + idx)
                        if tr is not None:
                            k = (tr["tx"], tr["from"], tr["to"], tr["amount"])
                            if k not in seen:
                                seen.add(k)
                                out.append(tr)
        except Exception:  # noqa: BLE001
            pass

    holders: list[tuple[str, int]] = []
    if not isinstance(r_hd, Exception) and getattr(r_hd, "status_code", 0) == 200:
        try:
            d_hd = r_hd.json()
        except ValueError:
            d_hd = None
        if isinstance(d_hd, dict) and isinstance(d_hd.get("items"), list):
            for it in d_hd["items"]:
                if not isinstance(it, dict):
                    continue
                addr = ((it.get("address") or {}).get("hash") or "").lower() if isinstance(it.get("address"), dict) else ""
                try:
                    val = int(str(it.get("value") or 0).split(".")[0] or 0)
                except (TypeError, ValueError):
                    val = 0
                if addr and addr != _DEAD_ZERO and val > 0:
                    holders.append((addr, val))

    if not out and not holders:
        return None

    out.sort(key=lambda t: (t["block"], t["log_index"]))
    if holders:
        net_bal: dict[str, int] = {}
        for t in out:
            net_bal[t["from"]] = net_bal.get(t["from"], 0) - t["amount"]
            net_bal[t["to"]] = net_bal.get(t["to"], 0) + t["amount"]
        first_block = out[0]["block"] if out else 2
        open_block = max(1, first_block - 1)
        first_ts = out[0].get("ts") if out else int(time.time())
        opening: list[dict] = []
        for idx, (addr, val) in enumerate(holders):
            diff = val - net_bal.get(addr, 0)
            if diff > 0:
                opening.append({
                    "block": open_block,
                    "ts": first_ts,
                    "tx": f"open-{idx}",
                    "log_index": idx,
                    "from": _DEAD_ZERO,
                    "to": addr,
                    "amount": diff,
                })
        if opening:
            out = opening + out

    out.sort(key=lambda t: (t["block"], t["log_index"]))
    return out


async def _rpc_logs_fallback(chain: str, token: str) -> tuple[list[dict], bool, str] | None:
    """Fallback for chains whose free explorers are offline (`taiko`, `linea`,
    `fantom`): reads ERC-20 Transfer logs over the last 2,000 blocks via
    `rpc_client.call_rpc`."""
    from app.trading.onchain import rpc_client

    if chain in _RPC_FALLBACK_ENDPOINTS:
        rpc_client._ENDPOINTS.setdefault(chain, list(_RPC_FALLBACK_ENDPOINTS[chain]))
    if chain not in rpc_client._ENDPOINTS:
        return None
    try:
        latest_hex = await rpc_client.call_rpc(chain, "eth_blockNumber", [], timeout=6.0)
        latest = int(str(latest_hex), 16)
        start = max(0, latest - 2000)
        logs = await rpc_client.call_rpc(
            chain,
            "eth_getLogs",
            [{
                "address": token,
                "fromBlock": hex(start),
                "toBlock": hex(latest),
                "topics": [_TRANSFER_TOPIC],
            }],
            timeout=8.0,
        )
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(logs, list):
        return None
    now_ts = int(time.time())
    out: list[dict] = []
    for idx, lg in enumerate(logs):
        if not isinstance(lg, dict):
            continue
        topics = lg.get("topics") or []
        if len(topics) < 3:
            continue
        try:
            blk = int(str(lg.get("blockNumber") or "0x0"), 16)
            log_idx = int(str(lg.get("logIndex") or hex(idx)), 16)
            amt = int(str(lg.get("data") or "0x0"), 16)
            frm = "0x" + str(topics[1])[-40:].lower()
            to = "0x" + str(topics[2])[-40:].lower()
        except (TypeError, ValueError):
            continue
        if frm and to and amt > 0:
            out.append({
                "block": blk,
                "ts": now_ts,
                "tx": str(lg.get("transactionHash") or f"rpc-{idx}"),
                "log_index": log_idx,
                "from": frm,
                "to": to,
                "amount": amt,
            })
    if not out:
        return None
    out.sort(key=lambda t: (t["block"], t["log_index"]))
    return out, True, f"{chain}-rpc"


async def _get(client: httpx.AsyncClient, base: str, params: dict) -> list[dict] | None:
    """One page; None when the source refuses (the caller tries the next)."""
    for i in range(2):
        try:
            r = await client.get(base, params=params, follow_redirects=True)
        except Exception:  # noqa: BLE001
            r = None
        if r is not None and r.status_code == 200:
            try:
                d = r.json()
            except ValueError:
                return None
            res = d.get("result")
            if isinstance(res, list):
                return res
            msg = str(d.get("message", "")).lower()
            if "no transactions" in msg:
                return []
            body_l = str(d).lower()
            if "rate" not in body_l and "too many" not in body_l:
                return None
        elif r is not None and r.status_code not in (429, 502, 503, 504):
            return None
        if i == 0:
            await asyncio.sleep(RETRY_DELAY_S)
    return None


async def _get_ranges(
    client: httpx.AsyncClient,
    base: str,
    token: str,
    ranges: list[tuple[int, int]],
) -> list[list[dict] | None]:
    """Fetch multiple (startblock, endblock) transfer windows concurrently."""
    return await asyncio.gather(*(
        _get(client, base, {
            "module": "account",
            "action": "tokentx",
            "contractaddress": token,
            "startblock": lo,
            "endblock": hi,
            "page": 1,
            "offset": PAGE,
            "sort": "asc",
        })
        for lo, hi in ranges
    ))


async def transfers(chain: str, token: str, client: httpx.AsyncClient | None = None) -> tuple[list[dict], bool, str]:
    """(transfers in order, partial, source). Raises when no source answers."""
    from app.trading.onchain import wallet_clusters

    own = client is None
    client = client or httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, headers=_UA, follow_redirects=True)
    try:
        for base in SOURCES.get(chain, []):
            if base.endswith("/api") and "routescan.io" not in base:
                origin = base[:-4]
                v2_out = await _blockscout_v2_transfers(client, origin, token)
                if v2_out:
                    wallet_clusters.progress("transfers", 1.0)
                    return v2_out, True, origin.split("/")[2]

            out, seen, start, partial, ok = [], set(), 0, False, True
            for page in range(MAX_PAGES):
                rows = await _get(client, base, {"module": "account", "action": "tokentx", "contractaddress": token,
                                                 "startblock": start, "page": 1, "offset": PAGE, "sort": "asc"})
                if rows is None:
                    if out:
                        partial = True
                        break
                    ok = False
                    break
                for i, r in enumerate(rows):
                    t = _row(r, i)
                    k = t and (t["tx"], t["from"], t["to"], t["amount"])
                    if t and k not in seen:
                        seen.add(k)
                        out.append(t)
                wallet_clusters.progress("transfers", (page + 1) / MAX_PAGES if len(rows) >= PAGE else 1.0)
                if len(rows) < PAGE:
                    break
                nxt = int(rows[-1]["blockNumber"])
                # The last block may be cut: read it again from its start.
                start = nxt if nxt > start else nxt + 1
                if page == MAX_PAGES - 1:
                    partial = True
                elif PAUSE_S > 0:
                    await asyncio.sleep(PAUSE_S)
            if ok and out:
                out.sort(key=lambda t: (t["block"], t["log_index"]))
                return out, partial, base.split("/")[2]
            logger.info("transfer source %s refused %s %s", base, chain, token)

        if chain in _RPC_FALLBACK_ENDPOINTS:
            rpc_res = await _rpc_logs_fallback(chain, token)
            if rpc_res is not None:
                wallet_clusters.progress("transfers", 1.0)
                return rpc_res

        raise RuntimeError(f"no explorer answered for {chain}")
    finally:
        if own:
            await client.aclose()
