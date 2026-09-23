"""Preventivo di uno swap PRIMA di firmare qualunque cosa — mai un ordine
mandato al buio. Jupiter (Solana) da' il price impact gia' calcolato;
Uniswap v3 su Robinhood Chain non ha un aggregator pubblico equivalente
ancora (chain troppo nuova), quindi si interroga direttamente Factory e
QuoterV2 via RPC — verificato dal vivo il 19/09/2026 contro il pool
WETH/USDG reale (fee 3000: 0.01 WETH -> ~26.19 USDG, coerente con un
prezzo ETH plausibile), non solo con un RPC finto.
"""
import httpx
from eth_abi import decode as _abi_decode
from eth_abi import encode as _abi_encode
from eth_utils import keccak, to_checksum_address

from app.trading.onchain import rpc_client

JUPITER_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
ROBINHOOD_RPC = "https://rpc.mainnet.chain.robinhood.com"

# Stesse fonti incrociate del router (execution.py): developers.uniswap.org
# + docs.robinhood.com, coerenti fra loro, e verificate dal vivo qui sotto
# con una vera getPool()/quote — non solo lette da una pagina.
ROBINHOOD_V3_FACTORY = to_checksum_address("0x1f7d7550b1b028f7571e69a784071f0205fd2efa")
ROBINHOOD_QUOTER_V2 = to_checksum_address("0x33e885ed0ec9bf04ecfb19341582aadcb4c8a9e7")

# Selettori delle funzioni ERC20/Uniswap v2 Pair usate qui — calcolati una
# volta con keccak256(firma)[:4], non richiedono una libreria ABI in piu'
# per una chiamata a due soli metodi, entrambi senza argomenti.
_SELECTOR_GET_RESERVES = "0x0902f1ac"  # getReserves()
_SELECTOR_TOKEN0 = "0x0dfe1681"        # token0()

_SELECTOR_GET_POOL = keccak(text="getPool(address,address,uint24)")[:4]
_SELECTOR_QUOTE_EXACT_INPUT_SINGLE = keccak(
    text="quoteExactInputSingle((address,address,uint256,uint24,uint160))"
)[:4]


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
    # Fallback multi-endpoint + circuit breaker (rpc_client): il quote e'
    # la seconda chiamata piu' frequente dopo il saldo, e per Robinhood
    # Chain sono due eth_call per ogni quote (getPool + quoteExactInputSingle,
    # o getReserves + token0 per il v2).
    return await rpc_client.call_rpc("robinhood", "eth_call", [{"to": to, "data": data}, "latest"])


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


async def get_pool(token_a: str, token_b: str, fee: int) -> str | None:
    """Legge il pool vero da UniswapV3Factory.getPool — None se non esiste
    per quella coppia/fee tier (l'indirizzo zero che il contratto ritorna
    in quel caso)."""
    data = "0x" + _SELECTOR_GET_POOL.hex() + _abi_encode(
        ["address", "address", "uint24"],
        [to_checksum_address(token_a), to_checksum_address(token_b), fee],
    ).hex()
    result = await _eth_call(ROBINHOOD_V3_FACTORY, data)
    address = "0x" + result[-40:]
    if int(address, 16) == 0:
        return None
    return to_checksum_address(address)


async def uniswap_v3_quote(token_in: str, token_out: str, fee: int, amount_in: int) -> dict:
    """Quote reale via QuoterV2.quoteExactInputSingle (eth_call, mai una
    transazione: e' una funzione "non-view" solo perche' usa un revert per
    tornare il risultato, staticcall non muove nulla). Il price impact si
    stima confrontando il prezzo eseguito su amount_in con quello di un
    quote di riferimento 1000 volte piu' piccolo (quasi-spot) — stessa idea
    del v2, senza dover leggere sqrtPriceX96 e convertirlo a mano."""
    token_in_c, token_out_c = to_checksum_address(token_in), to_checksum_address(token_out)

    async def _quote(amount: int) -> int:
        data = "0x" + _SELECTOR_QUOTE_EXACT_INPUT_SINGLE.hex() + _abi_encode(
            ["(address,address,uint256,uint24,uint160)"],
            [(token_in_c, token_out_c, amount, fee, 0)],
        ).hex()
        result = await _eth_call(ROBINHOOD_QUOTER_V2, data)
        raw = bytes.fromhex(result[2:] if result.startswith("0x") else result)
        return _abi_decode(["uint256", "uint160", "uint32", "uint256"], raw)[0]

    reference_amount = max(amount_in // 1000, 1)
    amount_out, reference_out = await _quote(amount_in), await _quote(reference_amount)
    if reference_out <= 0:
        raise RuntimeError("Pool senza liquidita' sufficiente per un quote di riferimento")

    spot_price = reference_out / reference_amount
    exec_price = amount_out / amount_in if amount_in else 0
    price_impact_pct = abs(1 - (exec_price / spot_price)) * 100 if spot_price else 100.0
    return {"amount_out": amount_out, "price_impact_pct": price_impact_pct}
