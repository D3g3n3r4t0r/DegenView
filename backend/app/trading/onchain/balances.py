"""Saldo e storico transazioni di un wallet on-chain, sola lettura —
nessuna chiave coinvolta qui, solo l'indirizzo (che e' pubblico per
definizione)."""
import httpx

from app.models import OnchainChain
from app.trading.onchain import rpc_client

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
ROBINHOOD_RPC = "https://rpc.mainnet.chain.robinhood.com"
# L'explorer ufficiale (Blockscout) e' dietro una sfida Cloudflare che una
# richiesta da server non supera — verificato dal vivo, non solo letto:
# risponde "Just a moment..." a qualunque User-Agent, anche il path legacy
# /api?module=... in stile Etherscan. Un vero browser la risolve da solo
# (esegue il JS della sfida), un backend no — per questo lo storico
# Robinhood Chain qui sotto e' un link all'explorer, non dati incorporati.
ROBINHOOD_EXPLORER = "https://robinhoodchain.blockscout.com"
LAMPORTS_PER_SOL = 1_000_000_000
WEI_PER_ETH = 10**18
_MAX_TRANSACTIONS = 20


async def native_balance(chain: OnchainChain, address: str) -> float:
    """Saldo nella moneta nativa della chain (SOL, ETH) — non e' un saldo
    in stablecoin: e' quello che serve per pagare il gas, la prima cosa da
    controllare prima che qualunque swap automatico possa mai partire."""
    if chain == "solana":
        return await _solana_balance(address)
    if chain == "robinhood":
        return await _robinhood_balance(address)
    raise ValueError(f"Chain non supportata: {chain}")


async def _solana_balance(address: str) -> float:
    # Passa dal rpc_client (fallback multi-endpoint + circuit breaker): e'
    # la chiamata piu' frequente di tutto il sistema on-chain (saldo,
    # /admin/status, ogni apertura wallet).
    result = await rpc_client.call_rpc("solana", "getBalance", [address])
    return result["value"] / LAMPORTS_PER_SOL


async def _robinhood_balance(address: str) -> float:
    result = await rpc_client.call_rpc("robinhood", "eth_getBalance", [address, "latest"])
    return int(result, 16) / WEI_PER_ETH


async def recent_transactions(chain: OnchainChain, address: str) -> dict:
    """Le ultime transazioni per un indirizzo. Su Solana e' un dato vero
    (l'RPC pubblico lo offre nativamente); su Robinhood Chain e' un link
    all'explorer con la spiegazione del perche' — vedi il commento sopra
    ROBINHOOD_EXPLORER. Meglio dirlo chiaro che restituire una lista vuota
    che sembra "nessuna transazione" quando in realta' e' "non raggiungibile
    da qui"."""
    if chain == "solana":
        return {"available": True, "transactions": await _solana_transactions(address)}
    if chain == "robinhood":
        return {
            "available": False,
            "transactions": [],
            "explorer_url": f"{ROBINHOOD_EXPLORER}/address/{address}",
            "reason": "L'explorer di Robinhood Chain e' protetto da una verifica anti-bot che una "
                      "richiesta dal server non supera — apri il link per vedere lo storico vero.",
        }
    raise ValueError(f"Chain non supportata: {chain}")


async def _solana_transactions(address: str) -> list[dict]:
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
        "params": [address, {"limit": _MAX_TRANSACTIONS}],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(SOLANA_RPC, json=payload)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC Solana: {data['error']}")
    return [
        {
            "signature": row["signature"],
            "block_time": row.get("blockTime"),
            "status": "fallita" if row.get("err") else "riuscita",
            "explorer_url": f"https://explorer.solana.com/tx/{row['signature']}",
        }
        for row in (data.get("result") or [])
    ]
