"""
Segnalazione 70a6bedd, la parte che restava dopo il primo fix.

Il primo giro (seed della bacheca) aveva sistemato pair/timeframe/strategia:
"Applica al grafico" ora li porta tutti. Riaperta con "i trade continuano a
non essere applicati correttamente" — e infatti restava un pezzo: i parametri
di ESECUZIONE del backtest (capitale, taglia della posizione, commissione,
slippage). getStrategyAndBacktestQuery() li scriveva come letterali fissi
(100% equity, zero costi) qualunque cosa il Laboratorio avesse usato, e la
riga che li avrebbe dovuti sincronizzare cercava un campo che non esiste piu'
nell'HTML (la scheda "Strategia" e' stata rimossa) — quindi non copiava
niente, in silenzio.

Questi test leggono direttamente app.js: non c'e' un motore di test
JavaScript in questo progetto, e la convenzione gia' in uso (vedi
test_apply_config.py) e' verificare la struttura del sorgente.
"""

from __future__ import annotations

from pathlib import Path

_APP_JS = Path(__file__).resolve().parent.parent.parent / "frontend" / "static" / "app.js"


def _source() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def _function_body(src: str, header: str) -> str:
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


def test_the_dead_sync_field_helper_is_gone():
    """Cercava [name="initial_capital"][form="params-form"]: quell'elemento
    non esiste piu' nell'HTML da quando la scheda Strategia e' stata tolta.
    mainInput era sempre null, quindi la riga non copiava mai niente."""
    src = _source()
    assert 'form="params-form"], #params-form [name=' not in src


def test_get_strategy_and_backtest_query_no_longer_hardcodes_clean_defaults():
    body = _function_body(_source(), "function getStrategyAndBacktestQuery(")
    assert "chartBacktestOverride" in body
    # I quattro executor-params non devono piu' essere letterali fissi.
    assert '"initial_capital", "10000"' not in body
    assert '"qty_pct_of_equity", "100"' not in body
    assert '"commission_pct", "0"' not in body
    assert '"slippage_pct", "0"' not in body


def test_apply_config_to_chart_accepts_and_stores_backtest_params():
    body = _function_body(_source(), "function applyConfigToChart(")
    assert "backtestParams" in body
    assert "state.chartBacktestOverride" in body


def test_lab_apply_carries_the_labs_own_backtest_params():
    src = _source()
    start = src.index('labEl("lab-apply-btn").addEventListener')
    block = src[start:start + 1500]
    assert "backtestParams: labBacktestParams()" in block
    # niente piu' il vecchio giro a vuoto sui campi del form nascosto
    assert "syncField" not in block


def test_saving_to_archive_sends_the_real_backtest_params_not_empty():
    src = _source()
    start = src.index("async function saveLabToArchive(")
    block = src[start:start + 1200]
    assert "backtest_params: labBacktestParams()" in block
    assert "backtest_params: {}" not in block


def test_manual_ticker_search_resets_the_override():
    src = _source()
    start = src.index('el("search-form").addEventListener("submit"')
    block = src[start:start + 700]
    assert "state.chartBacktestOverride = null" in block


def test_switching_strategy_from_the_toolbar_resets_the_override():
    src = _source()
    start = src.index('el("active-strategy-select").addEventListener("change"')
    block = src[start:start + 400]
    assert "state.chartBacktestOverride = null" in block


def test_applying_an_archive_entry_without_saved_backtest_params_resets_too():
    """Le voci salvate prima di questo fix hanno backtest_params vuoto: per
    quelle applicare deve tornare ai valori puliti, non lasciare in piedi
    l'override di un'altra azione precedente."""
    body = _function_body(_source(), "function applyArchiveEntry(")
    assert "state.chartBacktestOverride = null" in body
