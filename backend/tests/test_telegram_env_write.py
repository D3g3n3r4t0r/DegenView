"""
Scrivere TELEGRAM_DEV_CHAT_IDS nel .env senza rovinare il resto.

Il file contiene ogni segreto del sistema: token del bot, chiave di sessione,
credenziali. Uno strumento che lo riscrive deve toccare la propria riga e
nient'altro — un file .env rigenerato "quasi uguale" e' un modo silenzioso di
perdere l'accesso a qualcosa.
"""

from __future__ import annotations

import pytest

from tools.telegram_chat_ids import _write_dev_chat

ENV = """\
SESSION_SECRET=non-toccarmi
TELEGRAM_BOT_TOKEN=123:abc
TELEGRAM_CHAT_IDS=999

# commento che deve sopravvivere
TWELVEDATA_API_KEY=xyz
"""


def test_the_key_is_appended_when_missing(tmp_path):
    p = tmp_path / ".env"
    p.write_text(ENV, encoding="utf-8")

    outcome = _write_dev_chat(p, "-1001234567890")

    assert outcome == "aggiunto"
    after = p.read_text(encoding="utf-8")
    assert "TELEGRAM_DEV_CHAT_IDS=-1001234567890" in after
    # tutto il resto intatto, commento compreso
    for line in ENV.splitlines():
        assert line in after


def test_an_existing_key_is_replaced_not_duplicated(tmp_path):
    p = tmp_path / ".env"
    p.write_text(ENV + "TELEGRAM_DEV_CHAT_IDS=-100vecchio\n", encoding="utf-8")

    outcome = _write_dev_chat(p, "-100nuovo")

    assert outcome == "aggiornato"
    after = p.read_text(encoding="utf-8")
    assert after.count("TELEGRAM_DEV_CHAT_IDS=") == 1
    assert "-100nuovo" in after
    assert "-100vecchio" not in after
    assert "TELEGRAM_BOT_TOKEN=123:abc" in after


def test_rewriting_the_same_value_says_so_and_changes_nothing(tmp_path):
    p = tmp_path / ".env"
    p.write_text(ENV + "TELEGRAM_DEV_CHAT_IDS=-100uguale\n", encoding="utf-8")
    before = p.read_text(encoding="utf-8")

    outcome = _write_dev_chat(p, "-100uguale")

    assert outcome == "era gia' impostato su questo gruppo"
    assert p.read_text(encoding="utf-8") == before


def test_a_missing_env_file_is_an_error_not_a_new_file(tmp_path):
    """Crearlo da zero sarebbe peggio che fallire: un .env con dentro una sola
    riga avvia un sistema senza nessuno dei suoi segreti."""
    with pytest.raises(FileNotFoundError):
        _write_dev_chat(tmp_path / "non-esiste", "-100")
    assert not (tmp_path / "non-esiste").exists()
