"""
"Applica al grafico" deve portare TUTTA la configurazione.

Segnalazione 70a6bedd: applicando dal Laboratorio, il grafico prendeva il pair
ma restava sul proprio timeframe e sulla propria strategia. I trade disegnati
vengono da un backtest fatto con pair, timeframe, strategia e parametri
insieme: cambiarne solo una parte disegna i trade di una configurazione sopra
il grafico di un'altra, e sembrano semplicemente sbagliati — "devono sempre
coincidere".

Non c'e' un motore di test JavaScript in questo progetto, quindi qui si
verifica la struttura: che esista un solo punto che porta una configurazione
sul grafico, che tocchi tutte e quattro le cose, e che entrambi i percorsi
(Laboratorio e Archivio) passino di li'. Una riapplicazione parziale
reintrodotta a mano fa fallire questo test.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP_JS = Path(__file__).resolve().parent.parent.parent / "frontend" / "static" / "app.js"


def _source() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def _function_body(src: str, header: str) -> str:
    # Si comincia a contare dalla graffa che apre il CORPO: i parametri
    # destrutturati ne aprono e chiudono una loro, e contando da li' il corpo
    # finirebbe alla fine della lista dei parametri.
    start = src.index(header)
    start = src.index(") {", start) + 2
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError(f"corpo non trovato per {header}")


def test_the_single_apply_helper_touches_all_four_things():
    body = _function_body(_source(), "function applyConfigToChart(")
    assert "ticker-input" in body                 # il pair
    assert "interval-primary" in body             # il timeframe
    assert "active-strategy-select" in body       # la strategia
    assert "strategy-params-fields" in body       # i suoi parametri
    assert "renderStrategyParamsFields()" in body, (
        "cambiando strategia i campi vanno ridisegnati: ogni strategia ha i suoi"
    )


def test_both_apply_paths_go_through_it():
    src = _source()
    archive = _function_body(src, "function applyArchiveEntry(")
    assert "applyConfigToChart(" in archive

    lab_start = src.index('labEl("lab-apply-btn").addEventListener')
    lab = src[lab_start:lab_start + 2000]
    assert "applyConfigToChart(" in lab


def test_the_lab_path_passes_the_timeframe_and_the_strategy():
    src = _source()
    lab_start = src.index('labEl("lab-apply-btn").addEventListener')
    lab = src[lab_start:lab_start + 2000]
    assert re.search(r"interval:\s*labState\.tf", lab)
    assert re.search(r"strategyName:\s*labState\.strategy", lab)


def test_the_lab_activation_writes_parameters_before_switching_the_alert_on():
    """Accendere scatta la fotografia che finisce in archivio: farla prima di
    salvare i parametri la fa nascere con i default, e l'archivio resta a dire
    che l'alert e' partito con una configurazione che non ha mai avuto."""
    src = _source()
    start = src.index('labEl("lab-signal-btn").addEventListener')
    block = src[start:start + 4000]
    params_at = block.index("/strategy_params")
    enable_at = block.index("strategy_name: labState.strategy, enabled: true")
    assert params_at < enable_at
