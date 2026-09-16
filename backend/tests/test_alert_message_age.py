"""
Il messaggio di un alert deve dire QUANDO, non solo quanto.

Caso reale, INJUSDT daily: e' arrivata una notifica "Ingresso long rilevato /
Prezzo: 6.285" mentre il mercato stava a 5.42. Nessuno dei due numeri era
sbagliato — 6.285 era la chiusura del 14 settembre, quando il segnale si e'
formato, e la notifica e' arrivata il 16 dopo un -13,5%. Il messaggio pero'
mostrava solo quel prezzo, senza data: letto cosi' sembrava una strategia che
compra dentro una correzione, mentre era un ingresso nato PRIMA della
correzione e consegnato dopo.

Un segnale puo' legittimamente arrivare fino a _MAX_SIGNAL_AGE_BARS barre dopo
essersi formato (quella finestra esiste per non inondare di notifiche storiche
quando la deduplica perde lo stato — vedi il commento in alerts.py). Finche' e'
cosi', il messaggio deve rendere visibile il ritardo invece di nasconderlo.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import StrategySignal
from app.notify.alerts import format_signal_message

DAY = 86400


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp())


def _signal(ts: int, price: float) -> StrategySignal:
    return StrategySignal(time=ts, type="entry_long", price=price, label="Ingresso long rilevato")


def test_the_real_inj_case_shows_both_prices_and_the_delay():
    """Lo stesso alert di INJUSDT, com'era e come deve leggersi ora."""
    signal_ts = _ts("2026-09-14")
    now = _ts("2026-09-16")
    msg = format_signal_message(
        "INJUSDT", "1d", "Lorenzo (trend-follower)",
        _signal(signal_ts, 6.285), current_price=5.424, now=now,
    )
    assert "6.285" in msg
    assert "14 set" in msg
    # La candela del 14 chiude a mezzanotte del 15: il 16 e' chiusa da un
    # giorno, non da due. L'eta' si misura dalla chiusura, non dall'apertura.
    assert "chiusa un giorno fa" in msg
    # Il prezzo di adesso, e di quanto si e' mosso da allora.
    assert "5.424" in msg
    assert "-13.7%" in msg


def test_a_signal_born_now_does_not_repeat_the_same_price_twice():
    """Su un segnale appena nato il "prezzo ora" sarebbe rumore, non trasparenza."""
    bar_open = _ts("2026-09-15")
    now = bar_open + DAY + 60          # un minuto dopo la chiusura della candela
    msg = format_signal_message(
        "BTCUSDT", "1d", "Lorenzo (trend-follower)",
        _signal(bar_open, 100.0), current_price=100.02, now=now,
    )
    assert "Prezzo ora" not in msg
    assert "chiusa meno di un'ora fa" in msg


def test_the_age_is_measured_from_the_close_not_the_open():
    """Un alert spedito subito dopo la chiusura non deve annunciarsi vecchio.

    `signal.time` e' l'APERTURA della candela: misurando da li', un alert
    puntuale su un daily si sarebbe presentato come "un giorno fa" — vecchio
    di un giorno appena nato.
    """
    bar_open = _ts("2026-09-15")
    just_closed = bar_open + DAY + 60
    msg = format_signal_message("BTCUSDT", "1d", "S", _signal(bar_open, 100.0), now=just_closed)
    assert "chiusa meno di un'ora fa" in msg
    assert "giorni fa" not in msg


def test_an_intraday_signal_carries_the_hour_a_daily_one_does_not():
    """Su un 15m l'ora e' meta' dell'informazione; su un daily e' rumore."""
    ts = _ts("2026-09-16") + 9 * 3600
    now = ts + 1800
    intraday = format_signal_message("BTCUSDT", "15m", "S", _signal(ts, 100.0), now=now)
    daily = format_signal_message("BTCUSDT", "1d", "S", _signal(ts, 100.0), now=now)
    assert "09:00 UTC" in intraday
    assert "UTC" not in daily


def test_the_message_works_without_a_current_price():
    """L'alert di prova non ha una serie dietro: deve restare formattabile."""
    ts = _ts("2026-09-16")
    msg = format_signal_message("BTCUSDT", "1d", "S", _signal(ts, 100.0), now=ts)
    assert "Prezzo al segnale: 100" in msg
    assert "consulenza finanziaria" in msg


def test_a_price_that_moved_up_is_shown_with_a_plus_sign():
    ts = _ts("2026-09-14")
    now = ts + 2 * DAY
    msg = format_signal_message("BTCUSDT", "1d", "S", _signal(ts, 100.0),
                                current_price=110.0, now=now)
    assert "+10.0%" in msg
