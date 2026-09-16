from app.models import StrategySignal
from app.trading.audit import log_order
from app.trading.circuit_breaker import check_halt
from app.trading import (
    binance_exec,
    bitstamp_exec,
    coinbase_exec,
    kraken_exec,
    kucoin_exec,
)
from app.trading.futures import registry as futures_registry
from app.trading.futures.base import FuturesCreds

SUPPORTED_EXCHANGES = {"binance", "mexc", "kucoin", "kraken", "coinbase", "bitstamp"}

# Quali exchange fanno futures non si decide piu' qui: lo dice il registro
# degli adattatori, che e' anche l'unico posto dove si aggiunge il prossimo.
SUPPORTED_FUTURES_EXCHANGES = set(futures_registry.SUPPORTED_FUTURES_EXCHANGES)


async def place_futures_order_for_signal(
    exchange: str,
    symbol: str,
    signal: StrategySignal,
    size_mode: str,
    size_value: float,
    leverage: int,
    api_key: str,
    api_secret: str,
    passphrase: str = "",
    max_usdt: float | None = None,
) -> dict:
    """Separato da place_order_for_signal() apposta: mai un parametro
    is_futures su quella funzione, per lo stesso principio di isolamento
    dal codice spot che vale in tutto il resto del piano.

    A differenza dello spot, uno short qui e' una posizione vera: un
    exit_short deve RICOMPRARE per chiuderla, non e' un noop. E per lo
    stesso motivo un flip non puo' limitarsi ad aprire nella nuova
    direzione — deve prima chiudere quello che c'e' gia' aperto, o si
    finirebbe con l'esposizione raddoppiata invece che ribaltata.

    Il nome dell'exchange non compare piu' in questa funzione: la logica dei
    segnali e' la stessa per tutti, e le differenze fra piattaforme vivono
    dentro l'adattatore. Aggiungere un exchange non tocca questo file."""
    allowed, reason = check_halt()
    if not allowed:
        result = {"skipped": True, "reason": reason}
        log_order("skip", exchange, symbol, signal.type, result, is_futures=True)
        return result

    adapter = futures_registry.get(exchange)
    creds = FuturesCreds(api_key=api_key, api_secret=api_secret, passphrase=passphrase)

    t = signal.type
    if t in ("exit_long", "exit_short"):
        result = await adapter.close_position(symbol, creds)
        result = result or {"skipped": True, "reason": "nessuna posizione aperta da chiudere"}
        log_order("submit", exchange, symbol, t, result, is_futures=True)
        return result
    if t in ("flip_to_long", "flip_to_short"):
        await adapter.close_position(symbol, creds)
        side = "BUY" if t == "flip_to_long" else "SELL"
        result = await adapter.place_order(symbol, side, size_mode, size_value, leverage, creds, max_usdt=max_usdt)
        log_order("submit", exchange, symbol, t, result, is_futures=True)
        return result
    if t == "entry_long":
        result = await adapter.place_order(symbol, "BUY", size_mode, size_value, leverage, creds, max_usdt=max_usdt)
        log_order("submit", exchange, symbol, t, result, is_futures=True)
        return result
    if t == "entry_short":
        result = await adapter.place_order(symbol, "SELL", size_mode, size_value, leverage, creds, max_usdt=max_usdt)
        log_order("submit", exchange, symbol, t, result, is_futures=True)
        return result
    result = {"skipped": True, "reason": "no-op signal type"}
    log_order("skip", exchange, symbol, t, result, is_futures=True)
    return result


async def place_order_for_signal(
    exchange: str,
    symbol: str,
    signal: StrategySignal,
    size_mode: str,
    size_value: float,
    api_key: str,
    api_secret: str,
    passphrase: str = "",
    max_usdt: float | None = None,
) -> dict:
    """Map signal type to BUY/SELL and call the right exchange executor.

    max_usdt e' un tetto per singolo ordine, applicato SOLO lato BUY (aprire
    una posizione) da ciascun esecutore — mai lato SELL: un SELL qui puo'
    essere sia "entry_short" sintetico (vendi tutto, vai in cassa) sia un
    vero exit_long, e i due condividono lo stesso side senza modo di
    distinguerli da qui. Limitare un SELL vorrebbe dire lasciare aperta
    meta' di una posizione che si voleva chiudere per intero."""
    allowed, reason = check_halt()
    if not allowed:
        result = {"skipped": True, "reason": reason}
        log_order("skip", exchange, symbol, signal.type, result)
        return result

    side = _signal_to_side(signal.type)
    if side is None:
        result = {"skipped": True, "reason": "no-op signal type"}
        log_order("skip", exchange, symbol, signal.type, result)
        return result

    if exchange in ("binance", "mexc"):
        result = await binance_exec.place_order(
            exchange, symbol, side, size_mode, size_value, api_key, api_secret, max_usdt=max_usdt
        )
    elif exchange == "kucoin":
        kucoin_symbol = _to_kucoin_symbol(symbol)
        kucoin_side = side.lower()
        result = await kucoin_exec.place_order(
            kucoin_symbol, kucoin_side, size_mode, size_value, api_key, api_secret, passphrase, max_usdt=max_usdt
        )
    elif exchange == "kraken":
        result = await kraken_exec.place_order(symbol, side, size_mode, size_value, api_key, api_secret, max_usdt=max_usdt)
    elif exchange == "coinbase":
        result = await coinbase_exec.place_order(symbol, side, size_mode, size_value, api_key, api_secret, max_usdt=max_usdt)
    elif exchange == "bitstamp":
        result = await bitstamp_exec.place_order(symbol, side, size_mode, size_value, api_key, api_secret, max_usdt=max_usdt)
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")
    log_order("submit", exchange, symbol, signal.type, result)
    return result


def _signal_to_side(signal_type: str) -> str | None:
    """Map strategy signal type to BUY/SELL. Returns None for noop signals."""
    if signal_type in ("entry_long", "flip_to_long"):
        return "BUY"
    if signal_type in ("entry_short", "flip_to_short", "exit_long"):
        return "SELL"
    # exit_short on spot = already in USDT, noop
    return None


def _to_kucoin_symbol(symbol: str) -> str:
    """BTCUSDT → BTC-USDT, ETHBTC → ETH-BTC"""
    for quote in ("USDT", "BTC", "ETH", "USDC"):
        if symbol.endswith(quote):
            return symbol[: -len(quote)] + "-" + quote
    return symbol
