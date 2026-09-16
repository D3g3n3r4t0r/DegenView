"""
Simulatore di alert: riproduce la storia barra per barra e stampa i messaggi
Telegram che sarebbero partiti, con quanto ritardo rispetto alla chiusura
della candela che li ha generati.

Perche' esiste
--------------
Su INJUSDT e' arrivato un alert "Ingresso long — Prezzo 6.285" due giorni
dopo la candela che lo aveva generato, quando il prezzo era gia' sceso del
13,5%. Lorenzo: "deve arrivare l'alert alla chiusura della candela del
timeframe considerato, non tre giorni dopo... e' importante che questa cosa
non accada con nessun alert".

Leggere il codice non basta a garantirlo: serve vedere, su storia vera e su
piu' ticker, a che ora sarebbe partito ogni singolo messaggio. Questo script
lo fa passando dalle funzioni VERE usate in produzione — `drop_unclosed_candle`,
`build_strategy_state`, `find_new_signals`, `format_signal_message` — non da
una loro imitazione: una simulazione che riscrive la logica non dimostra
niente sulla logica.

Come funziona
-------------
Per ogni ticker e ogni barra della finestra, il tempo simulato viene portato
un minuto dopo la chiusura di quella barra (il watcher gira ogni 60 secondi),
la serie viene tagliata a quel momento esattamente come farebbe il provider —
compresa la candela ancora in formazione — e si guarda cosa sarebbe stato
notificato. Il ritardo di ogni alert e' la distanza fra la chiusura della
candela del segnale e il momento in cui sarebbe stato spedito.

Uso
---
    .venv/bin/python -m tools.simulate_alerts                  # 10 ticker, 1d
    .venv/bin/python -m tools.simulate_alerts --interval 4h --bars 120
    .venv/bin/python -m tools.simulate_alerts --symbols BTCUSDT,INJUSDT
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.notify.alerts as alerts_mod
from app.analysis.strategies import build_strategy_state
from app.notify.alerts import find_new_signals, format_signal_message
from app.providers.mexc import MexcProvider
from app.timeframes import INTERVAL_SECONDS, drop_unclosed_candle

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "INJUSDT", "KASUSDT",
    "XRPUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "DOGEUSDT",
]
DEFAULT_STRATEGIES = ["Lorenzo (trend-follower)", "Gabriele (RSI+BB reversal)"]


@dataclass
class Fired:
    symbol: str
    strategy: str
    interval: str
    signal_time: int      # apertura della candela del segnale
    sent_at: int          # quando sarebbe partito il messaggio
    message: str

    @property
    def bar_close(self) -> int:
        return self.signal_time + INTERVAL_SECONDS[self.interval]

    @property
    def delay_s(self) -> int:
        """Ritardo rispetto alla CHIUSURA della candela del segnale."""
        return self.sent_at - self.bar_close


def _reset_alert_state() -> None:
    """Ogni ticker riparte da zero: lo stato di deduplica e' un file condiviso
    in produzione, e portarselo dietro fra due simulazioni falserebbe la
    seconda."""
    alerts_mod._seen.clear()
    alerts_mod._stats.clear()
    alerts_mod._armed.clear()
    alerts_mod._seeded_scopes.clear()


def _monkeypatch_clock(now_holder: dict) -> None:
    """Il tempo lo decide la simulazione, non l'orologio della macchina.

    `drop_unclosed_candle` e la finestra di freschezza in alerts.py leggono
    entrambe time.time(): senza questo, ogni barra del passato risulterebbe
    "vecchia" e non verrebbe mai notificata.
    """
    import app.analysis.strategies as strat_mod
    import app.timeframes as tf_mod

    fake = lambda: now_holder["now"]                      # noqa: E731
    for mod in (alerts_mod, tf_mod, strat_mod):
        # `strategies` ha iniziato a leggere l'orologio solo con la correzione
        # del ritardo: senza getattr, la stessa simulazione non potrebbe girare
        # sulla versione precedente — ed e' proprio il confronto fra le due che
        # serve a dimostrare che il difetto c'era e non c'e' piu'.
        clock = getattr(mod, "time", None)
        if clock is not None:
            clock.time = fake                             # type: ignore[assignment]


async def simulate_symbol(
    provider, symbol: str, interval: str, bars: int, strategies: list[str],
    now_holder: dict, on_close: bool,
) -> tuple[list[Fired], int]:
    full = await provider.fetch_ohlcv(symbol, interval, 1000)
    if full.empty or len(full) < 60:
        print(f"  {symbol}: storia insufficiente ({len(full)} candele), salto")
        return [], 0

    step = INTERVAL_SECONDS[interval]
    fired: list[Fired] = []
    window = full.tail(bars)
    checks = 0

    for bar_open in window.index:
        # Il watcher passa un minuto dopo la chiusura di questa candela.
        now_holder["now"] = int(bar_open.timestamp()) + step + 60
        checks += 1
        # Cio' che il provider restituirebbe in quel momento: tutte le candele
        # aperte fino ad allora, inclusa quella in formazione.
        visible = full[full.index <= datetime.fromtimestamp(now_holder["now"], tz=timezone.utc)]
        if len(visible) < 50:
            continue
        df = drop_unclosed_candle(visible, interval) if on_close else visible
        if df.empty:
            continue

        for strategy_name in strategies:
            state = build_strategy_state(strategy_name, df)
            fresh = find_new_signals(
                symbol, interval, state, frequency="every",
                entry_id=f"sim-{symbol}-{strategy_name}",
            )
            for sig in fresh:
                fired.append(Fired(
                    symbol=symbol, strategy=strategy_name, interval=interval,
                    signal_time=sig.time, sent_at=now_holder["now"],
                    message=format_signal_message(
                        symbol, interval, strategy_name, sig,
                        current_price=float(df["close"].iloc[-1]),
                        now=now_holder["now"],
                    ),
                ))
    return fired, checks


def _fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--bars", type=int, default=90, help="quante barre simulare per ticker")
    ap.add_argument("--show", type=int, default=6, help="quanti messaggi stampare per intero")
    ap.add_argument("--no-on-close", action="store_true",
                    help="simula le voci SENZA 'alla chiusura della candela'")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    on_close = not args.no_on_close
    now_holder = {"now": 0}
    _monkeypatch_clock(now_holder)

    provider = MexcProvider()
    print(f"Simulazione: {len(symbols)} ticker · {args.interval} · ultime {args.bars} barre "
          f"· on_close={'si' if on_close else 'no'}")
    print(f"Strategie: {', '.join(DEFAULT_STRATEGIES)}\n")

    all_fired: list[Fired] = []
    total_checks = 0
    for symbol in symbols:
        _reset_alert_state()
        try:
            fired, checks = await simulate_symbol(
                provider, symbol, args.interval, args.bars, DEFAULT_STRATEGIES,
                now_holder, on_close,
            )
        except Exception as exc:                      # noqa: BLE001
            print(f"  {symbol}: errore ({exc}), salto")
            continue
        total_checks += checks
        all_fired.extend(fired)
        late = [f for f in fired if f.delay_s > INTERVAL_SECONDS[args.interval]]
        flag = "  ⚠ IN RITARDO" if late else ""
        print(f"  {symbol}: {len(fired)} alert su {checks} controlli{flag}")

    if not all_fired:
        print("\nNessun alert generato — finestra troppo corta o nessun incrocio.")
        return 0

    step = INTERVAL_SECONDS[args.interval]
    late = [f for f in all_fired if f.delay_s > step]
    on_time = [f for f in all_fired if f.delay_s <= step]

    print("\n" + "=" * 72)
    print(f"ALERT TOTALI: {len(all_fired)}")
    print(f"  puntuali (entro una barra dalla chiusura): {len(on_time)}")
    print(f"  in ritardo (oltre una barra):              {len(late)}")
    if all_fired:
        worst = max(all_fired, key=lambda f: f.delay_s)
        print(f"  ritardo massimo: {worst.delay_s / 3600:.1f} ore "
              f"({worst.symbol}, {worst.strategy})")
    print("=" * 72)

    if late:
        print("\nALERT IN RITARDO — questi non devono esistere:")
        for f in late[:20]:
            print(f"  {f.symbol} {f.strategy}: candela chiusa {_fmt(f.bar_close)}, "
                  f"spedito {_fmt(f.sent_at)} (+{f.delay_s / 3600:.1f}h)")

    print(f"\nPRIMI {args.show} MESSAGGI, come arriverebbero su Telegram:")
    for f in all_fired[:args.show]:
        body = f.message
        for tag in ("<b>", "</b>", "<i>", "</i>"):
            body = body.replace(tag, "")
        print("\n" + "-" * 72)
        print(f"[spedito {_fmt(f.sent_at)} · candela chiusa {_fmt(f.bar_close)} "
              f"· ritardo {f.delay_s / 60:.0f} min]")
        print(body)

    return 1 if late else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
