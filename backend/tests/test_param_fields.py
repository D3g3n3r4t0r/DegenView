"""
La tabella dei campi in app.js e il modello dei parametri qui devono dire la
stessa cosa.

Due modi silenziosi di sbagliare, entrambi gia' successi:

  * un campo che la pagina manda e il modello non dichiara viene scartato da
    FastAPI senza dire niente. La strategia gira con il valore di default e il
    risultato non corrisponde a quello che si legge a schermo;
  * un campo dichiarato `int` qui e disegnato con `step` in pagina invita a
    scrivere un decimale, che diventa un 422 al primo invio.

La regola e' quella usata da fieldNumber() in app.js: un campo e' intero
quando NON dichiara `step`.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.main import StrategyParamsQuery

_APP_JS = Path(__file__).resolve().parent.parent.parent / "frontend" / "static" / "app.js"


def _fields() -> dict[str, list[dict]]:
    src = _APP_JS.read_text(encoding="utf-8")
    start = src.index("const STRATEGY_PARAM_FIELDS = {")
    end = src.index("\n  };", start)
    block = src[start:end]

    out: dict[str, list[dict]] = {}
    current: str | None = None
    for line in block.splitlines():
        stripped = line.strip()
        strategy = re.match(r'^"([^"]+)":\s*\[', stripped)
        if strategy:
            current = strategy.group(1)
            out[current] = []
            continue
        entry = re.match(r'^\{\s*key:\s*"([^"]+)".*\},?$', stripped)
        if entry and current:
            out[current].append({
                "key": entry.group(1),
                "type": (re.search(r'type:\s*"([^"]+)"', stripped) or [None, "number"])[1],
                "has_step": "step:" in stripped,
            })
    return out


def test_the_table_was_actually_parsed():
    fields = _fields()
    assert set(fields) >= {"Lorenzo (trend-follower)", "Gabriele (RSI+BB reversal)"}
    assert all(v for v in fields.values())


def test_every_field_the_page_sends_exists_on_the_model():
    declared = set(StrategyParamsQuery.model_fields)
    for strategy, fields in _fields().items():
        for f in fields:
            assert f["key"] in declared, (
                f"{strategy}: '{f['key']}' non esiste su StrategyParamsQuery — "
                "FastAPI lo scarta in silenzio e la strategia gira con il default"
            )


def test_integer_params_have_no_step_and_float_params_do():
    annotations = {name: f.annotation for name, f in StrategyParamsQuery.model_fields.items()}
    for strategy, fields in _fields().items():
        for f in fields:
            if f["type"] != "number":
                continue
            ann = annotations[f["key"]]
            if ann is int:
                assert not f["has_step"], (
                    f"{strategy}: '{f['key']}' e' un intero lato server ma in pagina "
                    "dichiara uno step decimale"
                )
            elif ann is float:
                assert f["has_step"], (
                    f"{strategy}: '{f['key']}' e' un float lato server ma in pagina "
                    "non dichiara step — fieldNumber() lo arrotonderebbe"
                )
