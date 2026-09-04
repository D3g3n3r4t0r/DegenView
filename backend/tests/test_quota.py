"""Quota del provider esaurita: un limite di piano, non un guasto.

È arrivato sulla bacheca come "⚠️ Errore monitoraggio BTC/USD [1d]: You have run
out of API credits for the day" — un messaggio allarmante, ripetuto per ticker
per minuto, per una cosa che non è rotta e che si risolve da sola a mezzanotte.
"""

from __future__ import annotations

import time

import pytest

from app.providers.base import ProviderError, QuotaExceeded
from app.providers.twelvedata import _is_quota_error, _seconds_to_utc_midnight


# --- riconoscere il caso --------------------------------------------------


def test_the_real_message_is_recognised():
    msg = ("You have run out of API credits for the day. 803 API credits were used, "
           "with the current limit being 800.")
    assert _is_quota_error(400, msg)


def test_the_http_code_alone_is_enough():
    assert _is_quota_error(429, "")


def test_an_ordinary_error_is_not_a_quota_error():
    """Altrimenti un ticker inesistente metterebbe in pausa tutto."""
    assert not _is_quota_error(400, "**symbol** not found: XYZ")


def test_a_quota_error_is_still_a_provider_error():
    """Chi cattura ProviderError continua a funzionare senza sapere del nuovo caso."""
    assert issubclass(QuotaExceeded, ProviderError)


def test_the_retry_moment_is_the_reset_not_a_minute_from_now():
    s = _seconds_to_utc_midnight()
    assert 60 <= s <= 86400


# --- la pausa -------------------------------------------------------------


@pytest.fixture()
def loop(monkeypatch):
    from app import main as mod

    # Anche la serie di fallimenti: senza, un test che l'ha gia' portata al
    # massimo fa partire il successivo da li' e l'attesa non puo' piu' crescere.
    # E' caduto cosi', nella suite completa e non da solo.
    mod._quota_pause_until.clear()
    mod._quota_notified.clear()
    mod._unreachable_streak.clear()
    return mod


def test_the_pause_stops_further_calls(loop):
    assert not loop._quota_paused("stock", "mexc")
    loop._pause_for_quota("stock", "mexc", QuotaExceeded("finiti", retry_after_s=600))
    assert loop._quota_paused("stock", "mexc")


def test_the_pause_is_shared_across_users_of_the_same_plan(loop):
    """La quota è del piano: fermare solo chi ha visto l'errore lascerebbe gli
    altri a consumarne altri e a ricevere lo stesso messaggio a turno."""
    loop._pause_for_quota("stock", "mexc", QuotaExceeded("finiti", retry_after_s=600))
    assert loop._quota_paused("stock", "binance"), "per i titoli l'exchange non c'entra"


def test_crypto_is_not_paused_by_a_stock_quota(loop):
    loop._pause_for_quota("stock", "mexc", QuotaExceeded("finiti", retry_after_s=600))
    assert not loop._quota_paused("crypto", "mexc")


def test_the_pause_expires(loop):
    loop._pause_for_quota("stock", "twelvedata", QuotaExceeded("finiti", retry_after_s=60))
    loop._quota_pause_until[loop._quota_key("stock", "twelvedata")] = time.time() - 1
    assert not loop._quota_paused("stock", "twelvedata")


def test_a_missing_retry_hint_still_pauses(loop):
    loop._pause_for_quota("stock", "x", QuotaExceeded("finiti"))
    assert loop._quota_paused("stock", "x")


# --- una notifica sola ----------------------------------------------------


def test_one_message_per_user_per_pause(loop):
    loop._pause_for_quota("stock", "x", QuotaExceeded("finiti", retry_after_s=600))
    assert loop._notify_quota_once("u1", "stock", "x") is True
    assert loop._notify_quota_once("u1", "stock", "x") is False, "un messaggio per ticker per minuto era il problema"


def test_each_user_is_told_once(loop):
    loop._pause_for_quota("stock", "x", QuotaExceeded("finiti", retry_after_s=600))
    assert loop._notify_quota_once("u1", "stock", "x") is True
    assert loop._notify_quota_once("u2", "stock", "x") is True


def test_a_new_pause_speaks_again(loop):
    """Il giorno dopo, se succede di nuovo, va detto di nuovo."""
    loop._pause_for_quota("stock", "x", QuotaExceeded("finiti", retry_after_s=1))
    loop._notify_quota_once("u1", "stock", "x")
    loop._quota_pause_until[loop._quota_key("stock", "x")] = time.time() + 5000
    assert loop._notify_quota_once("u1", "stock", "x") is True


# --- provider irraggiungibile ---------------------------------------------
#
# Stessa famiglia, reazione diversa: la quota si esaurisce e resta esaurita,
# la rete cade e quasi sempre torna al giro dopo. È arrivata sulla bacheca come
# "⚠️ Errore monitoraggio BTCUSDT [1d]: MEXC non raggiungibile ... tlsv1 alert
# internal error" — un errore che poi non si è più ripresentato.


def test_unreachable_is_a_provider_error_but_not_a_quota_error():
    from app.providers.base import ProviderUnreachable

    assert issubclass(ProviderUnreachable, ProviderError)
    assert not issubclass(ProviderUnreachable, QuotaExceeded)


def test_the_first_failure_pauses_but_says_nothing(loop):
    """Un errore TLS che al giro dopo non si ripresenta non vale un messaggio."""
    streak = loop._pause_for_unreachable("crypto", "mexc")
    assert streak == 1
    assert loop._quota_paused("crypto", "mexc")
    assert loop._notify_unreachable_once("crypto", "mexc", streak) is False


def test_it_speaks_once_the_outage_lasts(loop):
    for _ in range(loop._UNREACHABLE_SPEAK_AFTER - 1):
        loop._pause_for_unreachable("crypto", "mexc")
    streak = loop._pause_for_unreachable("crypto", "mexc")
    assert loop._notify_unreachable_once("crypto", "mexc", streak) is True


def test_it_says_it_only_once_while_the_outage_lasts(loop):
    for _ in range(6):
        streak = loop._pause_for_unreachable("crypto", "mexc")
        loop._notify_unreachable_once("crypto", "mexc", streak)
    spoken = sum(1 for k in loop._quota_notified if k[0] is None)
    assert spoken == 1


def test_the_wait_grows_with_the_streak(loop):
    import time as _t

    loop._pause_for_unreachable("crypto", "mexc")
    first = loop._quota_pause_until[loop._quota_key("crypto", "mexc")] - _t.time()
    for _ in range(3):
        loop._pause_for_unreachable("crypto", "mexc")
    later = loop._quota_pause_until[loop._quota_key("crypto", "mexc")] - _t.time()
    assert later > first


def test_a_successful_read_resets_everything(loop):
    """Altrimenti un guasto di ieri farebbe scattare l'allarme al primo
    inciampo di domani."""
    for _ in range(4):
        streak = loop._pause_for_unreachable("crypto", "mexc")
        loop._notify_unreachable_once("crypto", "mexc", streak)
    loop._provider_recovered("crypto", "mexc")
    assert loop._pause_for_unreachable("crypto", "mexc") == 1
    assert loop._notify_unreachable_once("crypto", "mexc", 1) is False


def test_exchanges_are_counted_separately(loop):
    loop._pause_for_unreachable("crypto", "mexc")
    loop._pause_for_unreachable("crypto", "mexc")
    assert loop._pause_for_unreachable("crypto", "binance") == 1
