import math
import time

import pandas as pd

from app.analysis.strategies import DEFAULT_STRATEGY, confirmed_events
from app.models import BacktestResult, BacktestTrade, StrategySignal

# Same defaults as the user's Pine Script header:
# strategy("Lorenzo", initial_capital=10000, default_qty_type=percent_of_equity,
#          commission_type=percent, commission_value=0.06, slippage=2, default_qty_value=30)
# Pine's slippage is in ticks, which has no single meaning across stocks/crypto
# of wildly different price scales — ported here as a percent-of-price instead.
# stop_loss_pct/take_profit_pct default to 0 (disabled) — signal-only exits,
# same behavior as before this was added. Set either > 0 to close a position
# the moment a bar's intrabar high/low crosses that level, independent of
# whatever the strategy's own exit signal says.
# fill_at dice *quando* si compra rispetto alla candela che ha generato il
# segnale, ed e' la differenza fra un backtest ottimista e uno realizzabile:
#
#   "signal_close" — si riempie alla chiusura della candela del segnale.
#       E' il comportamento storico di questo motore. Presuppone di poter
#       transare esattamente a quel prezzo, che pero' si conosce solo *nel
#       momento in cui* la candela chiude: nella pratica quel riempimento
#       non esiste, tranne che con un ordine a mercato sparato sul campanello.
#   "next_open"    — si riempie all'apertura della candela successiva.
#       E' cio' che si puo' davvero ottenere: il segnale e' confermato solo a
#       candela chiusa, e la prima occasione di eseguire e' la barra dopo.
#
#   "on_condition" — si riempie nel punto della candela in cui la condizione
#       diventa vera (segnalazione 316219de: prima riempiva alla chiusura come
#       "signal_close", quindi le due opzioni davano numeri identici). Il
#       backtest non vede dentro la candela: ripercorre il cammino che il
#       broker emulator di TradingView assume, apertura -> minimo -> massimo
#       -> chiusura su una candela verde, apertura -> massimo -> minimo ->
#       chiusura su una rossa, e a ogni passo ricalcola la strategia con la
#       candela "in formazione" fino a quel prezzo. Il primo passo in cui il
#       segnale c'e' e' il prezzo di riempimento. Solo per i segnali confermati
#       a chiusura: quelli che compaiono e poi spariscono prima della chiusura
#       (l'alert partirebbe comunque) non entrano nel backtest.
#
# Il default resta "signal_close" apposta: cambiarlo qui sposterebbe in
# silenzio ogni risultato storico gia' archiviato. Chi vuole il numero
# realizzabile lo chiede esplicitamente.
DEFAULT_BACKTEST_PARAMS = {
    "initial_capital": 10000.0,
    "qty_pct_of_equity": 30.0,
    "commission_pct": 0.06,
    "slippage_pct": 0.02,
    "stop_loss_pct": 0.0,
    "take_profit_pct": 0.0,
    "fill_at": "signal_close",
}

_ENTRY_TYPES = {"entry_long", "entry_short"}
_EXIT_TYPES = {"exit_long", "exit_short"}
_FLIP_TYPES = {"flip_to_long", "flip_to_short"}


# Passi per tratto del cammino dentro la candela, e quante barre di storia
# ricalcolare a ogni passo: il costo e' segnali x passi x ricalcolo.
INTRABAR_STEPS_PER_LEG = 4
INTRABAR_WINDOW = 300
# Tetto di tempo per tutto il ricalcolo: oltre, i segnali rimanenti si
# riempiono alla chiusura (e intrabar_fills lo dice). Il backtest del Lab
# non deve restare appeso su una serie con centinaia di segnali.
INTRABAR_BUDGET_S = 8.0

# Colonna del frame dei segnali che deve accendersi sull'ultima riga perche'
# l'evento confermato a chiusura sia gia' vero a meta' candela.
_EVENT_COLUMN = {
    "entry_long": "entry_long", "flip_to_long": "entry_long",
    "entry_short": "entry_short", "flip_to_short": "entry_short",
    "exit_long": "exit_long", "exit_short": "exit_short",
}


