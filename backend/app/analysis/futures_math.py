"""Formula di liquidazione condivisa fra il backtest futures e l'esecuzione
reale: una sola versione, non due copie che rischiano di divergere — vedi il
piano "Operazioni futures". Margine isolated soltanto, come fissato ovunque
nel modello dati (FuturesCredential.margin_mode, MAX_FUTURES_LEVERAGE)."""

from __future__ import annotations

# Tasso di manutenzione margine prudente per fascia di leva bassa/media su
# un perpetuo USDT-M — fonte: tabella dei livelli di margine pubblicata da
# Binance per BTCUSDT-PERP
# (binance.com/it/futures/trading-rules/perpetual/leverage-margin). Non e'
# calibrato per simbolo: un default ragionevole, non un dato reale per ogni
# ticker — va sempre passato esplicitamente quando lo si conosce.
DEFAULT_MAINTENANCE_MARGIN_RATE = 0.005


def liquidation_price(entry: float, direction: str, leverage: int, maintenance_margin_rate: float) -> float:
    """Isolated margin, one-way position. direction: 'long' | 'short'."""
    if direction == "long":
        return entry * (1 - 1 / leverage + maintenance_margin_rate)
    return entry * (1 + 1 / leverage - maintenance_margin_rate)
