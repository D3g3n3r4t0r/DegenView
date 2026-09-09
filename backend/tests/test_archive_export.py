"""
Segnalazione 30f3f03f: esportare in Excel dall'archivio, senza dover prima
riportare i parametri sul Laboratorio.

Non c'e' un endpoint nuovo — /api/export/backtest.xlsx gia' accetta tutto
quello che una voce d'archivio conosce (symbol, asset_type, exchange,
interval, strategy_name, params, backtest_params): il pulsante nell'archivio
costruisce la stessa richiesta che gia' fa il Laboratorio, solo con i valori
letti dalla voce salvata invece che dai campi in pagina. Questi test leggono
la struttura di app.js, come le altre verifiche sull'archivio in questo
progetto.
"""

from __future__ import annotations

from pathlib import Path

_APP_JS = Path(__file__).resolve().parent.parent.parent / "frontend" / "static" / "app.js"


def _source() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def test_the_archive_card_has_an_export_button():
    assert '"arch-export"' in _source()


def test_the_export_handler_builds_the_request_from_the_saved_entry():
    src = _source()
    start = src.index('".arch-export"')
    block = src[start:start + 1200]
    assert "/api/export/backtest.xlsx" in block
    for field in ("entry.symbol", "entry.asset_type", "entry.exchange",
                  "entry.interval", "entry.strategy_name", "entry.params",
                  "entry.backtest_params"):
        assert field in block, f"manca {field}"


def test_it_does_not_hardcode_defaults_that_would_diverge_from_the_saved_metrics():
    """Un campo omesso deve restare omesso — il server applica i suoi stessi
    default, gli stessi con cui la voce e' stata misurata. Scriverne uno fisso
    qui produrrebbe un file diverso dalle metriche gia' mostrate in pagina."""
    src = _source()
    start = src.index('".arch-export"')
    block = src[start:start + 1200]
    assert '"initial_capital"' not in block
    assert '"qty_pct_of_equity"' not in block