def intrabar_path(o: float, h: float, low: float, c: float,
                  steps: int = INTRABAR_STEPS_PER_LEG) -> list[tuple[float, float, float]]:
    """(price, running high, running low) along the assumed path inside one
    candle. Green: open -> low -> high -> close; red: open -> high -> low ->
    close. The last point is the real close, with the real high and low."""
    legs = [o, low, h, c] if c >= o else [o, h, low, c]
    out: list[tuple[float, float, float]] = []
    hi = lo = o
    for a, b in zip(legs, legs[1:]):
        for k in range(1, steps + 1):
            p = a + (b - a) * k / steps
            hi, lo = max(hi, p), min(lo, p)
            out.append((p, hi, lo))
    return out


def epoch_seconds(index) -> list[int]:
    """Unix seconds of a DatetimeIndex, vectorised and unit-safe (pandas may
    store ns or us). Same values as [int(ts.timestamp()) for ts in index]."""
    idx = pd.DatetimeIndex(index)
    epoch = pd.Timestamp(0, tz=idx.tz) if idx.tz is not None else pd.Timestamp(0)
    return ((idx - epoch) // pd.Timedelta(seconds=1)).tolist()


def intrabar_prices(df: pd.DataFrame, events: list[StrategySignal], params: dict | None,
                    compute_fn) -> dict[int, float]:
    """Signal time -> first price inside the signal candle at which the
    strategy already gives that signal. Events where the replay never finds
    it (e.g. a warm-up difference on the shorter window) are left out and
    fill at the close as before."""
    if not events or compute_fn is None:
        return {}
    pos_by_ts = {int(ts.timestamp()): i for i, ts in enumerate(df.index)}
    cols = {name: df.columns.get_loc(name) for name in ("high", "low", "close")}
    out: dict[int, float] = {}
    deadline = time.monotonic() + INTRABAR_BUDGET_S
    for ev in events:
        if time.monotonic() > deadline:
            break
        col = _EVENT_COLUMN.get(ev.type)
        i = pos_by_ts.get(ev.time)
        if col is None or i is None:
            continue
        window = df.iloc[max(0, i - INTRABAR_WINDOW + 1): i + 1].copy()
        window[["high", "low", "close"]] = window[["high", "low", "close"]].astype(float)
        bar = df.iloc[i]
        for price, hi, lo in intrabar_path(float(bar["open"]), float(bar["high"]),
                                           float(bar["low"]), float(bar["close"])):
            window.iloc[-1, cols["high"]] = hi
            window.iloc[-1, cols["low"]] = lo
            window.iloc[-1, cols["close"]] = price
            try:
                sig = compute_fn(window.copy(), params)
                hit = bool(sig[col].iloc[-1])
            except Exception:  # noqa: BLE001 - a replay failure only loses the early fill
                break
            if hit:
                out[ev.time] = price
                break
    return out


def _fill_price(price: float, pct: float, side: str) -> float:
    # side "buy" fills worse (higher); "sell" fills worse (lower).
    return price * (1 + pct / 100) if side == "buy" else price * (1 - pct / 100)


def run_backtest(
    df: pd.DataFrame,
    strategy_params: dict | None,
    backtest_params: dict | None,
    signals: pd.DataFrame | None = None,
    strategy_name: str = DEFAULT_STRATEGY,
    intrabar_fn=None,
) -> BacktestResult:
    """`intrabar_fn(df, params) -> signals frame` turns on the in-candle
    replay of fill_at "on_condition" (see intrabar_prices). Opt-in on
    purpose: the optimisers run thousands of backtests and keep filling at
    the close, so no stored or optimised number moves."""
    bp = {**DEFAULT_BACKTEST_PARAMS, **(backtest_params or {})}
    events, _final_position = confirmed_events(df, strategy_params, signals=signals, strategy_name=strategy_name)
    event_by_ts: dict[int, StrategySignal] = {s.time: s for s in events}
    intrabar_by_ts: dict[int, float] = {}
    if bp.get("fill_at") == "on_condition" and intrabar_fn is not None:
        intrabar_by_ts = intrabar_prices(df, events, strategy_params, intrabar_fn)

    equity = bp["initial_capital"]
    peak_equity = equity
    max_drawdown_pct = 0.0
    trades: list[BacktestTrade] = []
    equity_curve: list[tuple[int, float]] = [(int(df.index[0].timestamp()), equity)]

    # Apertura della barra successiva, per il riempimento realizzabile.
    # Costruita una volta sola: cercarla dentro il ciclo sarebbe una scansione
    # per ogni segnale.
    next_open_by_ts: dict[int, float] = {}
    if bp.get("fill_at") == "next_open":
        timestamps = epoch_seconds(df.index)
        opens = df["open"].tolist()
        for idx in range(len(timestamps) - 1):
            next_open_by_ts[timestamps[idx]] = float(opens[idx + 1])

    open_trade: dict | None = None  # {direction, entry_time, entry_price}

    def _signal_fill_price(signal: StrategySignal) -> float | None:
        """Prezzo grezzo a cui si considera eseguito questo segnale.

        Con "next_open" un segnale sull'ultima candela disponibile non ha
        una barra successiva su cui riempire: quel trade non e' eseguibile e
        va scartato, non riempito al prezzo di chiusura come ripiego."""
        if bp.get("fill_at") == "on_condition":
            return intrabar_by_ts.get(signal.time, signal.price)
        if bp.get("fill_at") != "next_open":
            return signal.price
        return next_open_by_ts.get(signal.time)

    def _open(direction: str, signal: StrategySignal) -> None:
        nonlocal open_trade
        raw = _signal_fill_price(signal)
        if raw is None:
            return
        fill = _fill_price(raw, bp["slippage_pct"], "buy" if direction == "long" else "sell")
        open_trade = {"direction": direction, "entry_time": signal.time, "entry_price": fill}

    def _close_at(raw_price: float, time: int) -> None:
        nonlocal equity, peak_equity, max_drawdown_pct, open_trade
        if open_trade is None:
            return
        direction = open_trade["direction"]
        exit_fill = _fill_price(raw_price, bp["slippage_pct"], "sell" if direction == "long" else "buy")
        entry_fill = open_trade["entry_price"]

        raw_return = (exit_fill - entry_fill) / entry_fill
        if direction == "short":
            raw_return = -raw_return

        notional = equity * (bp["qty_pct_of_equity"] / 100)
        commission = notional * (bp["commission_pct"] / 100) * 2  # entry + exit
        pnl_abs = notional * raw_return - commission
        equity += pnl_abs
        peak_equity = max(peak_equity, equity)
        drawdown_pct = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        trades.append(
            BacktestTrade(
                direction=direction,
                entry_time=open_trade["entry_time"],
                exit_time=time,
                entry_price=entry_fill,
                exit_price=exit_fill,
                pnl_pct=raw_return * 100,
                pnl_abs=pnl_abs,
                equity_after=equity,
            )
        )
        equity_curve.append((time, equity))
        open_trade = None

    stop_pct = bp["stop_loss_pct"]
    target_pct = bp["take_profit_pct"]
    stop_loss_enabled = stop_pct > 0 or target_pct > 0

    # Plain arrays instead of df.iterrows(): the loop is the same, bar by bar,
    # but without building a Series per row (overhaul plan, week 2; checked
    # against the previous implementation by tests/test_engine_equivalence.py).
    stamps = epoch_seconds(df.index)
    lows = df["low"].to_numpy()
    highs = df["high"].to_numpy()
    for i, t in enumerate(stamps):
        row = {"low": lows[i], "high": highs[i]}

        # Intrabar stop/target check happens before this bar's own signal —
        # a position can be stopped out on a bar between two strategy
        # signals, using the bar's actual high/low, not just its close.
        if stop_loss_enabled and open_trade is not None:
            direction = open_trade["direction"]
            entry = open_trade["entry_price"]
            if direction == "long":
                stop_level = entry * (1 - stop_pct / 100) if stop_pct > 0 else None
                target_level = entry * (1 + target_pct / 100) if target_pct > 0 else None
                stop_hit = stop_level is not None and row["low"] <= stop_level
                target_hit = target_level is not None and row["high"] >= target_level
            else:
                stop_level = entry * (1 + stop_pct / 100) if stop_pct > 0 else None
                target_level = entry * (1 - target_pct / 100) if target_pct > 0 else None
                stop_hit = stop_level is not None and row["high"] >= stop_level
                target_hit = target_level is not None and row["low"] <= target_level
            if stop_hit:
                _close_at(stop_level, t)
                continue
            if target_hit:
                _close_at(target_level, t)
                continue

        signal = event_by_ts.get(t)
        if signal is None:
            continue
        # L'uscita segue la stessa regola dell'ingresso: se l'ingresso non e'
        # eseguibile alla chiusura del segnale, nemmeno l'uscita lo e'.
        # Un'uscita senza barra successiva resta aperta, e viene chiusa dal
        # riepilogo di fine serie come qualunque altra posizione ancora viva.
        exit_raw = _signal_fill_price(signal)
        if signal.type in _ENTRY_TYPES:
            _open("long" if signal.type == "entry_long" else "short", signal)
        elif signal.type in _EXIT_TYPES:
            if exit_raw is not None:
                _close_at(exit_raw, signal.time)
        elif signal.type in _FLIP_TYPES:
            if exit_raw is not None:
                _close_at(exit_raw, signal.time)
            _open("long" if signal.type == "flip_to_long" else "short", signal)

    wins = [t for t in trades if t.pnl_abs > 0]
    losses = [t for t in trades if t.pnl_abs <= 0]
    gross_profit = sum(t.pnl_abs for t in wins)
    gross_loss = -sum(t.pnl_abs for t in losses)

    # data_start / data_end: unix milliseconds of first and last candle
    data_start = int(df.index[0].timestamp() * 1000)
    data_end = int(df.index[-1].timestamp() * 1000)

    # Sharpe ratio from daily equity-curve returns
    sharpe_ratio: float | None = None
    if len(equity_curve) >= 3:
        eq_values = [v for _, v in equity_curve]
        daily_returns = [(eq_values[i] - eq_values[i - 1]) / eq_values[i - 1] for i in range(1, len(eq_values))]
        mean_r = sum(daily_returns) / len(daily_returns)
        var_r = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
        std_r = math.sqrt(var_r)
        if std_r > 0:
            sharpe_ratio = (mean_r / std_r) * math.sqrt(252)

    # max_consecutive_losses
    max_consec_losses: int | None = None
    if trades:
        max_consec_losses = 0
        current = 0
        for t in trades:
            if t.pnl_pct < 0:
                current += 1
                max_consec_losses = max(max_consec_losses, current)
            else:
                current = 0

    return BacktestResult(
        interval="",  # caller (app.main) fills in the interval the df it passed actually was
        # Dichiarato nel risultato: chi legge il rendimento deve poter sapere a
        # che prezzo si e' entrati senza risalire alla richiesta.
        fill_at=str(bp.get("fill_at", "signal_close")),
        intrabar_fills=len(intrabar_by_ts) if intrabar_fn is not None and bp.get("fill_at") == "on_condition" else None,
        initial_capital=bp["initial_capital"],
        final_equity=equity,
        total_return_pct=(equity - bp["initial_capital"]) / bp["initial_capital"] * 100,
        num_trades=len(trades),
        win_rate_pct=(len(wins) / len(trades) * 100) if trades else None,
        max_drawdown_pct=max_drawdown_pct,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else None,
        equity_curve=equity_curve,
        trades=trades,
        data_start=data_start,
        data_end=data_end,
        sharpe_ratio=sharpe_ratio,
        max_consecutive_losses=max_consec_losses,
    )
