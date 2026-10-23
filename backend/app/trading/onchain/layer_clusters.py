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

from collections import Counter, defaultdict
from datetime import datetime
import logging
import re
import time

import httpx

from app.trading.onchain import projects_db, sync_sells, transfer_sources

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
    "octa": ("octa-octaspace", "OCTA"),
    "octaspace": ("octa-octaspace", "OCTA"),
    "octa-octaspace": ("octa-octaspace", "OCTA"),
}

# Native L1 chains with a Blockscout v2 / v1 explorer (`/accounts`, `/api/v2/addresses`).
BLOCKSCOUT_NATIVE_CHAINS: dict[str, dict] = {
    "octa-octaspace": {
        "symbol": "OCTA",
        "origin": "https://scan.octa.space",
        "decimals": 18,
        "block_s": 11.2,
    },
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


# --- 3. Blockscout Native L1 chains (e.g. OctaSpace https://scan.octa.space/accounts) ---

def _extract_blockscout_native_tx(tx: dict, fallback_idx: int = 0) -> dict | None:
    """Extracts a native L1 coin transfer from a Blockscout v2 `/api/v2/transactions`
    or `/api/v2/addresses/{addr}/transactions` item."""
    frm = str((tx.get("from") or {}).get("hash") or "").lower()
    to = str((tx.get("to") or {}).get("hash") or "").lower()
    if not frm or not to or frm == to:
        return None
    raw_val = str(tx.get("value") or "0").split(".")[0] or "0"
    try:
        val = int(raw_val)
    except ValueError:
        return None
    if val <= 0:
        return None
    blk = int(tx.get("block_number") or tx.get("block") or (fallback_idx + 1))
    ts_val = _parse_iso_ts(tx.get("timestamp"))
    tx_hash = str(tx.get("hash") or f"bs-nat-{fallback_idx}")
    return {
        "block": blk,
        "ts": ts_val,
        "tx": tx_hash,
        "log_index": int(tx.get("position") or tx.get("index") or fallback_idx),
        "from": frm,
        "to": to,
        "amount": val,
    }


async def build_blockscout_native(
    origin: str,
    token: str,
    symbol: str = "OCTA",
    block_s: float = 11.2,
    decimals: int = 18,
    out_chain: str = "layer",
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Builds wallet clusters and coordinated sells for a native L1 coin
    indexed on a Blockscout v2/v1 explorer (e.g. `https://scan.octa.space/accounts`)."""
    import asyncio
    from urllib.parse import urlparse
    from app.trading.onchain import wallet_clusters

    origin = origin.rstrip("/")
    source = urlparse(origin).netloc or origin
    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"accept": "application/json"})

    balances_override: dict[str, int] = {}
    supply = 0
    transfers: list[dict] = []
    seen_tx: set[tuple[str, str, str, int]] = set()

    try:
        wallet_clusters.progress("holders", 0.15)
        # Step 1: top native coin holders from Blockscout v2 `/api/v2/addresses`
        try:
            r_addr = await client.get(f"{origin}/api/v2/addresses")
            if r_addr.status_code == 200:
                ad = r_addr.json() or {}
                for it in ad.get("items") or []:
                    addr = str(it.get("hash") or "").lower()
                    raw_bal = str(it.get("coin_balance") or "0").split(".")[0] or "0"
                    try:
                        bal_val = int(raw_bal)
                    except ValueError:
                        bal_val = 0
                    if addr.startswith("0x") and bal_val > 0 and addr not in wallet_clusters.DEAD:
                        balances_override[addr] = bal_val
                ts_raw = ad.get("total_supply")
                if ts_raw is not None:
                    ts_str = str(ts_raw).strip()
                    try:
                        ts_flt = float(ts_str)
                        max_holder = max(balances_override.values(), default=0)
                        if "." in ts_str or (max_holder > 10**18 and ts_flt < 10**15):
                            supply = int(ts_flt * (10**decimals))
                        else:
                            supply = int(ts_str.split(".")[0] or 0)
                    except ValueError:
                        pass
        except Exception:  # noqa: BLE001
            pass

        # Fallback v1: `?module=account&action=listaccounts`
        if not balances_override:
            try:
                r_v1_acc = await client.get(
                    f"{origin}/api",
                    params={"module": "account", "action": "listaccounts", "page": 1, "offset": 50},
                )
                if r_v1_acc.status_code == 200:
                    for row in (r_v1_acc.json() or {}).get("result") or []:
                        if not isinstance(row, dict):
                            continue
                        addr = str(row.get("address") or "").lower()
                        raw_bal = str(row.get("balance") or "0").split(".")[0] or "0"
                        try:
                            bal_val = int(raw_bal)
                        except ValueError:
                            bal_val = 0
                        if addr.startswith("0x") and bal_val > 0 and addr not in wallet_clusters.DEAD:
                            balances_override[addr] = bal_val
            except Exception:  # noqa: BLE001
                pass

        supply = max(supply, sum(balances_override.values()), 1)
        if balances_override:
            wallet_clusters.progress("holders", 0.45)
            wallet_clusters.live(
                holders=[
                    {"address": a, "share": round(v / supply, 5) if supply else None}
                    for a, v in sorted(balances_override.items(), key=lambda x: -x[1])
                ][:wallet_clusters.TOP_WATCH],
                counts={"holders": len(balances_override), "transfers": 0},
            )

        # Step 2: recent chain-wide native transactions (`/api/v2/transactions`)
        wallet_clusters.progress("transfers", 0.2)
        try:
            r_txs = await client.get(f"{origin}/api/v2/transactions")
            if r_txs.status_code == 200:
                for idx, tx in enumerate((r_txs.json() or {}).get("items") or []):
                    tr = _extract_blockscout_native_tx(tx, idx)
                    if tr is not None:
                        k = (tr["tx"], tr["from"], tr["to"], tr["amount"])
                        if k not in seen_tx:
                            seen_tx.add(k)
                            transfers.append(tr)
        except Exception:  # noqa: BLE001
            pass

        # Step 3: per-holder native transaction history for top holders (batched)
        ranked_holders = [
            a for a, _ in sorted(balances_override.items(), key=lambda x: -x[1])[:25]
        ]

        async def _fetch_holder_txs(addr: str) -> list[dict]:
            holder_trs: list[dict] = []
            try:
                r_htx = await client.get(f"{origin}/api/v2/addresses/{addr}/transactions")
                if r_htx.status_code == 200:
                    for idx, tx in enumerate((r_htx.json() or {}).get("items") or []):
                        tr = _extract_blockscout_native_tx(tx, idx)
                        if tr is not None:
                            holder_trs.append(tr)
                    if holder_trs:
                        return holder_trs
            except Exception:  # noqa: BLE001
                pass
            try:
                r_v1 = await client.get(
                    f"{origin}/api",
                    params={"module": "account", "action": "txlist", "address": addr, "page": 1, "offset": 100, "sort": "desc"},
                )
                if r_v1.status_code == 200:
                    rows = (r_v1.json() or {}).get("result")
                    if isinstance(rows, list):
                        for idx, row in enumerate(rows):
                            frm = str(row.get("from") or "").lower()
                            to = str(row.get("to") or "").lower()
                            val = int(str(row.get("value") or "0").split(".")[0] or 0)
                            blk = int(row.get("blockNumber") or (idx + 1))
                            ts_val = int(row.get("timeStamp") or 0) or None
                            if frm and to and frm != to and val > 0:
                                holder_trs.append({
                                    "block": blk,
                                    "ts": ts_val,
                                    "tx": str(row.get("hash") or f"v1-nat-{idx}"),
                                    "log_index": int(row.get("transactionIndex") or idx),
                                    "from": frm,
                                    "to": to,
                                    "amount": val,
                                })
            except Exception:  # noqa: BLE001
                pass
            return holder_trs

        batch_size = 5
        for b_start in range(0, len(ranked_holders), batch_size):
            batch = ranked_holders[b_start : b_start + batch_size]
            batch_lists = await asyncio.gather(*(_fetch_holder_txs(a) for a in batch))
            for tr_list in batch_lists:
                for tr in tr_list:
                    k = (tr["tx"], tr["from"], tr["to"], tr["amount"])
                    if k not in seen_tx:
                        seen_tx.add(k)
                        transfers.append(tr)
            wallet_clusters.progress(
                "transfers",
                0.25 + 0.65 * min(len(ranked_holders), b_start + batch_size) / max(1, len(ranked_holders)),
            )

        if not transfers and balances_override:
            # Ensure top holders from `/accounts` still render even if recent tx list was empty
            now_ts = int(time.time())
            for idx, (addr, bal_val) in enumerate(balances_override.items()):
                transfers.append({
                    "block": 1,
                    "ts": now_ts,
                    "tx": f"genesis-{idx}",
                    "log_index": idx,
                    "from": "0x0000000000000000000000000000000000000000",
                    "to": addr,
                    "amount": bal_val,
                })

        if not transfers:
            raise RuntimeError(f"blockscout native {source}: no accounts or transfers returned")

        transfers.sort(key=lambda t: (t["block"], t["log_index"]))
        return _finalize_layer_build(
            token=token,
            symbol=symbol or "OCTA",
            transfers=transfers,
            supply=supply,
            balances_override=balances_override or None,
            source=source,
            block_s=block_s,
            out_chain=out_chain,
        )
    finally:
        if own:
            await client.aclose()


async def blockscout_native_new_sells(
    cfg: dict,
    origin: str = "https://scan.octa.space",
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Polls recent native coin transactions for watched Blockscout L1 wallets."""
    origin = origin.rstrip("/")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={"accept": "application/json"})
    wallets = list(cfg.get("wallets") or [])[:25]
    ws = set(wallets)
    out: list[dict] = []
    seen: set[tuple[str, str, str, int]] = set()
    try:
        for addr in wallets:
            if not str(addr).startswith("0x"):
                continue
            try:
                r = await client.get(f"{origin}/api/v2/addresses/{addr}/transactions")
                if r.status_code == 200:
                    for idx, tx in enumerate((r.json() or {}).get("items") or []):
                        tr = _extract_blockscout_native_tx(tx, idx)
                        if tr is not None and tr["from"] in ws:
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


# --- Shared cluster builder & sync_watch handoff ----------------------------

def _finalize_layer_build(
    token: str,
    symbol: str,
    transfers: list[dict],
    supply: int,
    balances_override: dict[str, int] | None,
    source: str,
    block_s: float = 2.0,
    out_chain: str = "layer",
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
    contracts = {
        a for a, peers in counterparties.items()
        if len(peers) >= 25 and a not in wallet_clusters.DEAD
    }

    wallet_clusters.progress("holders", 0.8)
    wallet_clusters.live(
        holders=[
            {"address": a, "share": round(v / supply, 5) if supply else None}
            for a, v in sorted(peak.items(), key=lambda x: -x[1])
            if a not in contracts and a not in wallet_clusters.DEAD
        ][:wallet_clusters.TOP_WATCH],
        counts={"holders": len(peak), "transfers": len(transfers)},
    )

    # Prepend synthetic opening balances from DEAD so `wallet_clusters.cluster()`
    # sees the true current balances of all top holders in `balances_override`
    # without introducing any false sender/transfer/buy links.
    cluster_transfers = transfers
    if balances_override:
        raw_bal, _ = wallet_clusters.balances(transfers)
        first_real_b = transfers[0]["block"] if transfers else 1
        first_real_ts = transfers[0].get("ts") if transfers else None
        dead_origin = "0x0000000000000000000000000000000000000000"
        opening = [
            {
                "block": max(0, first_real_b - 1),
                "ts": first_real_ts,
                "tx": f"open-{idx}",
                "log_index": idx,
                "from": dead_origin,
                "to": addr,
                "amount": target_bal - raw_bal.get(addr, 0),
            }
            for idx, (addr, target_bal) in enumerate(balances_override.items())
            if target_bal > raw_bal.get(addr, 0) and addr not in wallet_clusters.DEAD
        ]
        if opening:
            cluster_transfers = opening + transfers

    wallet_clusters.progress("clusters", None)
    res = wallet_clusters.cluster(cluster_transfers, contracts, supply, block_s=block_s)
    if balances_override and supply > 0:
        for a, b in balances_override.items():
            if a in res["shares"] or a in res["top"]:
                res["shares"][a] = round(max(0, b) / supply, 6)

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
        chain=out_chain,
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

    write_text_atomic(wallet_clusters._dir() / f"{wallet_clusters._key(out_chain, token)}.json", json.dumps(res))

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
        if out_chain in sync_watch.CHAINS:
            cfg = sync_watch.save({
                "chain": out_chain,
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
            out_chain,
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


async def build(token: str, symbol: str = "", created_at: float | None = None, client: httpx.AsyncClient | None = None, out_chain: str = "layer") -> dict:
    """Main entry point called by `wallet_clusters.build('layer', ...)`."""
    custom_url = get_custom_url(out_chain, token) or (token if str(token).startswith(("http://", "https://")) else "")
    if custom_url:
        return await build_from_url(custom_url, out_chain=out_chain, token=token, symbol=symbol, client=client)
    norm_cid, norm_sym = resolve_layer_token(token, symbol)
    keep_token = (token or norm_cid).strip().lower()

    # 1. Kaspa (native BlockDAG REST API)
    if _is_kaspa(norm_cid, norm_sym):
        return await build_kaspa(keep_token, norm_sym or "KAS", client=client)

    # 2. Blockscout native L1 chains (e.g. OctaSpace https://scan.octa.space/accounts)
    if norm_cid in BLOCKSCOUT_NATIVE_CHAINS:
        bs_cfg = BLOCKSCOUT_NATIVE_CHAINS[norm_cid]
        return await build_blockscout_native(
            origin=bs_cfg["origin"],
            token=keep_token,
            symbol=norm_sym or bs_cfg["symbol"],
            block_s=float(bs_cfg.get("block_s") or 11.2),
            decimals=int(bs_cfg.get("decimals") or 18),
            out_chain=out_chain,
            client=client,
        )

    # 3. Injective & Cosmos-SDK L0/L1 chains: try native Cosmos LCD first,
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
            from app.trading.onchain import solana_clusters, wallet_clusters
            import json
            from app.atomic_write import write_text_atomic

            res = await solana_clusters.build(contract_addr)
            res.update(
                chain=out_chain,
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
            out_chain=out_chain,
        )

    raise RuntimeError(f"layer {keep_token}: no public transfer source answered")


# --- Custom link / Explorer URL analyzer (Lorenzo, 23/10) -------------------

_HOST_CHAIN_MAP: dict[str, str] = {
    "etherscan.io": "ethereum",
    "eth.blockscout.com": "ethereum",
    "arbiscan.io": "arbitrum",
    "arbitrum.blockscout.com": "arbitrum",
    "optimistic.etherscan.io": "optimism",
    "optimism.blockscout.com": "optimism",
    "basescan.org": "base",
    "base.blockscout.com": "base",
    "bscscan.com": "bsc",
    "polygonscan.com": "polygon",
    "polygon.blockscout.com": "polygon",
    "snowtrace.io": "avalanche",
    "avascan.info": "avalanche",
    "lineascan.build": "linea",
    "explorer.linea.build": "linea",
    "scrollscan.com": "scroll",
    "scroll.blockscout.com": "scroll",
    "blastscan.io": "blast",
    "blast.blockscout.com": "blast",
    "mantlescan.xyz": "mantle",
    "explorer.mantle.xyz": "mantle",
    "explorer.zksync.io": "zksync",
    "zksync.blockscout.com": "zksync",
    "celoscan.io": "celo",
    "celo.blockscout.com": "celo",
    "gnosisscan.io": "gnosis",
    "gnosis.blockscout.com": "gnosis",
    "ftmscan.com": "fantom",
}


def _custom_urls_file():
    from app.trading.onchain import storage
    return storage.data_file("cluster_custom_urls.json")


def set_custom_url(chain: str, token: str, url: str) -> None:
    """Stores a user-supplied explorer/DEX link for `(chain, token)` on the volume."""
    import json
    from app.atomic_write import write_text_atomic
    from app.trading.onchain import sync_watch

    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        raise ValueError("URL must start with https:// or http://")
    path = _custom_urls_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    k = f"{(chain or 'layer').lower()}:{sync_watch._n(token or '')}"
    data[k] = u[:500]
    write_text_atomic(path, json.dumps(data))


def get_custom_url(chain: str, token: str) -> str | None:
    import json
    from app.trading.onchain import sync_watch

    try:
        data = json.loads(_custom_urls_file().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            k = f"{(chain or 'layer').lower()}:{sync_watch._n(token or '')}"
            return data.get(k)
    except (OSError, ValueError):
        pass
    return None


def parse_explorer_url(url: str) -> dict:
    """Extracts `(chain, token, symbol, base_origin)` from an explorer or DEX URL."""
    from urllib.parse import urlparse
    import hashlib

    u = (url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Invalid URL")
    host = parsed.netloc.lower().split(":")[0]
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.startswith(("10.", "192.168.", "169.254.")):
        raise ValueError("Private URLs are not allowed")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path_q = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path

    # 1. Kaspa explorer
    if "kaspa.org" in host or "kas.fyi" in host:
        return {"chain": "layer", "token": "kas-kaspa", "symbol": "KAS", "origin": origin, "url": u}
    # 1b. OctaSpace Blockscout explorer (https://scan.octa.space/accounts)
    if "octa.space" in host:
        m_octa_tok = re.search(r"/(?:token|tokens)/(0x[0-9a-fA-F]{40})", parsed.path, re.IGNORECASE)
        if m_octa_tok:
            t_addr = m_octa_tok.group(1).lower()
            return {"chain": "layer", "token": t_addr, "symbol": t_addr[:6].upper(), "origin": origin, "url": u}
        return {
            "chain": "layer",
            "token": "octa-octaspace",
            "symbol": "OCTA",
            "origin": "https://scan.octa.space",
            "url": u,
            "native_accounts": True,
        }
    # 2. Injective explorer / Mintscan
    if "injective" in host or "mintscan.io/injective" in u.lower():
        return {"chain": "layer", "token": "inj-injective-protocol", "symbol": "INJ", "origin": origin, "url": u}
    for cid in COSMOS_CHAINS:
        short_c = cid.split("-")[0]
        if f"mintscan.io/{short_c}" in u.lower():
            return {"chain": "layer", "token": cid, "symbol": short_c.upper(), "origin": origin, "url": u}

    # 3. EVM 0x address in URL
    m_evm = re.search(r"0x[0-9a-fA-F]{40}", path_q)
    if m_evm:
        addr = m_evm.group(0).lower()
        mapped_chain = next((v for k, v in _HOST_CHAIN_MAP.items() if host == k or host.endswith("." + k)), "layer")
        return {"chain": mapped_chain, "token": addr, "symbol": addr[:6].upper(), "origin": origin, "url": u}

    # 4. Solana explorer / Solscan / Birdeye
    if any(k in host for k in ("solscan.io", "solana.com", "solana.fm", "birdeye.so")):
        m_sol = re.search(r"/([1-9A-HJ-NP-Za-km-z]{32,44})", parsed.path)
        if m_sol:
            mint = m_sol.group(1)
            return {"chain": "solana", "token": mint, "symbol": mint[:6], "origin": origin, "url": u}

    # 5. Generic URL slug (including Blockscout `/accounts` native coin pages)
    norm_path = parsed.path.rstrip("/").lower()
    is_native_accounts = norm_path.endswith("/accounts")
    slug = "url-" + hashlib.sha1(u.encode("utf-8")).hexdigest()[:12]
    host_parts = [p for p in host.split(".") if p not in ("scan", "explorer", "blockscout", "www", "io", "com", "org", "net", "xyz", "space")]
    sym_guess = (host_parts[0] if host_parts else host.split(".")[0])[:8].upper()
    return {
        "chain": "layer",
        "token": slug,
        "symbol": sym_guess,
        "origin": origin,
        "url": u,
        "native_accounts": is_native_accounts,
    }


async def _fetch_custom_explorer_transfers(origin: str, contract: str, client: httpx.AsyncClient) -> tuple[list[dict], dict[str, int], int, str]:
    """Queries any Blockscout v2 or Etherscan-compatible v1 explorer at `origin`."""
    from urllib.parse import urlparse
    host = urlparse(origin).netloc
    transfers: list[dict] = []
    holders_override: dict[str, int] = {}
    supply = 0

    # Try Blockscout v2 API first (`/api/v2/tokens/{contract}/transfers` & `/holders`)
    try:
        r_tok = await client.get(f"{origin}/api/v2/tokens/{contract}")
        if r_tok.status_code == 200:
            td = r_tok.json() or {}
            if td.get("total_supply"):
                supply = int(str(td["total_supply"]).split(".")[0] or 0)
        r_tr = await client.get(f"{origin}/api/v2/tokens/{contract}/transfers")
        if r_tr.status_code == 200:
            items = (r_tr.json() or {}).get("items") or []
            for idx, it in enumerate(items):
                frm = ((it.get("from") or {}).get("hash") or "").lower()
                to = ((it.get("to") or {}).get("hash") or "").lower()
                val = int(((it.get("total") or {}).get("value")) or 0)
                blk = int(it.get("block_number") or (idx + 1))
                ts_raw = it.get("timestamp")
                ts_val = None
                if isinstance(ts_raw, str):
                    try:
                        ts_val = int(datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp())
                    except ValueError:
                        pass
                if frm and to and val > 0:
                    transfers.append({
                        "block": blk,
                        "ts": ts_val,
                        "tx": str(it.get("tx_hash") or f"bs-{idx}"),
                        "log_index": int(it.get("log_index") or idx),
                        "from": frm,
                        "to": to,
                        "amount": val,
                    })
        r_h = await client.get(f"{origin}/api/v2/tokens/{contract}/holders")
        if r_h.status_code == 200:
            for it in (r_h.json() or {}).get("items") or []:
                addr = ((it.get("address") or {}).get("hash") or "").lower()
                val = int(it.get("value") or 0)
                if addr and val > 0:
                    holders_override[addr] = val
    except Exception:  # noqa: BLE001
        pass

    # Fallback: Etherscan / Blockscout v1 `?module=account&action=tokentx`
    if not transfers:
        try:
            r_v1 = await client.get(
                f"{origin}/api",
                params={"module": "account", "action": "tokentx", "contractaddress": contract, "page": 1, "offset": 2000, "sort": "asc"},
            )
            if r_v1.status_code == 200:
                rows = (r_v1.json() or {}).get("result")
                if isinstance(rows, list):
                    for idx, row in enumerate(rows):
                        frm = str(row.get("from") or "").lower()
                        to = str(row.get("to") or "").lower()
                        val = int(row.get("value") or 0)
                        blk = int(row.get("blockNumber") or (idx + 1))
                        ts_val = int(row.get("timeStamp") or 0) or None
                        if frm and to and val > 0:
                            transfers.append({
                                "block": blk,
                                "ts": ts_val,
                                "tx": str(row.get("hash") or f"v1-{idx}"),
                                "log_index": int(row.get("logIndex") or row.get("transactionIndex") or idx),
                                "from": frm,
                                "to": to,
                                "amount": val,
                            })
        except Exception:  # noqa: BLE001
            pass

    transfers.sort(key=lambda t: (t["block"], t["log_index"]))
    return transfers, holders_override, supply, host


async def build_from_url(
    url: str,
    out_chain: str = "layer",
    token: str = "",
    symbol: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Analyzes a user-supplied explorer, DexScreener, or GeckoTerminal link
    and saves the resulting cluster report under `(out_chain, token)`."""
    info = parse_explorer_url(url)
    keep_chain = (out_chain or info["chain"] or "layer").lower()
    keep_token = (token or info["token"]).strip()
    if keep_token.startswith("0x"):
        keep_token = keep_token.lower()
    keep_sym = (symbol or info["symbol"] or keep_token[:8]).upper()

    if info["token"] == "kas-kaspa":
        res = await build_kaspa(keep_token, keep_sym, client=client)
        return res
    if info["token"] in BLOCKSCOUT_NATIVE_CHAINS:
        bs_cfg = BLOCKSCOUT_NATIVE_CHAINS[info["token"]]
        return await build_blockscout_native(
            origin=bs_cfg["origin"],
            token=keep_token,
            symbol=symbol or bs_cfg["symbol"],
            block_s=float(bs_cfg.get("block_s") or 11.2),
            decimals=int(bs_cfg.get("decimals") or 18),
            out_chain=keep_chain,
            client=client,
        )
    if info.get("native_accounts"):
        return await build_blockscout_native(
            origin=info["origin"],
            token=keep_token,
            symbol=keep_sym,
            out_chain=keep_chain,
            client=client,
        )
    if info["token"] in COSMOS_CHAINS:
        cosmos_res = await build_cosmos(keep_token, keep_sym, COSMOS_CHAINS[info["token"]], client=client)
        if cosmos_res is not None:
            return cosmos_res

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20.0, follow_redirects=True)

    try:
        assert client is not None
        u_low = url.lower()
        target_chain = info["chain"]
        contract_addr = info["token"] if info["token"].startswith("0x") else ""

        # DexScreener link: resolve pair or token via DexScreener API
        if "dexscreener.com/" in u_low:
            parts = [p for p in urlparse_path(url) if p]
            if len(parts) >= 2:
                ds_chain, ds_id = parts[0].lower(), parts[1]
                r = await client.get(f"https://api.dexscreener.com/latest/dex/pairs/{ds_chain}/{ds_id}")
                pairs = (r.json() or {}).get("pairs") if r.status_code == 200 else None
                if not pairs:
                    r2 = await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{ds_id}")
                    pairs = (r2.json() or {}).get("pairs") if r2.status_code == 200 else None
                if pairs and isinstance(pairs, list):
                    p0 = pairs[0]
                    target_chain = str(p0.get("chainId") or ds_chain).lower()
                    base_tok = p0.get("baseToken") or {}
                    contract_addr = str(base_tok.get("address") or "").strip()
                    if base_tok.get("symbol") and not symbol:
                        keep_sym = str(base_tok["symbol"]).upper()

        # GeckoTerminal link: resolve pool or token via GeckoTerminal API
        elif "geckoterminal.com/" in u_low:
            parts = [p for p in urlparse_path(url) if p]
            if len(parts) >= 3 and parts[1] in ("pools", "tokens"):
                gt_net, gt_kind, gt_id = parts[0].lower(), parts[1], parts[2]
                target_chain = _PAPRIKA_PLATFORM_MAP.get(gt_net, gt_net)
                if gt_kind == "tokens":
                    contract_addr = gt_id
                else:
                    r = await client.get(f"https://api.geckoterminal.com/api/v2/networks/{gt_net}/pools/{gt_id}")
                    if r.status_code == 200:
                        rel = (((r.json() or {}).get("data") or {}).get("relationships") or {}).get("base_token") or {}
                        tid = str((rel.get("data") or {}).get("id") or "")
                        if "_" in tid:
                            contract_addr = tid.split("_", 1)[1]

        # If we still don't have a contract address, fetch the page and look for 0x...
        if not contract_addr and target_chain != "solana":
            r_page = await client.get(url)
            if r_page.status_code == 200:
                m0x = re.search(r"0x[0-9a-fA-F]{40}", r_page.text)
                if m0x:
                    contract_addr = m0x.group(0).lower()

        if target_chain == "solana" or (contract_addr and not contract_addr.startswith("0x") and len(contract_addr) >= 32):
            from app.trading.onchain import solana_clusters, wallet_clusters
            import json
            from app.atomic_write import write_text_atomic

            mint = contract_addr or info["token"]
            res = await solana_clusters.build(mint)
            res.update(
                chain=keep_chain,
                token=keep_token,
                symbol=keep_sym,
                built_at=int(time.time()),
                partial=True,
                transfers=res["coverage"]["transfers"],
            )
            res["coverage"]["rules"] = wallet_clusters.RULES
            wallet_clusters._dir().mkdir(parents=True, exist_ok=True)
            write_text_atomic(wallet_clusters._dir() / f"{wallet_clusters._key(keep_chain, keep_token)}.json", json.dumps(res))
            clusters = [
                {"id": c["id"], "wallets": c["wallets"], "links": c["links"], "edges": c["edges"]}
                for c in res["clusters"]
            ] + [{"id": "top", "wallets": res["top"], "links": ["top_holders"]}]
            rep = sync_sells.report(keep_chain, keep_token, [], clusters, ["pool"], int(res.get("supply") or 0), keep_sym, res.get("shares"))
            rep["coverage"] = res["coverage"]
            sync_sells.write_report(rep)
            return res

        if contract_addr and contract_addr.startswith("0x"):
            from app.trading.onchain import wallet_clusters
            transfers: list[dict] = []
            holders_override: dict[str, int] = {}
            supply = 0
            source = info["origin"]
            if target_chain in transfer_sources.SOURCES:
                try:
                    transfers, _partial, source = await transfer_sources.transfers(target_chain, contract_addr, client=client)
                except Exception:  # noqa: BLE001
                    transfers = []
            if not transfers:
                transfers, holders_override, supply, source = await _fetch_custom_explorer_transfers(
                    info["origin"], contract_addr, client
                )
            if transfers:
                calc_supply = sum(v for v in wallet_clusters.balances(transfers)[0].values() if v > 0)
                if holders_override:
                    calc_supply = max(calc_supply, sum(holders_override.values()))
                return _finalize_layer_build(
                    token=keep_token,
                    symbol=keep_sym,
                    transfers=transfers,
                    supply=max(supply, calc_supply, 1),
                    balances_override=holders_override or None,
                    source=source,
                    block_s=2.0,
                    out_chain=keep_chain,
                )

        # Fallback: try Blockscout native L1 accounts (`/api/v2/addresses`) at `info["origin"]`
        try:
            return await build_blockscout_native(
                origin=info["origin"],
                token=keep_token,
                symbol=keep_sym,
                out_chain=keep_chain,
                client=client,
            )
        except Exception:  # noqa: BLE001
            pass
    finally:
        if own_client and client is not None:
            await client.aclose()

    raise RuntimeError(f"link {url[:80]}: no public transfer data found at URL")


def urlparse_path(url: str) -> list[str]:
    from urllib.parse import urlparse
    return [p for p in urlparse(url).path.split("/") if p]


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
    elif norm_cid in BLOCKSCOUT_NATIVE_CHAINS:
        new_moves = await blockscout_native_new_sells(cfg, origin=BLOCKSCOUT_NATIVE_CHAINS[norm_cid]["origin"])
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
