"""
Il riepilogo settimanale, e il perche' e' in italiano senza tradurre niente.

Lorenzo: "i messaggi degli aggiornamenti li voglio in italiano sempre" e
"vorrei che ogni settimana lo inviassi".

I messaggi di commit di questo progetto sono in inglese per convenzione
(CLAUDE.md), quindi un changelog che li riporta cosi' com'e' e' inglese per
costruzione. La via scelta non traduce a runtime — prende il testo italiano
dove gia' esiste: il trailer `Aggiornamento:` sui commit, e le risoluzioni
della bacheca, che sono scritte in italiano da sempre perche' le legge lui.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.notify.weekly_recap import (
    build_recap,
    current_week_key,
    italian_line,
    should_send,
)

DAY = 86400


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp())


# ── la riga italiana ─────────────────────────────────────────────────────


def test_the_italian_trailer_wins_over_the_english_subject():
    msg = ("Fire alerts at the candle close, not one bar later\n\n"
           "Long English body explaining the fix.\n\n"
           "Aggiornamento: gli alert partono alla chiusura della candela\n")
    assert italian_line(msg) == "gli alert partono alla chiusura della candela"


def test_without_a_trailer_the_subject_is_used_rather_than_skipping_the_commit():
    """Un titolo inglese e' un'informazione vera; saltare il commit
    nasconderebbe una modifica avvenuta."""
    assert italian_line("Fix the MEXC futures host\n\nbody") == "Fix the MEXC futures host"


def test_an_empty_message_does_not_produce_an_empty_bullet():
    assert italian_line("   ") == "(senza descrizione)"


# ── il messaggio ─────────────────────────────────────────────────────────


def _write_resolutions(tmp_path, entries):
    p = tmp_path / "resolutions.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def test_the_recap_lists_the_issues_closed_in_the_window(tmp_path):
    now = _ts("2026-09-21")
    res = _write_resolutions(tmp_path, {
        "abc123": {"at": now - 2 * DAY, "summary": "Gli alert partivano un giorno dopo. Dettagli lunghi."},
        "old999": {"at": now - 30 * DAY, "summary": "Roba di un mese fa"},
    })
    text = build_recap(["Aggiornamento: qualcosa"], now, resolutions_path=res)
    assert "abc123" in text
    assert "Gli alert partivano un giorno dopo" in text
    assert "old999" not in text, "fuori finestra: non e' successo questa settimana"


def test_only_the_first_sentence_of_a_resolution_is_used(tmp_path):
    """Un riepilogo e' un indice, non l'archivio."""
    now = _ts("2026-09-21")
    res = _write_resolutions(tmp_path, {
        "x1": {"at": now - DAY, "summary": "Prima frase. Seconda frase molto lunga che non serve qui."},
    })
    text = build_recap([], now, resolutions_path=res)
    assert "Prima frase" in text
    assert "Seconda frase" not in text


def test_a_week_with_nothing_to_say_sends_nothing(tmp_path):
    """Un riepilogo che arriva anche quando non e' successo niente insegna a
    ignorarlo, e allora non serve piu' nemmeno la settimana in cui conta."""
    now = _ts("2026-09-21")
    res = _write_resolutions(tmp_path, {})
    assert build_recap([], now, resolutions_path=res) is None


def test_a_missing_resolutions_file_does_not_break_the_recap(tmp_path):
    text = build_recap(["Aggiornamento: una modifica"], _ts("2026-09-21"),
                       resolutions_path=tmp_path / "non-esiste.json")
    assert text is not None
    assert "una modifica" in text


# ── quando parte ─────────────────────────────────────────────────────────


def test_it_goes_out_monday_morning_and_only_once():
    monday_9 = _ts("2026-09-21") + 9 * 3600      # 21 set 2026 e' un lunedi'
    assert datetime.fromtimestamp(monday_9, tz=timezone.utc).weekday() == 0

    assert should_send(monday_9, last_sent_week="") is True
    already = current_week_key(monday_9)
    assert should_send(monday_9, last_sent_week=already) is False


def test_it_does_not_go_out_before_the_hour_or_on_other_days():
    monday_early = _ts("2026-09-21") + 3 * 3600
    tuesday = _ts("2026-09-22") + 9 * 3600
    assert should_send(monday_early, "") is False
    assert should_send(tuesday, "") is False


def test_a_restart_on_monday_morning_does_not_send_it_twice():
    """Il caso vero: il deploy riavvia l'app, e il ciclo riparte da zero."""
    monday_9 = _ts("2026-09-21") + 9 * 3600
    sent_week = current_week_key(monday_9)
    monday_11 = monday_9 + 2 * 3600
    assert should_send(monday_11, sent_week) is False
    # ma la settimana dopo si'
    next_monday = monday_9 + 7 * DAY
    assert should_send(next_monday, sent_week) is True
