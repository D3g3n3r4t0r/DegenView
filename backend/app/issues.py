"""
Segnalazioni dei problemi, scritte dall'app.

Chi scrive cosa è separato di proposito, come per i file nel repo:

  * Le SEGNALAZIONI le scrivete voi dall'interfaccia. Vivono nel volume Fly, in
    `data/issues.json`, e sopravvivono ai deploy.
  * Le RISOLUZIONI le scrive Claude, in `app/data/resolutions.json`, che è
    versionato in git e viaggia con il deploy.

Nessuno dei due lati può quindi sovrascrivere l'altro, e ogni risoluzione porta
con sé la storia del commit che l'ha introdotta invece di un campo "data" che
qualcuno deve ricordarsi di compilare.

L'unione avviene in lettura, agganciando la risoluzione all'id della
segnalazione: gli id sono generati dal server e restano stabili, quindi il
riferimento regge anche se l'elenco viene riordinato o filtrato.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Literal

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_STORE_FILE = _DATA_DIR / "issues.json"
# Le risposte seguono la stessa divisione delle segnalazioni: quelle scritte
# dall'app vivono sul volume e appartengono a chi le scrive, quelle di Claude
# arrivano col deploy. Un botta e risposta in cui una parte puo' riscrivere le
# parole dell'altra non e' una conversazione.
_REPLIES_FILE = _DATA_DIR / "issue_replies.json"
# Quali voci della lista iniziale sono gia' state inserite. Serve a distinguere
# "mai inserita" da "inserita e poi cancellata": senza questo file l'unico modo
# per non resuscitare una voce cancellata era non inserirne mai di nuove.
_SEEDED_FILE = _DATA_DIR / "seeded_ids.json"

# Versionato in git e distribuito col deploy: è il lato di Claude.
_RESOLUTIONS_FILE = Path(__file__).resolve().parent / "data" / "resolutions.json"
_CLAUDE_REPLIES_FILE = Path(__file__).resolve().parent / "data" / "replies.json"

_MAX_ISSUES = 500

Status = Literal["aperto", "in corso", "risolto", "scartato"]
Priority = Literal["alta", "media", "bassa"]

_VALID_STATUS = {"aperto", "in corso", "risolto", "scartato", "riaperto"}
_VALID_PRIORITY = {"alta", "media", "bassa"}

_issues: list[dict] = []
_seeded_ids: set[str] = set()
_replies: list[dict] = []


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            _issues.clear()
            _issues.extend(raw)
    except (json.JSONDecodeError, OSError):
        pass


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps(_issues, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_replies() -> None:
    if not _REPLIES_FILE.exists():
        return
    try:
        raw = json.loads(_REPLIES_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            _replies.clear()
            _replies.extend(x for x in raw if isinstance(x, dict))
    except (json.JSONDecodeError, OSError):
        pass


def _save_replies() -> None:
    try:
        _REPLIES_FILE.write_text(json.dumps(_replies, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _claude_replies() -> dict[str, list[dict]]:
    """Le risposte di Claude, rilette a ogni richiesta come le risoluzioni."""
    try:
        raw = json.loads(_CLAUDE_REPLIES_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def add_reply(issue_id: str, text: str, author: str = "", reopen: bool = False) -> dict:
    """Una risposta a una segnalazione, con la possibilita' di riaprirla.

    Riaprire serve perche' "risolto" lo decide chi ha scritto la segnalazione,
    non chi ha scritto la correzione: se il problema si vede ancora, la voce
    deve tornare in cima all'elenco invece di restare chiusa per decreto.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Risposta vuota")
    entry = {
        "id": uuid.uuid4().hex[:8],
        "issue_id": issue_id,
        "text": text[:4000],
        "author": (author or "").strip()[:120],
        "created_at": int(time.time()),
        "reopen": bool(reopen),
    }
    _replies.append(entry)
    _save_replies()
    if reopen:
        for it in _issues:
            if it["id"] == issue_id:
                it["reopened_at"] = entry["created_at"]
                _save()
                break
    return entry


