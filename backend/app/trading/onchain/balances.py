"""Saldo di un wallet on-chain, sola lettura via RPC pubblico — nessuna
chiave coinvolta qui, solo l'indirizzo (che e' pubblico per definizione)."""
import httpx

from app.models import OnchainChain

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
ROBINHOOD_RPC = "https://rpc.mainnet.chain.robinhood.com"
LAMPORTS_PER_SOL = 1_000_000_000
WEI_PER_ETH = 10**18


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
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(SOLANA_RPC, json=payload)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC Solana: {data['error']}")
    return data["result"]["value"] / LAMPORTS_PER_SOL


async def _robinhood_balance(address: str) -> float:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [address, "latest"]}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(ROBINHOOD_RPC, json=payload)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC Robinhood Chain: {data['error']}")
    return int(data["result"], 16) / WEI_PER_ETH
