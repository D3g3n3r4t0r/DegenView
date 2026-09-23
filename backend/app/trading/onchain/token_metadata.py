"""Decimali del token BASE — servono solo per una VENDITA on-chain (convertire
una quantita' posseduta, in unita' umane, nell'unita' raw che Jupiter/Uniswap
si aspettano come amount_in). Un acquisto non ne ha bisogno: si paga sempre
nello stabile di quote, i cui decimali sono noti e fissi (vedi
_ONCHAIN_QUOTE_DECIMALS in main.py).

Letti dal vero contratto/mint, mai indovinati: un decimals sbagliato manda un
multiplo o una frazione dell'importo voluto, non un errore leggibile — vedi
il commento su _run_onchain_auto_trade in main.py.

* Solana: la mint account SPL espone i decimali tramite `getTokenSupply`,
  che li ritorna gia' pronti in `value.decimals` (l'alternativa,
  `getAccountInfo` con `encoding=jsonParsed`, da' lo stesso dato ma richiede
  di scendere in `data.parsed.info.decimals` — stessa fonte, un campo in
  piu' da attraversare, nessun vantaggio).
* EVM (Robinhood Chain): `decimals()` e' lo standard ERC20 (selettore
  0x313ce567, uint8) — stesso schema eth_call di quotes.py/execution.py,
  nessuna libreria ABI necessaria per una funzione senza argomenti.

Cache in memoria (non su disco, non sulla WatchlistEntry): i decimali di un
token non cambiano mai, quindi vale la pena non richiederli ad ogni segnale,
ma non vale la pena persisterli — un riavvio del processo li rilegge una
volta, con lo stesso costo di una entry aggiunta oggi. Aggiungere il campo
alla WatchlistEntry avrebbe richiesto gestire la migrazione delle entry
vecchie (che non l'avrebbero mai avuto) per un guadagno che il riavvio da
solo non giustifica.
"""
from app.trading.onchain import rpc_client

_SELECTOR_DECIMALS = "0x313ce567"  # decimals()

_decimals_cache: dict[tuple[str, str], int] = {}


async def get_token_decimals(chain: str, token_address: str) -> int | None:
    """Decimali reali del token, o None se non ottenibili (RPC irraggiungibile,
    token/indirizzo strano, chain non supportata). None non e' 0: chi chiama
    deve trattarlo come "non lo so", mai come "salta la conversione"."""
    key = (chain, token_address)
    cached = _decimals_cache.get(key)
    if cached is not None:
        return cached

    try:
        if chain == "solana":
            decimals = await _solana_decimals(token_address)
        elif chain == "robinhood":
            decimals = await _robinhood_decimals(token_address)
        else:
            return None
    except Exception:
        # Trasporto, JSON-RPC applicativo, indirizzo non valido: qualunque
        # cosa vada storta, meglio "non lo so" (None, gestito da chi chiama
        # come "saltato") che propagare un'eccezione che affonderebbe l'intero
        # giro di segnali, o peggio dedurre un valore.
        return None

    if decimals is None:
        return None
    _decimals_cache[key] = decimals
    return decimals


async def _solana_decimals(mint_address: str) -> int | None:
    result = await rpc_client.call_rpc("solana", "getTokenSupply", [mint_address])
    value = result.get("value") if isinstance(result, dict) else None
    if not value or "decimals" not in value:
        return None
    return int(value["decimals"])


async def _robinhood_decimals(token_address: str) -> int | None:
    result = await rpc_client.call_rpc(
        "robinhood", "eth_call", [{"to": token_address, "data": _SELECTOR_DECIMALS}, "latest"]
    )
    if not result or result == "0x":
        return None
    return int(result, 16)
