"""Test della guardia d'età sugli alert.

Il guasto che questi test bloccano è arrivato davvero: attivando un alert sono
partite una ventina di notifiche con prezzi di anni diversi. La deduplica
funzionava — diceva correttamente "questi segnali non li ho mai visti". Il
punto è che non era la domanda giusta: un segnale del 2022 non è azionabile
oggi, che sia già stato notificato o no.
"""

from __future__ import annotations

import time

import pytest

from app.models import StrategySignal, StrategyState
from app.notify import alerts


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts, "_SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(alerts, "_STATS_FILE", tmp_path / "stats.json")
    alerts._seen.clear()
    alerts._stats.clear()
    alerts._seeded_scopes.clear()


def _sig(ts: int, kind: str = "entry_long", price: float = 100.0) -> StrategySignal:
    return StrategySignal(time=ts, type=kind, price=price, label=kind)


def _state(signals: list[StrategySignal], name: str = "Lorenzo (trend-follower)") -> StrategyState:
    return StrategyState(name=name, position="flat", signals=signals)


NOW = lambda: int(time.time())  # noqa: E731


# --- la finestra ---------------------------------------------------------


def test_window_scales_with_the_timeframe():
    assert alerts._max_signal_age_s("1h") < alerts._max_signal_age_s("1d")
    assert alerts._max_signal_age_s("1d") < alerts._max_signal_age_s("1w")


def test_window_has_a_floor_and_a_ceiling():
    assert alerts._max_signal_age_s("1m") >= alerts._MIN_SIGNAL_AGE_WINDOW_S
    assert alerts._max_signal_age_s("1M") <= alerts._MAX_SIGNAL_AGE_WINDOW_S


def test_unknown_interval_does_not_crash():
    assert alerts._max_signal_age_s("boh") > 0


# --- il comportamento che conta ------------------------------------------


def test_first_pass_never_alerts():
    st = _state([_sig(NOW() - 60)])
    assert alerts.find_new_signals("BTCUSDT", "1h", st) == []


def test_a_fresh_signal_after_seeding_alerts():
    alerts.find_new_signals("BTCUSDT", "1h", _state([]))       # seed
    st = _state([_sig(NOW() - 60)])
    assert len(alerts.find_new_signals("BTCUSDT", "1h", st)) == 1


def test_an_old_signal_never_alerts_even_if_never_seen():
    """Il cuore del fix. La deduplica direbbe 'nuovo', ed è irrilevante."""
    alerts.find_new_signals("BTCUSDT", "1d", _state([]))       # seed
    old = _sig(NOW() - 400 * 86400)
    assert alerts.find_new_signals("BTCUSDT", "1d", _state([old])) == []


def test_the_reported_flood_does_not_happen():
    """Riproduce il caso reale: lo scope è già registrato con pochi segnali,
    poi la stessa chiamata comincia a restituire anni di storia — che è
    esattamente l'effetto di aver alzato il tetto da 30 a 10 000."""
    now = NOW()
    alerts.find_new_signals("KASUSDT", "1d", _state([_sig(now - 86400)]))

    storia = [_sig(now - d * 86400, price=float(d)) for d in range(5, 900, 30)]
    recente = _sig(now - 3600, price=999.0)
    fresh = alerts.find_new_signals("KASUSDT", "1d", _state(storia + [recente]))

    assert len(fresh) == 1, f"attese 1 notifica, arrivate {len(fresh)}"
    assert fresh[0].price == 999.0


def test_old_signals_are_still_marked_seen():
    """Devono essere registrati comunque: se restassero fuori da `_seen`,
    tornerebbero a sembrare nuovi appena la finestra si sposta."""
    alerts.find_new_signals("BTCUSDT", "1d", _state([]))
    old = _sig(NOW() - 400 * 86400)
    alerts.find_new_signals("BTCUSDT", "1d", _state([old]))
    key = alerts._signal_key("BTCUSDT", "1d", "Lorenzo (trend-follower)", old)
    assert key in alerts._seen


def test_losing_the_dedup_state_no_longer_causes_a_flood():
    """La difesa vera: anche azzerando completamente la deduplica — un prune,
    un file cancellato — la storia non riparte."""
    now = NOW()
    storia = [_sig(now - d * 86400) for d in range(5, 400, 20)]
    alerts.find_new_signals("ETHUSDT", "1d", _state(storia))

    alerts._seen.clear()                       # come dopo un prune
    fresh = alerts.find_new_signals("ETHUSDT", "1d", _state(storia))
    assert fresh == []


def test_once_frequency_also_respects_the_age_guard():
    alerts.find_new_signals("BTCUSDT", "1d", _state([]), frequency="once")
    old = _sig(NOW() - 400 * 86400)
    assert alerts.find_new_signals("BTCUSDT", "1d", _state([old]), frequency="once") == []


def test_a_signal_right_at_the_edge_still_alerts():
    alerts.find_new_signals("BTCUSDT", "1d", _state([]))
    edge = _sig(NOW() - alerts._max_signal_age_s("1d") + 120)
    assert len(alerts.find_new_signals("BTCUSDT", "1d", _state([edge]))) == 1
