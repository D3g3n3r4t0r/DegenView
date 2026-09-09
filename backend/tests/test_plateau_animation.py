"""
La ricerca stabile disegnata, nel pannello del laboratorio.

Non c'e' un canale nuovo verso il server: l'animazione legge le stesse righe
che la ricerca gia' scrive nel log (say(...) in plateau.py e pipeline.py),
con le espressioni regolari incollate a quel testo esatto. Se una frase li'
cambia forma, questi test la notano prima che l'animazione smetta di capirla
in silenzio.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP_JS = Path(__file__).resolve().parent.parent.parent / "frontend" / "static" / "app.js"
_PLATEAU_PY = Path(__file__).resolve().parent.parent / "app" / "analysis" / "plateau.py"


def _js() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def _real_lines() -> list[str]:
    """Le frasi vere che plateau.py scrive, con dati plausibili al posto delle
    f-string — sono quelle che le regex di app.js devono saper leggere."""
    return [
        "cerco i confini su 5 assi: dove il risultato cambia, non dove cambia il parametro",
        "asse rsi_length: 8 confini → 9 intervalli (70 backtest)",
        "asse bb_mult: 1 confine → 2 intervalli (22 backtest)",  # singolare
        "asse len: ancora al lavoro — 12 backtest finora",
        "griglia: 9 × 5 × 2 × 8 × 6 = 4320 celle",
        "griglia: 9 × 5 = 45 celle · inerti su questa serie: bb_mult",  # con la coda
        "4320 celle oltre il budget di 400: invece di sorteggiarne 400 le apro per ordine di promessa",
        "provo il centro di 1080 celle (enumerate tutte)",
        "celle 50 — 32 configurazioni distinte finora",
        "128 configurazioni distinte su 400 celle provate: le altre producono esattamente gli stessi trade",
        "4 candidati con almeno 8 trade; ne scuoto 4 con 14 spostamenti casuali di ±5%",
        "finalista 1/4: regge 1 volta su 14 — +17.4% su 8 trade",
        "finalista 4/12: regge 10 volte su 14 — -12.4% su 8 trade",  # negativo, plurale "volte"
        "scelto: +17.4% su 8 trade, stabile 7% delle volte",
        "scelto: +164.6% su 10 trade, stabile 43% delle volte (il massimo secco faceva +198.4% ma regge meno)",
    ]


def _extract_regexes(js: str) -> list[re.Pattern]:
    """Le stesse regex di plateauAnimParseLine, tradotte in Python. Tenerle
    duplicate qui e' il prezzo di non avere un motore JS in questo progetto —
    vedi la convenzione gia' in uso per le altre verifiche su app.js."""
    start = js.index("function plateauAnimParseLine(m) {")
    end = js.index("function plateauAnimFeed(", start)
    body = js[start:end]
    # [^/] da solo si fermerebbe al primo "\/" (una barra dentro il pattern
    # JS dev'essere scritta cosi', o chiuderebbe il letterale) leggendolo come
    # fine del regex — (?:\\.|[^/]) tratta ogni coppia backslash+carattere
    # come opaca, cosi' "\/" resta dentro invece di troncare l'estrazione.
    literals = re.findall(r"/(\^(?:\\.|[^/])+)/\.exec", body)
    # 7 forme ancorate: confini, asse, budget-superato, enumerate-tutte,
    # checkpoint di apertura, apertura-finale, quanti-finalisti, finalista,
    # scelto — "griglia:" e' un'ottava forma ma non ancorata (si cerca
    # ovunque nella riga), gestita a parte nel test sotto.
    assert len(literals) >= 7, "il parser deve avere almeno le 7 forme di riga ancorate attese"
    return [re.compile(pat) for pat in literals]


