"""
Riepilogo settimanale, in italiano, sul canale di sistema.

Lorenzo: "i messaggi degli aggiornamenti li voglio in italiano sempre" e
"vorrei che ogni settimana lo inviassi".

Il primo dei due e' meno banale di come suona: i messaggi di commit di questo
progetto sono in inglese per convenzione (CLAUDE.md), quindi un changelog che
li riporta cosi' com'e' e' inglese per costruzione. Tradurli al volo
richiederebbe un servizio di traduzione dentro il percorso delle notifiche —
una dipendenza esterna, e non deterministica, per un messaggio informativo.

La via scelta non traduce: prende il testo italiano da dove *gia' esiste*.

  * le **risoluzioni** (`app/data/resolutions.json`) sono scritte in italiano
    fin dall'inizio, perche' le legge Lorenzo dalla bacheca — sono la parte
    del riepilogo che dice cosa e' cambiato per chi usa il sito;
  * i **commit** possono portare un trailer `Aggiornamento: <testo>` con la
    riga italiana gia' pronta; senza trailer si ricade sul titolo inglese,
    che e' meglio di niente e non blocca nessuno.

Cosi' il messaggio e' italiano perche' qualcuno l'ha scritto in italiano, non
perche' una macchina ci ha provato.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

_RESOLUTIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "resolutions.json"

_TRAILER = "Aggiornamento:"
# I trailer di attribuzione stanno in fondo al messaggio, subito dopo il
# nostro: se finiscono attaccati (capita, a seconda di come il messaggio viene
# composto) la riga italiana si porterebbe dietro "Co-Authored-By: ...".
_ATTRIBUTION = ("Co-Authored-By:", "Claude-Session:", "Signed-off-by:")
_MONTHS_IT = ["gen", "feb", "mar", "apr", "mag", "giu",
              "lug", "ago", "set", "ott", "nov", "dic"]


def _strip_attribution(text: str) -> str:
    for marker in _ATTRIBUTION:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    return text.strip()


def has_italian_line(commit_message: str) -> bool:
    """Se questo commit porta davvero una riga italiana, o solo il titolo."""
    return any(
        line.strip().startswith(_TRAILER) and line.strip()[len(_TRAILER):].strip()
        for line in commit_message.splitlines()
    )


_ACCOUNT_TRAILER = "Solo-account:"


def private_account(commit_message: str) -> str:
    """The account a commit is for, from its "Solo-account:" trailer ("" for
    everyone). Lorenzo, 17/10: a change made only for whitekobra needs no
    Telegram at all, neither the deploy notice nor the weekly recap."""
    for line in commit_message.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(_ACCOUNT_TRAILER.lower()):
            return stripped[len(_ACCOUNT_TRAILER):].strip().lower()
    return ""


def italian_line(commit_message: str) -> str:
    """La riga italiana di un commit: il trailer se c'e', altrimenti il titolo.

    Il fallback non e' una resa: un titolo inglese e' un'informazione vera,
    mentre saltare il commit nasconderebbe una modifica avvenuta.
    """
    for line in commit_message.splitlines():
        stripped = line.strip()
        if stripped.startswith(_TRAILER):
            text = _strip_attribution(stripped[len(_TRAILER):])
            if text:
                return text
    if not commit_message.strip():
        return "(senza descrizione)"
    return commit_message.splitlines()[0].strip()


def _fmt_day(d: datetime) -> str:
    return f"{d.day} {_MONTHS_IT[d.month - 1]}"


def _resolutions_since(since: int, path: Path | None = None) -> list[str]:
    """Le segnalazioni risolte nella finestra, gia' in italiano."""
    target = path or _RESOLUTIONS_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []

    out = []
    for issue_id, res in raw.items():
        if not isinstance(res, dict):
            continue
        at = res.get("at")
        if not isinstance(at, int) or at < since:
            continue
        summary = (res.get("summary") or "").strip()
        if not summary:
            continue
        # Solo la prima frase: un riepilogo e' un indice, non l'archivio.
        first = summary.split(". ")[0].rstrip(".")
        out.append(f"• <b>{html.escape(issue_id, quote=False)}</b> — {html.escape(first, quote=False)}")
    return out


def build_recap(
    commit_messages: list[str],
    now: int,
    days: int = 7,
    resolutions_path: Path | None = None,
) -> str | None:
    """Il messaggio, o None quando non c'e' niente da raccontare.

    Un riepilogo che arriva ogni settimana anche quando non e' successo nulla
    insegna a ignorarlo, e allora non serve piu' a niente nemmeno la settimana
    in cui conta.
    """
    since = now - days * 86400
    start = datetime.fromtimestamp(since, tz=timezone.utc)
    end = datetime.fromtimestamp(now, tz=timezone.utc)

    resolved = _resolutions_since(since, resolutions_path)
    # Solo le modifiche che hanno una riga italiana: un elenco di titoli
    # inglesi dentro un messaggio italiano non e' "quasi italiano", e' un
    # messaggio che non mantiene la promessa. Quelle senza trailer restano
    # nel conteggio, perche' sono avvenute e vanno dichiarate — semplicemente
    # non hanno una frase da leggere.
    # "Solo-account:" changes are announced to that account only, here too.
    commit_messages = [m for m in commit_messages if not private_account(m)]
    described = [italian_line(m) for m in commit_messages if has_italian_line(m)]
    total_changes = len(commit_messages)

    if not resolved and not total_changes:
        return None

    parts = [f"📋 <b>Riepilogo settimanale</b> — {_fmt_day(start)} / {_fmt_day(end)}", ""]

    if resolved:
        parts.append(f"<b>Segnalazioni risolte ({len(resolved)}):</b>")
        parts.extend(resolved)
        parts.append("")

    if total_changes:
        parts.append(f"<b>Modifiche al codice: {total_changes}</b>")
        parts.extend(f"• {html.escape(c, quote=False)}" for c in described)
    else:
        parts.append("<i>Nessuna modifica al codice in questo periodo.</i>")

    return "\n".join(parts).strip()


def current_week_key(now: int) -> str:
    """Anno e settimana ISO: l'identita' della settimana gia' inviata.

    Confrontare settimane invece di "sono passati 7 giorni" evita che un
    riavvio, o un'ora di ritardo, spostino l'invio in avanti di volta in volta
    fino a farlo capitare di mercoledi'.
    """
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def should_send(now: int, last_sent_week: str, weekday: int = 0, hour: int = 9) -> bool:
    """Lunedi' alle 9 UTC, una volta sola per settimana."""
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    if d.weekday() != weekday or d.hour < hour:
        return False
    return current_week_key(now) != last_sent_week