def _load_seeded() -> None:
    if not _SEEDED_FILE.exists():
        return
    try:
        raw = json.loads(_SEEDED_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            _seeded_ids.update(str(x) for x in raw)
    except (json.JSONDecodeError, OSError):
        pass


def _save_seeded() -> None:
    try:
        _SEEDED_FILE.write_text(json.dumps(sorted(_seeded_ids)), encoding="utf-8")
    except OSError:
        pass


def _resolutions() -> dict[str, dict]:
    """Le risoluzioni scritte da Claude, lette a ogni richiesta.

    Rilette ogni volta anziché memorizzate all'avvio: il file arriva col deploy,
    e un processo che sopravvive a più deploy servirebbe altrimenti le
    risoluzioni della versione con cui è partito.
    """
    try:
        raw = json.loads(_RESOLUTIONS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


_SEED = [
    ("seed-0037", "Durante un deploy il sito mostra un errore grezzo",
     "Quando c'e' un deploy in corso vorrei che chi si collega veda un avviso invece di un errore, "
     "cosi' non sembra che il sito sia rotto.",
     "media"),
    ("seed-0036", "Il grafico non proietta il prezzo corrente sull'asse",
     "Serve la linea del prezzo attuale che arriva fino all'asse con l'etichetta, come su TradingView, "
     "su ogni grafico.",
     "media"),
    ("seed-0035", "\"Errore di rete\" sull'archivio, senza dire altro",
     "Premendo 'Attiva l'alert' su una voce d'archivio compare 'Errore di rete' e basta: non si capisce "
     "se il server non ha risposto o se ha risposto male.",
     "media"),
    ("seed-0034", "Lo sniper propone meme coin invece di progetti seri",
     "Voglio vedere solo crypto legittime, o quantomeno progetti seri: le meme coin non mi interessano.",
     "alta"),
    ("seed-0032", "Il tema non viaggiava davvero con l'account",
     "Il frontend mandava 'theme' a PUT /api/preferences ma l'allowlist del backend non lo includeva: "
     "il valore veniva scartato in silenzio e il tema restava legato al browser, non all'account.",
     "media"),
    ("seed-0031", "Il sito e' pubblico e le API rispondono a chiunque",
     "Con il trasloco su un dominio pubblico serve verificare che le funzioni pesanti e i dati "
     "non siano raggiungibili senza credenziali.", "alta"),
    ("seed-0033", "La sezione Watchlist non si trovava piu' da desktop",
     "Dopo il ridisegno (seed-0028), 'Sorveglia' nella sidebar apriva solo la tab Alert: la lista dei "
     "ticker rapidi (tab Watchlist, i preferiti da un clic) non aveva piu' nessuna voce di navigazione "
     "su desktop, solo dal menu mobile 'Altro'.", "alta"),
    ("seed-0028", "Ridisegnare il sito: ogni funzione al suo posto",
     "Il prodotto e' cresciuto per innesti e ogni funzione era disegnata bene da sola, ma nessuna "
     "parlava la lingua delle altre. Serve un occhio globale che rimetta in discussione dove sta "
     "ogni cosa, non solo che colore ha.", "alta"),
    ("seed-0029", "Il backtest non dice a che prezzo entra",
     "Non era possibile sapere se una candela viene considerata alla chiusura oppure nel momento in "
     "cui il segnale si verifica. Due rendimenti calcolati con ipotesi diverse non sono confrontabili, "
     "e l'ipotesi non era scritta da nessuna parte.", "alta"),
    ("seed-0030", "Le operazioni eseguite non lasciano traccia sul grafico",
     "Il grafico mostrava cosa la strategia diceva, mai cosa e' successo davvero: guardando la serie "
     "non si poteva rispondere alla domanda \"quella volta sono entrato o no?\". Ogni operazione, "
     "manuale o automatica, deve restare segnata.", "alta"),
    ("seed-0001", "Bug grafico sui trade del backtest", "", "media"),
    ("seed-0002", "Salvare il backtest in database quando si attiva un alert",
     "Una volta attivato l'alert di una strategia bisogna poter accedere al backtesting e salvarlo, "
     "per avere un archivio consultabile delle strategie generate dall'ottimizzazione.", "alta"),
    ("seed-0003", "Strategia Gabriele 2 con movimento short",
     "Da testare e applicare poi sui futures.", "media"),
    ("seed-0004", "Graficare l'imbalance FVG in stile TradingView",
     "Zone d'interesse a barre orizzontali.", "media"),
    ("seed-0005", "Valore RSI sul pallino blu invece che sulla freccia del cursore", "", "bassa"),
    ("seed-0006", "Pulsante per attivare/disattivare modalita' black", "", "bassa"),
    ("seed-0007", "Discrepanza nel numero di trade fra ottimizzazione e manuale",
     "Con gli stessi valori impostati a mano si ottengono risultati simili ma quantita' di trade molto "
     "diverse rispetto alla modalita' automatica. Ogni variabile aggiuntiva usata dalla logica automatica "
     "deve essere parametrizzata e visibile dopo l'ottimizzazione, per rendere il risultato replicabile "
     "a mano e verificabile.", "alta"),
    ("seed-0008", "Venti notifiche Telegram con prezzi disparati dopo aver attivato un alert", "", "alta"),
    ("seed-0009", "Filtri di ottimizzazione su trade in perdita e drawdown",
     "Poter selezionare solo strategie con un minimo/massimo di trade in perdita (compreso 0) "
     "o una percentuale di drawdown (compreso 0%).", "media"),
    ("seed-0010", "Dubbi sui dati non usati in ottimizzazione nel backtest",
     "Verificare che non escluda trade 'a giochi fatti' per gonfiare la performance, e che quei trade "
     "sarebbero davvero stati aperti o chiusi dal bot in tempo reale.", "alta"),
    ("seed-0011", "Il trading automatico non ha mai piazzato un ordine",
     "Trovato lavorando sugli alert, non segnalato: non c'era modo di accorgersene. "
     "Nessun errore, nessun log, semplicemente nessun ordine.", "alta"),
    ("seed-0013", "Il sito non carica piu': resta la schermata vuota",
     "Segnalato con screenshot da telefono: nav e testo iniziale visibili, ma niente funziona.", "alta"),
    ("seed-0014", "La pagina resta vecchia dopo un deploy",
     "Il log dell'ottimizzazione mostrava ancora la versione precedente mentre in produzione c'era gia' quella nuova.", "alta"),
    ("seed-0015", "L'ottimizzazione fallisce con un errore che non parla di ottimizzazione",
     "'The string did not match the expected pattern', e nessun modo di sapere se sta lavorando.", "alta"),
    ("seed-0016", "La ricerca sembra tirare i dadi",
     "Deve capire la strategia e concentrarsi come fa un navigatore, non provare ogni strada.", "alta"),
    ("seed-0017", "La strategia non tiene conto della volatilita' delle coppie poco liquide",
     "Su altcoin che si muovono molto senza un trend vero rende male.", "alta"),
    ("seed-0018", "Se chiudo il browser perdo l'ottimizzazione in corso",
     "Deve continuare, avvisarmi su Telegram alla fine e restare salvata in un archivio.", "alta"),
    ("seed-0019", "Il sito diventa irraggiungibile mentre gira una ricerca",
     "Segnalato dal vivo durante una ricerca stabile.", "alta"),
    ("seed-0020", "L'indicatore non e' allineato al prezzo",
     "Segnalato con screenshot: il pannello sotto il grafico non e' agganciato alle stesse candele.", "alta"),
    ("seed-0022", "Lo stesso account vede il tema chiaro su un computer e scuro su un altro",
     "Gabriele dal suo pc non vede lo sfondo bianco.", "media"),
    ("seed-0023", "Le segnalazioni sono tante e non si trovano",
     "Serve un elenco richiudibile e una ricerca per parole chiave.", "media"),
    ("seed-0024", "Esportare i trade del backtest in Excel",
     "Cliccando sul numero di trade, poter scaricare tutto in un file con i grafici per "
     "riverificare il portafoglio.", "media"),
    ("seed-0025", "Errore 422 quando si avvia la strategia",
     "Premendo per far girare la strategia arriva 'Errore 422' e non parte niente.", "alta"),
    ("seed-0021", "Chiudendo il log non si sa piu' a che punto e' l'ottimizzazione",
     "Serve un indicatore che resti visibile finche' non e' salvata in archivio, e poter lanciare "
     "un'altra ricerca senza aspettare la prima.", "media"),
    ("seed-0012", "Voci della lista iniziale che non comparivano piu' sulla bacheca",
     "Trovato controllando la bacheca dal vivo: seed-0011 non c'era, e la sua risoluzione "
     "restava senza voce a cui agganciarsi.", "media"),
    ("seed-0026", "Visualizzare in modo stilizzato cosa sta facendo la ricerca stabile",
     "Durante la ricerca stabile, un'animazione che mostri graficamente l'equivalente di "
     "quello che l'algoritmo sta facendo — non serve fedele al dettaglio, basta che sia "
     "bella e minimale.", "bassa"),
    ("seed-0027", "Operazioni futures: leva, margine, liquidazione",
     "Introdurre le operazioni futures — completo, accurato e a prova di errore: leva, "
     "margine isolated, liquidazione intrabar, funding. Prima solo in backtest, esecuzione "
     "reale solo dopo validazione, exchange per exchange.", "media"),
]


def _seed() -> None:
    """Aggiunge le voci della lista iniziale che mancano, una per una.

    Gli id sono fissi e non generati: le risoluzioni scritte da Claude si
    agganciano per id, e un id casuale al primo avvio scollegherebbe le
    diagnosi gia' scritte da queste voci.

    Il controllo e' per id, non "l'elenco e' vuoto". Con quest'ultimo, una voce
    aggiunta alla lista dopo il primo avvio non compariva mai piu': il file sul
    volume esisteva gia', quindi il seeding usciva subito. E' successo con
    seed-0011, che dal vivo non c'era mentre la sua risoluzione, scritta e
    distribuita, restava senza voce a cui agganciarsi.

    Una voce cancellata a mano resta cancellata: `seeded_ids.json` ricorda cosa
    e' gia' stato inserito, cosi' "mai vista" e "vista e buttata" non si
    confondono.
    """
    now = int(time.time())
    have = {it.get("id") for it in _issues}
    added = False
    for i, (iid, title, detail, prio) in enumerate(_SEED):
        if iid in have or iid in _seeded_ids:
            _seeded_ids.add(iid)
            continue
        _issues.append({
            "id": iid, "title": title, "detail": detail, "priority": prio,
            "status": "aperto", "author": "lista iniziale",
            "created_at": now - (len(_SEED) - i),
        })
        _seeded_ids.add(iid)
        added = True
    if added:
        _save()
    _save_seeded()


_load()
_load_seeded()
_load_replies()
_seed()


def list_issues() -> list[dict]:
    """Segnalazioni con la risoluzione agganciata, le più recenti per prime."""
    res = _resolutions()
    mine = _claude_replies()
    out = []
    for it in _issues:
        merged = dict(it)
        r = res.get(it["id"])
        if r:
            merged["resolution"] = r
            # La risoluzione è la fonte di verità sullo stato: se Claude l'ha
            # segnata risolta, l'elenco non deve continuare a mostrarla aperta
            # solo perché nessuno ha aggiornato il campo a mano.
            if r.get("status") in _VALID_STATUS:
                merged["status"] = r["status"]
        # …tranne quando chi l'ha scritta dice che il problema si vede ancora.
        # Una risoluzione senza data si considera piu' vecchia di qualsiasi
        # riapertura: chiudere per decreto una voce riaperta sarebbe il modo
        # piu' veloce di rendere inutile la bacheca.
        reopened = int(it.get("reopened_at", 0) or 0)
        if reopened and reopened > int((r or {}).get("at", 0) or 0):
            merged["status"] = "riaperto"
        thread = [dict(x, side="loro") for x in _replies if x.get("issue_id") == it["id"]]
        thread += [dict(x, side="claude") for x in mine.get(it["id"], [])]
        merged["replies"] = sorted(thread, key=lambda x: x.get("created_at", 0))
        out.append(merged)
    return sorted(out, key=lambda x: x.get("created_at", 0), reverse=True)


def add_issue(title: str, detail: str = "", priority: str = "media",
              author: str = "") -> dict:
    title = (title or "").strip()
    if not title:
        raise ValueError("Titolo mancante")
    entry = {
        "id": uuid.uuid4().hex[:8],
        "title": title[:300],
        "detail": (detail or "").strip()[:4000],
        "priority": priority if priority in _VALID_PRIORITY else "media",
        "status": "aperto",
        "author": (author or "").strip()[:120],
        "created_at": int(time.time()),
    }
    _issues.append(entry)
    if len(_issues) > _MAX_ISSUES:
        del _issues[: len(_issues) - _MAX_ISSUES]
    _save()
    return entry


def update_issue(issue_id: str, *, status: str | None = None,
                 priority: str | None = None, detail: str | None = None) -> dict | None:
    for it in _issues:
        if it["id"] != issue_id:
            continue
        if status is not None:
            if status not in _VALID_STATUS:
                raise ValueError(f"Stato non valido: {status}")
            it["status"] = status
        if priority is not None:
            if priority not in _VALID_PRIORITY:
                raise ValueError(f"Priorità non valida: {priority}")
            it["priority"] = priority
        if detail is not None:
            it["detail"] = detail.strip()[:4000]
        _save()
        return it
    return None


def delete_issue(issue_id: str) -> bool:
    for i, it in enumerate(_issues):
        if it["id"] == issue_id:
            del _issues[i]
            _save()
            return True
    return False
