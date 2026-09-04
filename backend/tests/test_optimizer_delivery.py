"""Cosa succede quando la ricerca finisce e nessuno sta guardando.

La ricerca gira sul server, quindi chiudere Safari o perdere la linea non la
ferma. Ma finora il risultato viveva solo nella risposta a chi era rimasto
collegato: chi chiudeva perdeva nove minuti di lavoro. Ora viene archiviato e
annunciato — questi test tengono ferme le due cose.
"""

from __future__ import annotations

import pytest

from app import archive
from app import main
from app.main import DataUsed, DeflatedSharpe, OptimizeResult, Overfitting, RegimeInfo
from app.models import BacktestResult


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_STORE_FILE", tmp_path / "archive.json")
    archive._entries.clear()


def _body(**kw) -> OptimizeResult:
    bt = BacktestResult(
        interval="1d", initial_capital=10000, final_equity=74670,
        total_return_pct=646.7, num_trades=28, win_rate_pct=46.0,
        max_drawdown_pct=-32.4, profit_factor=2.1, equity_curve=[], trades=[],
        sharpe_ratio=1.2,
    )
    base = dict(
        params={"len": 136, "average": "EMA"}, backtest=bt, trials_evaluated=10290,
        out_of_sample_return_pct=-3.1, overfitted=True, mode="plateau",
        data_used=DataUsed(interval="1d", candles=1439, chart_interval="1d",
                           differs_from_chart=False, note=""),
        deterministic=False, chosen_branch="trendfilter=True volatilityfilter=False",
        regime=RegimeInfo(passed=False, reason="Nessun edge misurabile", verdict=""),
        deflated_sharpe=DeflatedSharpe(sharpe=1.2, deflated=0.0, sharpe_threshold=3.9,
                                       n_trials=10290, acceptable=False),
        overfitting=Overfitting(pbo=0.56, acceptable=False, n_candidates=12, n_splits=924),
    )
    base.update(kw)
    return OptimizeResult(**base)


def _archive(body=None):
    return main._archive_optimizer_result(
        "u1", "kasusdt", "crypto", "mexc", "1d", "Lorenzo (trend-follower)",
        "plateau", body or _body(),
    )


# --- l'archiviazione ------------------------------------------------------


def test_the_result_is_archived_ready_to_read():
    entry = _archive()
    stored = archive.get(entry["id"], "u1")
    assert stored["state"] == "pronto", "una voce 'in corso' costringerebbe a un secondo backtest"
    assert stored["metrics"]["total_return_pct"] == 646.7
    assert stored["params"]["len"] == 136
    assert stored["source"] == "ottimizzazione"


def test_the_numbers_are_the_ones_just_measured():
    """Rieseguire il backtest rifarebbe lo stesso lavoro e potrebbe dare un
    numero diverso, perché nel frattempo il feed si è allungato."""
    body = _body()
    stored = archive.get(_archive(body)["id"], "u1")
    assert stored["metrics"]["num_trades"] == body.backtest.num_trades
    assert stored["metrics"]["max_drawdown_pct"] == body.backtest.max_drawdown_pct


def test_how_the_parameters_were_reached_is_stored_too():
    """Due risultati con lo stesso rendimento — uno enumerato e uno sorteggiato,
    uno con il gate superato e uno no — non sono la stessa cosa."""
    o = archive.get(_archive()["id"], "u1")["optimizer"]
    assert o["mode"] == "plateau"
    assert o["evaluations"] == 10290
    assert o["regime_passed"] is False
    assert o["deterministic"] is False
    assert o["pbo"] == 0.56


def test_a_clean_run_carries_no_warnings():
    body = _body(
        overfitted=False, deterministic=True, out_of_sample_return_pct=12.0,
        regime=RegimeInfo(passed=True, reason="Regime compatibile", verdict=""),
        deflated_sharpe=DeflatedSharpe(sharpe=2.0, deflated=0.99, sharpe_threshold=1.1,
                                       n_trials=400, acceptable=True),
        overfitting=Overfitting(pbo=0.05, acceptable=True, n_candidates=12, n_splits=924),
    )
    o = archive.get(_archive(body)["id"], "u1")["optimizer"]
    assert o["regime_passed"] is True
    assert o["deterministic"] is True


# --- il riepilogo su Telegram ---------------------------------------------


def _summary(body=None) -> str:
    return main._optimizer_summary("kasusdt", "Lorenzo (trend-follower)", "plateau",
                                   body or _body())


def test_the_summary_leads_with_the_numbers():
    text = _summary()
    assert "KASUSDT" in text
    assert "+646.7%" in text and "28 trade" in text
    assert "10290 backtest" in text


def test_the_summary_carries_the_verdicts_not_just_the_return():
    """Un +646% con il gate non superato e affidabilità zero è un numero da non
    usare: mandare solo il primo dei tre lo farebbe sembrare un risultato."""
    text = _summary()
    assert "Gate di regime non superato" in text
    assert "Affidabilità" in text
    assert "Sovra-ottimizzazione" in text
    assert "sovradattato" in text
    assert "non è riproducibile" in text


def test_a_clean_run_reads_clean():
    body = _body(
        overfitted=False, deterministic=True, out_of_sample_return_pct=12.0,
        regime=RegimeInfo(passed=True, reason="ok", verdict=""),
        deflated_sharpe=DeflatedSharpe(sharpe=2.0, deflated=0.99, sharpe_threshold=1.1,
                                       n_trials=400, acceptable=True),
        overfitting=Overfitting(pbo=0.05, acceptable=True, n_candidates=12, n_splits=924),
    )
    text = _summary(body)
    assert "⚠️" not in text
    assert "+12.0%" in text


def test_the_summary_says_where_to_find_it():
    assert "archivio" in _summary().lower()


def test_a_run_without_an_out_of_sample_figure_does_not_invent_one():
    text = _summary(_body(out_of_sample_return_pct=None, overfitted=False))
    assert "Fuori campione" not in text
