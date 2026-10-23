"""Wallet clusters and coordinated sells for Layer 0, Layer 1 and Layer 2
projects (`chain == "layer"`, e.g. Kaspa `kas-kaspa`, Injective
`inj-injective-protocol`, Arbitrum, Optimism, Celestia, Sei, LayerZero,
Mantle, Metis, zkSync, ZetaChain, etc.).

Three native paths, all using free keyless public APIs:
1. Kaspa (`kas-kaspa` / `KAS`): official Kaspa BlockDAG REST API
   (`https://api.kaspa.org`) — circulating supply, recent block transactions,
   holder balances (`/addresses/balances`) and UTXO transfer history
   (`/addresses/{addr}/full-transactions?resolve_previous_outpoints=light`).
2. Injective (`inj-injective-protocol` / `INJ`) & Cosmos-SDK L0/L1 chains
   (`tia-celestia`, `sei-sei`, `atom-cosmos`, `osmo-osmosis`, `akt-akash-network`,
   `axl-axelar`, `dym-dymension`, `saga-saga`, `ntrn-neutron`, `fet-fetch-ai`,
   `kava-kava`): native Cosmos LCD REST API (`/cosmos/tx/v1beta1/txs`,
   `/cosmos/bank/v1beta1/supply`, `/cosmos/bank/v1beta1/balances/{addr}`) with
   automatic fallback/enrichment from canonical ERC-20 explorer transfers
   (e.g. `INJ` on Ethereum `0xe28b3b32b6c345a34ff64674606124dd5aceca30`).
3. EVM & Solana L0/L1/L2 tokens: canonical token contract resolved from our
   curated registry, CoinPaprika `/v1/coins/{id}` (`contracts`), or DexScreener
   search, then scanned via Blockscout / Routescan / Solana cluster engines.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime
import logging
import re
import time

import httpx

from app.trading.onchain import projects_db, storage, sync_sells, transfer_sources

logger = logging.getLogger(__name__)

KASPA_API = "https://api.kaspa.org"
PAPRIKA_COIN = "https://api.coinpaprika.com/v1/coins/{cid}"
DEX_SEARCH = "https://api.dexscreener.com/latest/dex/search?q={q}"

# Canonical aliases so a user or test typing "kaspa", "KAS", "injective", "INJ"
# lands on the exact CoinPaprika id stored in projects_db / layers.py.
LAYER_ALIASES: dict[str, tuple[str, str]] = {
    "kas": ("kas-kaspa", "KAS"),
    "kaspa": ("kas-kaspa", "KAS"),
    "kas-kaspa": ("kas-kaspa", "KAS"),
    "inj": ("inj-injective-protocol", "INJ"),
    "injective": ("inj-injective-protocol", "INJ"),
    "injective-protocol": ("inj-injective-protocol", "INJ"),
    "inj-injective-protocol": ("inj-injective-protocol", "INJ"),
    "arb": ("arb-arbitrum", "ARB"),
    "arbitrum": ("arb-arbitrum", "ARB"),
    "arb-arbitrum": ("arb-arbitrum", "ARB"),
    "op": ("op-optimism", "OP"),
    "optimism": ("op-optimism", "OP"),
    "op-optimism": ("op-optimism", "OP"),
    "tia": ("tia-celestia", "TIA"),
    "celestia": ("tia-celestia", "TIA"),
    "tia-celestia": ("tia-celestia", "TIA"),
    "sei": ("sei-sei", "SEI"),
    "sei-sei": ("sei-sei", "SEI"),
    "zro": ("zro-layerzero", "ZRO"),
    "layerzero": ("zro-layerzero", "ZRO"),
    "zro-layerzero": ("zro-layerzero", "ZRO"),
    "mnt": ("mnt-mantle", "MNT"),
    "mantle": ("mnt-mantle", "MNT"),
    "mnt-mantle": ("mnt-mantle", "MNT"),
    "metis": ("metis-metisdao", "METIS"),
    "metis-metisdao": ("metis-metisdao", "METIS"),
    "zk": ("zk-zksync", "ZK"),
    "zksync": ("zk-zksync", "ZK"),
    "zk-zksync": ("zk-zksync", "ZK"),
    "zeta": ("zeta-zetachain", "ZETA"),
    "zetachain": ("zeta-zetachain", "ZETA"),
    "zeta-zetachain": ("zeta-zetachain", "ZETA"),
    "axl": ("axl-axelar", "AXL"),
    "axelar": ("axl-axelar", "AXL"),
    "axl-axelar": ("axl-axelar", "AXL"),
    "w": ("w-wormhole", "W"),
    "wormhole": ("w-wormhole", "W"),
    "w-wormhole": ("w-wormhole", "W"),
}

# Canonical (chain, contract_address, decimals) for L0/L1/L2 projects that have
# an official ERC-20 / SPL representation indexed on Blockscout/Routescan/Solana.
KNOWN_LAYER_CONTRACTS: dict[str, tuple[str, str, int]] = {
    "inj-injective-protocol": ("ethereum", "0xe28b3b32b6c345a34ff64674606124dd5aceca30", 18),
    "arb-arbitrum": ("arbitrum", "0x912ce59144191c1204e64559fe8253a0e49e6548", 18),
    "op-optimism": ("optimism", "0x4200000000000000000000000000000000000042", 18),
    "mnt-mantle": ("ethereum", "0x3c3a81e81dc49a522a592e7622a7e711c06bf354", 18),
    "metis-metisdao": ("ethereum", "0x9e32b13ce7f2e80a01932b42553652e053d6ed8e", 18),
    "zk-zksync": ("zksync", "0x5a7d6b2f92c77fad6ccabd7ee0624e64907eaf3e", 18),
    "scr-scroll": ("scroll", "0xd29687c813d741e2f938f4ac377128810e217b1b", 18),
    "scroll-scroll": ("scroll", "0xd29687c813d741e2f938f4ac377128810e217b1b", 18),
    "blast-blast": ("blast", "0xb1a5700fa2358173fe465e6ea4ff52e36e88e2ad", 18),
    "mode-mode": ("mode", "0xdfc7c877a950e49d2610114102175a06c2e3167a", 18),
    "taiko-taiko": ("ethereum", "0x10dea67478c5f8c5e2d90e5e9b26dbe60c54d800", 18),
    "zro-layerzero": ("ethereum", "0x6985884c4392d348587b19cb9eaaf157f13271cd", 18),
    "axl-axelar": ("ethereum", "0x467719ad09025fcc6cf6f8311755809d45a5e5f3", 6),
    "zeta-zetachain": ("ethereum", "0xf091867ec603a6628ed83d274e835539d82e9cc8", 18),
    "omni-omni-network": ("ethereum", "0x36e66fbbce51e4cd5bd3c62b637eb411b18949d4", 18),
    "qnt-quant": ("ethereum", "0x4a220e6096b25eadb88358cb44068a3248254675", 18),
    "matic-polygon": ("ethereum", "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb", 18),
    "pol-polygon-ecosystem-token": ("ethereum", "0x455e53cbb86018ac2b8092fdcd39d8444affc3f6", 18),
    "strk-starknet": ("ethereum", "0xca14007eff0db1f8135f4c25b34de49ab0d42766", 18),
    "imx-immutable-x": ("ethereum", "0xf57e7e7c23978c3caec3c3548e3d615c346e79ff", 18),
    "lrc-loopring": ("ethereum", "0xbbbbca6a901c926f240b89eacb641d8aec7aeafd", 18),
    "manta-manta-network": ("arbitrum", "0x95cef13441be50d20ca4558cc0a27b601ac544e5", 18),
    "boba-boba-network": ("ethereum", "0x42bbfa2e77757c645eeaad1655e0911a7553efbc", 18),
    "celo-celo": ("celo", "0x471ece3750da237f93b8e339c536989b8978a438", 18),
    "gno-gnosis": ("gnosis", "0x9c58bacc331c9aa871afd802db6379a98e80cedb", 18),
    "fet-fetch-ai": ("ethereum", "0xaea46a60368a7bd060eec7df8cba43b7ef41ad85", 18),
    "cro-cronos": ("ethereum", "0xa0b73e1ff0b80914ab6fe0444e65848c4c34450b", 8),
    "w-wormhole": ("solana", "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ", 6),
}

# Cosmos-SDK L0/L1 native LCD REST endpoints (free, keyless).
COSMOS_CHAINS: dict[str, dict] = {
    "inj-injective-protocol": {
        "symbol": "INJ",
        "denom": "inj",
        "decimals": 18,
        "lcds": [
            "https://sentry.lcd.injective.network",
            "https://injective-rest.publicnode.com",
        ],
    },
    "tia-celestia": {
        "symbol": "TIA",
        "denom": "utia",
        "decimals": 6,
        "lcds": ["https://celestia-rest.publicnode.com"],
    },
    "sei-sei": {
        "symbol": "SEI",
        "denom": "usei",
        "decimals": 6,
        "lcds": ["https://sei-rest.publicnode.com"],
    },
    "atom-cosmos": {
        "symbol": "ATOM",
        "denom": "uatom",
        "decimals": 6,
        "lcds": ["https://cosmos-rest.publicnode.com"],
    },
    "osmo-osmosis": {
        "symbol": "OSMO",
        "denom": "uosmo",
        "decimals": 6,
        "lcds": ["https://osmosis-rest.publicnode.com"],
    },
    "akt-akash-network": {
        "symbol": "AKT",
        "denom": "uakt",
        "decimals": 6,
        "lcds": ["https://akash-rest.publicnode.com"],
    },
    "axl-axelar": {
        "symbol": "AXL",
        "denom": "uaxl",
        "decimals": 6,
        "lcds": ["https://axelar-rest.publicnode.com"],
    },
    "dym-dymension": {
        "symbol": "DYM",
        "denom": "adym",
        "decimals": 18,
        "lcds": ["https://dymension-rest.publicnode.com"],
    },
    "saga-saga": {
        "symbol": "SAGA",
        "denom": "usaga",
        "decimals": 6,
        "lcds": ["https://saga-rest.publicnode.com"],
    },
    "kava-kava": {
        "symbol": "KAVA",
        "denom": "ukava",
        "decimals": 6,
        "lcds": ["https://kava-rest.publicnode.com"],
    },
}

_LAYER_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,80}$", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"^(\d+)([a-zA-Z/0-9_-]+)$")


def is_valid_layer_token(token: str) -> bool:
    return bool(_LAYER_TOKEN_RE.match((token or "").strip()))


def resolve_layer_token(token: str, symbol: str = "") -> tuple[str, str]:
    """Normalizes a user-supplied or leaderboard layer identifier (e.g.
    'kaspa', 'KAS', 'kas-kaspa', 'injective', 'INJ') to (token_id, symbol)."""
    raw = (token or "").strip().lower()
    sym = (symbol or "").strip().upper()
    if raw in LAYER_ALIASES:
        cid, csym = LAYER_ALIASES[raw]
        # Prefer the exact key stored in projects_db if present
        if projects_db.get("layer", raw) is not None:
            return raw, sym or csym
        return cid, sym or csym
    if sym.lower() in LAYER_ALIASES:
        cid, csym = LAYER_ALIASES[sym.lower()]
        if projects_db.get("layer", raw) is not None:
            return raw, sym or csym
        return cid, sym or csym
    row = projects_db.get("layer", raw)
    if row is not None:
        return row["token"], (row.get("symbol") or sym or raw.upper())
    # Search projects_db layer rows by symbol or name
    try:
        items = projects_db.search(chain="layer", q=raw, limit=5)["items"]
        for it in items:
            if (it.get("symbol") or "").lower() == raw or (it.get("name") or "").lower() == raw or it.get("token") == raw:
                return it["token"], (it.get("symbol") or sym or raw.upper())
    except Exception:  # noqa: BLE001
        pass
    return raw, sym or raw.split("-")[0].upper()


def _is_kaspa(token: str, symbol: str) -> bool:
    t = (token or "").lower()
    s = (symbol or "").upper()
    return t in ("kas-kaspa", "kaspa", "kas") or t.startswith("kaspa") or s == "KAS"


def _parse_iso_ts(val: str | int | float | None) -> int:
    if isinstance(val, (int, float)):
        return int(val / 1000) if val > 1e12 else int(val)
    if isinstance(val, str) and val:
        try:
            return int(datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return int(time.time())


# --- 1. Kaspa BlockDAG (`https://api.kaspa.org`) ----------------------------

def _kaspa_tx_transfers(tx: dict) -> list[dict]:
    """Extracts UTXO transfers from one Kaspa transaction object."""
    tx_id = tx.get("transaction_id") or (tx.get("verboseData") or {}).get("transactionId") or tx.get("hash") or ""
    btime = tx.get("block_time") or (tx.get("verboseData") or {}).get("blockTime") or int(time.time() * 1000)
    ts = int(btime // 1000) if btime > 1e11 else int(btime)
    block = int(tx.get("accepting_block_blue_score") or (tx.get("verboseData") or {}).get("blueScore") or ts)

    senders: list[str] = []
    for inp in tx.get("inputs") or []:
        addr = inp.get("previous_outpoint_address") or (inp.get("previousOutpoint") or {}).get("address")
        if isinstance(addr, str) and addr.startswith("kaspa:") and addr not in senders:
            senders.append(addr)

    if not senders:
        return []
    primary = senders[0]
    sender_set = set(senders)
    out: list[dict] = []
    for idx, o in enumerate(tx.get("outputs") or []):
        dst = o.get("script_public_key_address") or (o.get("verboseData") or {}).get("scriptPublicKeyAddress")
        amt = int(o.get("amount") or 0)
        if not isinstance(dst, str) or not dst.startswith("kaspa:") or amt <= 0:
            continue
        if dst in sender_set:
            continue  # UTXO change back to sender
        out.append({
            "block": block,
            "ts": ts,
            "tx": tx_id,
            "log_index": idx,
            "from": primary,
            "to": dst,
            "amount": amt,
        })
    return out


async def build_kaspa(token: str, symbol: str = "KAS", client: httpx.AsyncClient | None = None) -> dict:
    """Builds the wallet cluster report for Kaspa (`kas-kaspa`) via api.kaspa.org."""
    from app.trading.onchain import wallet_clusters

    own = client is None
    client = client or httpx.AsyncClient(timeout=25.0, headers={"accept": "application/json"})
    try:
        wallet_clusters.progress("transfers", 0.05)
        supply = 25_000_000_000 * 10**8
        try:
            r_sup = await client.get(f"{KASPA_API}/info/coinsupply")
            if r_sup.status_code == 200:
                cs = int(float((r_sup.json() or {}).get("circulatingSupply") or supply))
                if cs > 0:
                    supply = cs
        except Exception:  # noqa: BLE001
            pass

        transfers: list[dict] = []
        seen_tx: set[tuple[str, str, str, int]] = set()
        candidate_addrs: Counter[str] = Counter()

        # Step 1: sample recent virtual-chain blocks for active Kaspa addresses & transfers
        blue_score = 0
        try:
            r_bs = await client.get(f"{KASPA_API}/info/virtual-chain-blue-score")
            if r_bs.status_code == 200:
                blue_score = int((r_bs.json() or {}).get("blueScore") or 0)
        except Exception:  # noqa: BLE001
            pass

        if blue_score > 0:
            offsets = [0, 30, 90, 240, 600]
            for step_i, off in enumerate(offsets):
                try:
                    r_blk = await client.get(
                        f"{KASPA_API}/blocks-from-bluescore",
                        params={"blueScore": max(1, blue_score - off), "includeTransactions": "true"},
                    )
                    if r_blk.status_code == 200 and isinstance(r_blk.json(), list):
                        for blk in r_blk.json():
                            for tx in blk.get("transactions") or []:
                                for o in tx.get("outputs") or []:
                                    a = o.get("script_public_key_address") or (o.get("verboseData") or {}).get("scriptPublicKeyAddress")
                                    amt = int(o.get("amount") or 0)
                                    if isinstance(a, str) and a.startswith("kaspa:") and amt > 0:
                                        candidate_addrs[a] += amt
                                for tr in _kaspa_tx_transfers(tx):
                                    k = (tr["tx"], tr["from"], tr["to"], tr["amount"])
                                    if k not in seen_tx:
                                        seen_tx.add(k)
                                        transfers.append(tr)
                except Exception:  # noqa: BLE001
                    pass
                wallet_clusters.progress("transfers", 0.1 + 0.3 * (step_i + 1) / len(offsets))

        # Step 2: query balances for the discovered active addresses
        probe_addrs = [a for a, _ in candidate_addrs.most_common(60)]
        balances_map: dict[str, int] = {}
        if probe_addrs:
            try:
                r_bal = await client.post(f"{KASPA_API}/addresses/balances", json={"addresses": probe_addrs[:50]})
                if r_bal.status_code == 200 and isinstance(r_bal.json(), list):
                    for row in r_bal.json():
                        a = row.get("address")
                        b = int(row.get("balance") or 0)
                        if isinstance(a, str) and b > 0:
                            balances_map[a] = b
            except Exception:  # noqa: BLE001
                pass

        ranked_holders = [a for a, _ in sorted((balances_map or candidate_addrs).items(), key=lambda x: -x[1])][:28]
        wallet_clusters.progress("holders", 0.5)

        # Step 3: pull full transaction history (with resolved input addresses) for top holders
        for idx, addr in enumerate(ranked_holders):
            try:
                r_tx = await client.get(
                    f"{KASPA_API}/addresses/{addr}/full-transactions",
                    params={"limit": 40, "resolve_previous_outpoints": "light"},
                )
                if r_tx.status_code == 200 and isinstance(r_tx.json(), list):
                    for tx in r_tx.json():
                        for tr in _kaspa_tx_transfers(tx):
                            k = (tr["tx"], tr["from"], tr["to"], tr["amount"])
                            if k not in seen_tx:
                                seen_tx.add(k)
                                transfers.append(tr)
            except Exception:  # noqa: BLE001
                pass
            wallet_clusters.progress("transfers", 0.5 + 0.4 * (idx + 1) / max(1, len(ranked_holders)))

        if not transfers:
            raise RuntimeError("kaspa: no transfers returned from api.kaspa.org")

        transfers.sort(key=lambda t: (t["block"], t["log_index"]))
        return _finalize_layer_build(
            token=token,
            symbol=symbol or "KAS",
            transfers=transfers,
            supply=supply,
            balances_override=balances_map,
            source="api.kaspa.org",
            block_s=1.0,
        )
    finally:
        if own:
            await client.aclose()


async def kaspa_new_sells(cfg: dict, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Reads recent UTXO transfers from watched Kaspa wallets for sync_watch."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0, headers={"accept": "application/json"})
    wallets = list(cfg.get("wallets") or [])[:35]
    ws = set(wallets)
    out: list[dict] = []
    seen: set[tuple[str, str, str, int]] = set()
    try:
        for addr in wallets:
            if not str(addr).startswith("kaspa:"):
                continue
            try:
                r = await client.get(
                    f"{KASPA_API}/addresses/{addr}/full-transactions",
                    params={"limit": 20, "resolve_previous_outpoints": "light"},
                )
                if r.status_code == 200 and isinstance(r.json(), list):
                    for tx in r.json():
                        for tr in _kaspa_tx_transfers(tx):
                            if tr["from"] in ws:
                                k = (tr["tx"], tr["from"], tr["to"], tr["amount"])
                                if k not in seen:
                                    seen.add(k)
                                    out.append(tr)
            except Exception:  # noqa: BLE001
                continue
        return out
    finally:
        if own:
            await client.aclose()


# --- 2. Injective & Cosmos-SDK L0/L1 chains ---------------------------------

def _cosmos_tx_transfers(tx_resp: dict, target_denom: str = "") -> list[dict]:
    """Extracts bank MsgSend / transfer events from a Cosmos LCD tx_response."""
    tx_hash = tx_resp.get("txhash") or ""
    height = int(tx_resp.get("height") or 0)
    ts = _parse_iso_ts(tx_resp.get("timestamp"))
    out: list[dict] = []

    # Check both top-level events and logs[].events
    events = list(tx_resp.get("events") or [])
    for lg in tx_resp.get("logs") or []:
        events.extend(lg.get("events") or [])

    idx = 0
    for ev in events:
        if ev.get("type") != "transfer":
            continue
        attrs = {a.get("key"): a.get("value") for a in ev.get("attributes") or [] if isinstance(a, dict)}
        sender = attrs.get("sender") or ""
        recipient = attrs.get("recipient") or ""
        raw_amt = attrs.get("amount") or ""
        if not sender or not recipient or sender == recipient or not raw_amt:
            continue
        for part in str(raw_amt).split(","):
            m = _AMOUNT_RE.match(part.strip())
            if not m:
                continue
            amt_val, denom = int(m.group(1)), m.group(2)
            if target_denom and denom.lower() != target_denom.lower():
                continue
            if amt_val > 0:
                out.append({
                    "block": height or ts,
                    "ts": ts,
                    "tx": tx_hash,
                    "log_index": idx,
                    "from": sender,
                    "to": recipient,
                    "amount": amt_val,
                })
                idx += 1

    # Also inspect tx.body.messages for MsgSend if events were stripped
    if not out:
        msgs = ((tx_resp.get("tx") or {}).get("body") or {}).get("messages") or []
        for m in msgs:
            if "MsgSend" not in str(m.get("@type") or ""):
                continue
            sender = m.get("from_address") or ""
            recipient = m.get("to_address") or ""
            for coin in m.get("amount") or []:
                denom = coin.get("denom") or ""
                if target_denom and denom.lower() != target_denom.lower():
                    continue
                amt_val = int(coin.get("amount") or 0)
                if sender and recipient and sender != recipient and amt_val > 0:
                    out.append({
                        "block": height or ts,
                        "ts": ts,
                        "tx": tx_hash,
                        "log_index": idx,
                        "from": sender,
                        "to": recipient,
                        "amount": amt_val,
                    })
                    idx += 1
    return out


async def build_cosmos(
    cid: str,
    symbol: str,
    cfg_cosmos: dict,
    client: httpx.AsyncClient | None = None,
) -> dict | None:
    """Builds wallet clusters from a Cosmos-SDK LCD API (Injective, Celestia, Sei, etc.)."""
    from app.trading.onchain import wallet_clusters

    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0, headers={"accept": "application/json"})
    denom = cfg_cosmos["denom"]
    decimals = cfg_cosmos.get("decimals", 6)
    try:
        for base in cfg_cosmos.get("lcds") or []:
            transfers: list[dict] = []
            seen: set[tuple[str, str, str, int]] = set()
            supply = 100_000_000 * (10 ** decimals)
            try:
                r_sup = await client.get(
                    f"{base}/cosmos/bank/v1beta1/supply/by_denom",
                    params={"denom": denom},
                )
                if r_sup.status_code == 200:
                    amt = int(((r_sup.json() or {}).get("amount") or {}).get("amount") or 0)
                    if amt > 0:
                        supply = amt
            except Exception:  # noqa: BLE001
                pass

            queries = [
                "message.action='/cosmos.bank.v1beta1.MsgSend'",
                "message.module='bank'",
            ]
            for q in queries:
                for page in range(1, 5):
                    try:
                        r_tx = await client.get(
                            f"{base}/cosmos/tx/v1beta1/txs",
                            params={
                                "events": q,
                                "pagination.limit": "100",
                                "pagination.offset": str((page - 1) * 100),
                                "order_by": "ORDER_BY_DESC",
                            },
                        )
                        if r_tx.status_code != 200:
                            break
                        tx_resps = (r_tx.json() or {}).get("tx_responses") or []
                        if not tx_resps:
                            break
                        for txr in tx_resps:
                            for tr in _cosmos_tx_transfers(txr, denom):
                                k = (tr["tx"], tr["from"], tr["to"], tr["amount"])
                                if k not in seen:
                                    seen.add(k)
                                    transfers.append(tr)
                        wallet_clusters.progress("transfers", min(0.85, len(transfers) / 300))
                        if len(tx_resps) < 100:
                            break
                    except Exception:  # noqa: BLE001
                        break
                if len(transfers) >= 80:
                    break

            if len(transfers) >= 10:
                transfers.sort(key=lambda t: (t["block"], t["log_index"]))
                host = base.split("/")[2]
                return _finalize_layer_build(
                    token=cid,
                    symbol=symbol or cfg_cosmos["symbol"],
                    transfers=transfers,
                    supply=supply,
                    balances_override=None,
                    source=host,
                    block_s=2.0,
                )
        return None
    finally:
        if own:
            await client.aclose()


# --- 3. EVM & Solana L0/L1/L2 contract resolution ---------------------------

_PAPRIKA_PLATFORM_MAP = {
    "ethereum-eth": "ethereum",
    "eth-ethereum": "ethereum",
    "base-base": "base",
    "bnb-binance-coin": "bsc",
    "binance-smart-chain": "bsc",
    "arb-arbitrum": "arbitrum",
    "op-optimism": "optimism",
    "matic-polygon": "polygon",
    "avax-avalanche": "avalanche",
    "sol-solana": "solana",
    "mnt-mantle": "mantle",
    "metis-metisdao": "metis",
    "zk-zksync": "zksync",
    "celo-celo": "celo",
    "gno-gnosis": "gnosis",
    "ftm-fantom": "fantom",
}


async def resolve_contract(cid: str, symbol: str, client: httpx.AsyncClient | None = None) -> tuple[str, str] | None:
    """Resolves a `chain == 'layer'` project to (target_chain, contract_address)
    when an EVM or Solana token contract exists for it."""
    norm_cid, norm_sym = resolve_layer_token(cid, symbol)
    if norm_cid in KNOWN_LAYER_CONTRACTS:
        ch, addr, _dec = KNOWN_LAYER_CONTRACTS[norm_cid]
        return ch, addr

    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0, headers={"accept": "application/json"})
    try:
        # 1. CoinPaprika /v1/coins/{cid} contracts list
        try:
            r = await client.get(PAPRIKA_COIN.format(cid=norm_cid))
            if r.status_code == 200:
                coin = r.json() or {}
                for c in coin.get("contracts") or []:
                    plat = _PAPRIKA_PLATFORM_MAP.get((c.get("platform") or "").lower())
                    addr = (c.get("contract") or "").strip()
                    if plat and addr and (plat in transfer_sources.SOURCES or plat == "solana"):
                        return plat, addr.lower() if addr.startswith("0x") else addr
        except Exception:  # noqa: BLE001
            pass

        # 2. DexScreener search by symbol
        q = norm_sym or cid
        if q:
            try:
                r = await client.get(DEX_SEARCH.format(q=q))
                if r.status_code == 200:
                    pairs = (r.json() or {}).get("pairs") or []
                    best = None
                    best_liq = -1.0
                    for p in pairs:
                        ch = (p.get("chainId") or "").lower()
                        base_tok = p.get("baseToken") or {}
                        addr = (base_tok.get("address") or "").strip()
                        bsym = (base_tok.get("symbol") or "").upper()
                        liq = float((p.get("liquidity") or {}).get("usd") or 0.0)
                        if bsym == norm_sym.upper() and (ch in transfer_sources.SOURCES or ch == "solana") and liq > best_liq:
                            best = (ch, addr.lower() if addr.startswith("0x") else addr)
                            best_liq = liq
                    if best:
                        return best
            except Exception:  # noqa: BLE001
                pass
        return None
    finally:
        if own:
            await client.aclose()


# --- Shared cluster builder & sync_watch handoff ----------------------------

def _finalize_layer_build(
    token: str,
    symbol: str,
    transfers: list[dict],
    supply: int,
    balances_override: dict[str, int] | None,
    source: str,
    block_s: float = 2.0,
) -> dict:
    """Runs wallet_clusters.cluster() on normalized transfers, writes both the
    wallet_clusters file and the sync_watch / sync_sells report under
    `chain='layer'`."""
    from app.trading.onchain import sync_watch, wallet_clusters

    bal, peak = wallet_clusters.balances(transfers)
    if balances_override:
        for a, b in balances_override.items():
            bal[a] = max(bal.get(a, 0), b)
            peak[a] = max(peak.get(a, 0), b)

    # Identify high-degree hub addresses (exchanges, routers, validator pools)
    # that interact with >= 25 distinct counterparties so their outflows are
    # treated as first buys and inflows as sells.
    counterparties: dict[str, set[str]] = defaultdict(set)
    for t in transfers:
        counterparties[t["from"]].add(t["to"])
        counterparties[t["to"]].add(t["from"])
    contracts = {a for a, peers in counterparties.items() if len(peers) >= 25}

    wallet_clusters.progress("holders", 0.8)
    wallet_clusters.live(
        holders=[
            {"address": a, "share": round(v / supply, 5) if supply else None}
            for a, v in sorted(peak.items(), key=lambda x: -x[1])
            if a not in contracts and a not in wallet_clusters.DEAD
        ][:wallet_clusters.TOP_WATCH],
        counts={"holders": len(peak), "transfers": len(transfers)},
    )

    wallet_clusters.progress("clusters", None)
    res = wallet_clusters.cluster(transfers, contracts, supply, block_s=block_s)
    if balances_override and supply > 0:
        for a in res["top"]:
            if a in balances_override:
                res["shares"][a] = round(max(0, balances_override[a]) / supply, 6)

    wallet_clusters.live(
        clusters=[
            {"id": c["id"], "wallets": c["wallets"], "edges": c.get("edges", []), "links": c.get("links", [])}
            for c in res["clusters"]
        ],
        top=res["top"],
    )
    wallet_clusters.live(
        counts={
            "holders": len(peak),
            "transfers": len(transfers),
            "clusters": len(res["clusters"]),
            "waves": len(res.get("waves") or []),
        }
    )

    first_b = transfers[0]["block"]
    last_b = transfers[-1]["block"]
    first_ts = transfers[0].get("ts")
    res.update(
        chain="layer",
        token=token,
        symbol=symbol,
        built_at=int(time.time()),
        partial=True,
        from_block=first_b,
        to_block=last_b,
        transfers=len(transfers),
        supply=str(supply),
        contracts=sorted(contracts),
        block_s=round(block_s, 4),
        coverage={
            "source": source,
            "partial": True,
            "from_block": first_b,
            "to_block": last_b,
            "from_ts": first_ts,
            "transfers": len(transfers),
            "rules": wallet_clusters.RULES,
        },
    )
    wallet_clusters._dir().mkdir(parents=True, exist_ok=True)
    from app.atomic_write import write_text_atomic
    import json

    write_text_atomic(wallet_clusters._dir() / f"{wallet_clusters._key('layer', token)}.json", json.dumps(res))

    clusters = [
        {"id": c["id"], "wallets": c["wallets"], "links": c["links"], "edges": c["edges"]}
        for c in res["clusters"]
    ] + [{"id": "top", "wallets": res["top"], "links": ["top_holders"]}]
    wallets = list(dict.fromkeys(w for c in clusters for w in c["wallets"]))[:sync_watch.MAX_WALLETS]
    if len(wallets) >= 2:
        wallet_clusters.progress("sells", None)
        ws = set(wallets)
        cut = time.time() - sync_watch.KEEP_S
        mine = [dict(t) for t in transfers if t["from"] in ws and (t.get("ts") is None or t["ts"] >= cut)]
        cfg = sync_watch.save({
            "chain": "layer",
            "token": token,
            "symbol": symbol,
            "pools": sorted(contracts) or ["pool"],
            "wallets": wallets,
            "shares": {w: res["shares"].get(w, 0.0) for w in wallets},
            "clusters": clusters,
            "source": "auto",
            "coverage": res["coverage"],
            "supply": str(supply),
        })
        if cfg:
            sync_watch.seed(cfg, mine, last_b + 1)
        rep = sync_sells.report(
            "layer",
            token,
            mine,
            clusters,
            sorted(contracts) or ["pool"],
            supply,
            symbol,
            {w: res["shares"].get(w, 0.0) for w in wallets},
        )
        rep["coverage"] = res["coverage"]
        sync_sells.write_report(rep)
    return res


async def build(token: str, symbol: str = "", created_at: float | None = None, client: httpx.AsyncClient | None = None) -> dict:
    """Main entry point called by `wallet_clusters.build('layer', ...)`."""
    norm_cid, norm_sym = resolve_layer_token(token, symbol)
    keep_token = (token or norm_cid).strip().lower()

    # 1. Kaspa (native BlockDAG REST API)
    if _is_kaspa(norm_cid, norm_sym):
        return await build_kaspa(keep_token, norm_sym or "KAS", client=client)

    # 2. Injective & Cosmos-SDK L0/L1 chains: try native Cosmos LCD first,
    #    then fall back to canonical ERC-20 explorer transfers (e.g. INJ on Ethereum).
    if norm_cid in COSMOS_CHAINS:
        cosmos_res = await build_cosmos(keep_token, norm_sym, COSMOS_CHAINS[norm_cid], client=client)
        if cosmos_res is not None:
            return cosmos_res

    # 3. Canonical EVM / Solana contract (static table, CoinPaprika, or DexScreener)
    resolved = await resolve_contract(norm_cid, norm_sym, client=client)
    if resolved:
        target_chain, contract_addr = resolved
        if target_chain == "solana":
            from app.trading.onchain import solana_clusters, sync_watch, wallet_clusters
            import json
            from app.atomic_write import write_text_atomic

            res = await solana_clusters.build(contract_addr)
            res.update(
                chain="layer",
                token=keep_token,
                symbol=norm_sym,
                built_at=int(time.time()),
                partial=True,
                transfers=res["coverage"]["transfers"],
            )
            res["coverage"]["rules"] = wallet_clusters.RULES
            wallet_clusters._dir().mkdir(parents=True, exist_ok=True)
            write_text_atomic(wallet_clusters._dir() / f"{wallet_clusters._key('layer', keep_token)}.json", json.dumps(res))
            clusters = [
                {"id": c["id"], "wallets": c["wallets"], "links": c["links"], "edges": c["edges"]}
                for c in res["clusters"]
            ] + [{"id": "top", "wallets": res["top"], "links": ["top_holders"]}]
            rep = sync_sells.report("layer", keep_token, [], clusters, ["pool"], int(res.get("supply") or 0), norm_sym, res.get("shares"))
            rep["coverage"] = res["coverage"]
            sync_sells.write_report(rep)
            return res

        from app.trading.onchain import wallet_clusters
        transfers, _partial, source = await transfer_sources.transfers(target_chain, contract_addr, client=client)
        supply = sum(v for v in wallet_clusters.balances(transfers)[0].values() if v > 0)
        return _finalize_layer_build(
            token=keep_token,
            symbol=norm_sym,
            transfers=transfers,
            supply=max(supply, 1),
            balances_override=None,
            source=source,
            block_s=2.0,
        )

    raise RuntimeError(f"layer {keep_token}: no public transfer source answered")


async def run_watch_layer(cfg: dict) -> dict:
    """Updates the coordinated sells report of a watched `chain == 'layer'` project."""
    from app.atomic_write import write_text_atomic
    from app.trading.onchain import sync_watch
    import json

    token = cfg["token"]
    symbol = cfg.get("symbol") or ""
    norm_cid, norm_sym = resolve_layer_token(token, symbol)
    key = sync_watch._key("layer", token)
    tpath = sync_watch._dir() / f"{key}.transfers.json"
    state = dict(cfg.get("state") or {})
    existing = sync_watch._load(tpath) or []

    new_moves: list[dict] = []
    if _is_kaspa(norm_cid, norm_sym):
        new_moves = await kaspa_new_sells(cfg)
    elif norm_cid in COSMOS_CHAINS:
        # Poll latest Cosmos bank txs from watched wallets
        ws = set(cfg.get("wallets") or [])
        cosmos_cfg = COSMOS_CHAINS[norm_cid]
        async with httpx.AsyncClient(timeout=15.0) as client:
            for base in cosmos_cfg.get("lcds") or []:
                try:
                    r = await client.get(
                        f"{base}/cosmos/tx/v1beta1/txs",
                        params={
                            "events": "message.action='/cosmos.bank.v1beta1.MsgSend'",
                            "pagination.limit": "100",
                            "order_by": "ORDER_BY_DESC",
                        },
                    )
                    if r.status_code == 200:
                        for txr in (r.json() or {}).get("tx_responses") or []:
                            for tr in _cosmos_tx_transfers(txr, cosmos_cfg["denom"]):
                                if tr["from"] in ws:
                                    new_moves.append(tr)
                        break
                except Exception:  # noqa: BLE001
                    continue

    cut = time.time() - sync_watch.KEEP_S
    seen = {(t.get("tx"), t.get("from"), t.get("to"), t.get("amount")) for t in existing}
    merged = list(existing)
    for m in new_moves:
        k = (m.get("tx"), m.get("from"), m.get("to"), m.get("amount"))
        if k not in seen:
            seen.add(k)
            merged.append(m)
    merged = [t for t in merged if t.get("ts") is None or t["ts"] >= cut]
    write_text_atomic(tpath, json.dumps(merged))

    supply = int(cfg.get("supply") or 0) or max(1, sum(int(t.get("amount") or 0) for t in merged))
    clusters = cfg.get("clusters") or [{"id": "c1", "wallets": cfg["wallets"]}]
    pools = cfg.get("pools") or ["pool"]
    rep = sync_sells.report("layer", token, merged, clusters, pools, supply, symbol, cfg.get("shares"))
    if cfg.get("coverage"):
        rep["coverage"] = cfg["coverage"]
    sync_sells.write_report(rep)
    state.update(last_run=int(time.time()), error=None)
    return state
