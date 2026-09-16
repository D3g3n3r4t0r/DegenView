"""
Due canali Telegram, non uno.

Lorenzo: "voglio che i bot Telegram mi arrivi i messaggi di apertura e chiusura
della posizione, quindi degli alert, in una chat separata rispetto ai messaggi
delle modifiche del software, dell'avanzamento della programmazione".

La separazione esisteva gia' nel codice — `send_to()` per gli alert (chat
personale dell'utente) e `send_message()` per i messaggi di sistema — ma
entrambe finivano nella stessa conversazione perche' puntavano allo stesso
chat_id. `TELEGRAM_DEV_CHAT_IDS` rende la distinzione configurabile senza
toccare il percorso degli alert.
"""

from __future__ import annotations

from app.config import settings
from app.notify import telegram


def test_system_messages_go_to_the_dev_chat_when_one_is_set(monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_ids", "111", raising=False)
    monkeypatch.setattr(settings, "telegram_dev_chat_ids", "-1009999", raising=False)
    assert telegram._chat_ids() == ["-1009999"]


def test_without_a_dev_chat_nothing_moves(monkeypatch):
    """Chi non configura niente deve continuare a ricevere dove riceveva."""
    monkeypatch.setattr(settings, "telegram_chat_ids", "111,222", raising=False)
    monkeypatch.setattr(settings, "telegram_dev_chat_ids", "", raising=False)
    assert telegram._chat_ids() == ["111", "222"]


def test_several_dev_chats_are_all_used(monkeypatch):
    monkeypatch.setattr(settings, "telegram_chat_ids", "111", raising=False)
    monkeypatch.setattr(settings, "telegram_dev_chat_ids", " -100111 , -100222 ", raising=False)
    assert telegram._chat_ids() == ["-100111", "-100222"]


def test_trading_alerts_never_go_through_the_system_channel():
    """send_to() prende il chat_id dell'utente e non guarda la configurazione.

    E' cio' che tiene separati i due percorsi: un alert non puo' finire nella
    chat di sistema nemmeno sbagliando la configurazione, perche' non la legge.
    """
    import inspect

    source = inspect.getsource(telegram.send_to)
    assert "_chat_ids" not in source
    assert "chat_id" in inspect.signature(telegram.send_to).parameters
