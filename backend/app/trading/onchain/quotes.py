"""Preventivo di uno swap PRIMA di firmare qualunque cosa — mai un ordine
mandato al buio. Jupiter (Solana) da' il price impact gia' calcolato;
Uniswap v2 su Robinhood Chain non ha un endpoint pubblico equivalente
(niente aggregator ufficiale ancora per una chain cosi' nuova, vedi il
piano), quindi lo si ricava dalle riserve del pool via RPC — la stessa
formula a prodotto costante (x*y=k) di ogni pool Uniswap v2.
"""
import httpx

JUPITER_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
ROBINHOOD_RPC = "https://rpc.mainnet.chain.robinhood.com"

# Selettori delle funzioni ERC20/Uniswap v2 Pair usate qui — calcolati una
# volta con keccak256(firma)[:4], non richiedono una libreria ABI in piu'
# per una chiamata a due soli metodi, entrambi senza argomenti.
_SELECTOR_GET_RESERVES = "0x0902f1ac"  # getReserves()
_SELECTOR_TOKEN0 = "0x0dfe1681"        # token0()


async def jupiter_quote(input_mint: str, output_mint: str, amount_lamports: int, slippage_bps: int = 50) -> dict:
    """Quote reale via Jupiter — nessuna chiave richiesta. price_impact_pct
    e' quello che risk.check_price_impact() confronta con la soglia."""
    params = {
        "inputMint": input_mint, "outputMint": output_mint,
        "amount": amount_lamports, "slippageBps": slippage_bps,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(JUPITER_QUOTE_URL, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"Jupiter ha risposto {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Jupiter: {data['error']}")
    return {
        "in_amount": int(data["inAmount"]),
        "out_amount": int(data["outAmount"]),
        "price_impact_pct": float(data["priceImpactPct"]) * 100,
        "raw": data,
    }


async def _eth_call(to: str, data: str) -> str:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": to, "data": data}, "latest"]}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(ROBINHOOD_RPC, json=payload)
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"RPC Robinhood Chain: {body['error']}")
    return body["result"]


async def uniswap_v2_price_impact(pool_address: str, token_in: str, amount_in: int) -> dict:
    """Stima il price impact di un buy/sell su un pool Uniswap v2 leggendo
    le riserve vere via RPC e applicando x*y=k — nessuna libreria ABI,
    solo due chiamate eth_call e la matematica del pool.

    ATTENZIONE: non ancora verificata contro un pool reale su Robinhood
    Chain (nessun indirizzo di pool noto in questa sessione) — la logica
    e' testata con RPC finto, la formula e' quella pubblica di ogni pool
    Uniswap v2, ma un giro dal vivo resta da fare prima di fidarsene con
    fondi veri."""
    reserves_hex = await _eth_call(pool_address, _SELECTOR_GET_RESERVES)
    token0_hex = await _eth_call(pool_address, _SELECTOR_TOKEN0)
    # getReserves() ritorna (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast),
    # ognuno un parola da 32 byte concatenata nell'output esadecimale.
    raw = reserves_hex[2:] if reserves_hex.startswith("0x") else reserves_hex
    reserve0 = int(raw[0:64], 16)
    reserve1 = int(raw[64:128], 16)
    token0 = "0x" + token0_hex[-40:]

    reserve_in, reserve_out = (reserve0, reserve1) if token_in.lower() == token0.lower() else (reserve1, reserve0)
    if reserve_in <= 0 or reserve_out <= 0:
        raise RuntimeError("Pool senza liquidita' — riserve a zero")

    # x*y=k, senza commissione (0.3% Uniswap v2 ignorata: sovrastima leggera
    # dell'impatto, mai una sottostima — l'errore va nella direzione sicura).
    amount_out = (amount_in * reserve_out) // (reserve_in + amount_in)
    spot_price = reserve_out / reserve_in
    exec_price = amount_out / amount_in if amount_in else 0
    price_impact_pct = abs(1 - (exec_price / spot_price)) * 100 if spot_price else 100.0
    return {"amount_out": amount_out, "price_impact_pct": price_impact_pct}