def test_every_real_log_line_is_matched_by_some_pattern():
    """"espansione guidata: ..." non e' in questa lista apposta: la sua
    informazione (celle aperte, finalisti) e' ridondante con la riga
    successiva "N configurazioni distinte su M celle provate", che invece
    l'animazione legge — non serve un secondo modo di saperlo."""
    js = _js()
    patterns = _extract_regexes(js)
    unmatched = []
    for line in _real_lines():
        if line.startswith("griglia:"):
            if not re.search(r"= (\d+) celle(?:\s|$)", line):
                unmatched.append(line)
            continue
        if "ne scuoto" in line:
            # Questa non e' ancorata a inizio riga (il numero di finalisti
            # arriva a meta' frase, dopo "N candidati con almeno..."), quindi
            # _extract_regexes() non la prende insieme alle altre.
            if not re.search(r"ne scuoto (\d+) con (\d+) spostamenti", line):
                unmatched.append(line)
            continue
        if not any(p.search(line) for p in patterns):
            unmatched.append(line)
    assert not unmatched, f"righe vere che l'animazione non riconosce: {unmatched}"


def test_the_animation_only_shows_for_the_stable_search():
    js = _js()
    assert 'job.mode === "plateau"' in js
    start = js.index("function plateauAnimShow(job)")
    body = js[start:start + 500]
    assert "isPlateau" in body


def test_the_job_records_its_own_mode_for_the_animation_to_read():
    js = _js()
    start = js.index("optJobs.set(started.job_id")
    block = js[start:start + 400]
    assert "mode: optMode" in block


def test_reopening_the_progress_window_replays_the_whole_log():
    """Il lavoro puo' essere gia' a meta' quando si riapre la finestra:
    l'animazione deve poter ricostruire tutte le fasi gia' passate, non solo
    quelle da qui in poi."""
    js = _js()
    start = js.index("function openOptProgress(jobId)")
    body = js[start:start + 1200]
    assert "plateauAnimShow(job)" in body


def test_new_log_lines_are_fed_incrementally_while_watching():
    js = _js()
    start = js.index("async function pollOnce(job)")
    body = js[start:start + 1200]
    assert 'plateauAnimFeed(data.log || [])' in body


def test_the_canvas_exists_and_is_hidden_by_default():
    html = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
    src = html.read_text(encoding="utf-8")
    assert 'id="opt-progress-anim"' in src
    m = re.search(r'<canvas id="opt-progress-anim"[^>]*class="([^"]+)"', src)
    assert m and "hidden" in m.group(1)


def test_plateau_py_still_says_the_five_things_the_animation_listens_for():
    """Se una di queste frasi sparisse da plateau.py, l'animazione perderebbe
    silenziosamente quella fase: meglio un test che se ne accorga qui."""
    src = _PLATEAU_PY.read_text(encoding="utf-8")
    needles = [
        "cerco i confini su",
        "griglia: ",
        "configurazioni distinte finora",
        "configurazioni distinte su",
        "spostamenti casuali di",
        "finalista {rank}",
        "scelto: ",
        "ancora al lavoro",
    ]
    missing = [n for n in needles if n not in src]
    assert not missing, f"frasi che plateau.py non scrive piu': {missing}"


def test_an_axis_still_being_searched_shows_something_instead_of_nothing():
    """Segnalato dal vivo con uno screenshot: il pannello restava fermo su
    "asse 0/5" per una quindicina di secondi senza muovere nulla, ne' nel
    disegno ne' nel log — un asse pesante puo' metterci cosi' tanto prima
    della sua riga finale. Questo e' il contatore che nel frattempo si vede
    crescere."""
    js = _js()
    assert "axisBusy" in js
    start = js.index("if (plateauAnim.axisBusy > 0)")
    body = js[start:start + 900]
    assert "al lavoro" in body


def test_finishing_an_axis_clears_its_own_busy_counter():
    """Altrimenti il contorno tratteggiato dell'asse appena chiuso resterebbe
    a schermo mentre il prossimo asse comincia, mostrando un numero vecchio."""
    js = _js()
    start = js.index("^asse (.+?): (\\d+) confin")
    block = js[start:start + 300]
    assert "plateauAnim.axisBusy = 0" in block
