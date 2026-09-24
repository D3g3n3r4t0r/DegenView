"""La memoria del radar. Lorenzo, dopo VISE: "dobbiamo implementare una
specie di coscienza, imparare dai segnali, da cosa effettivamente succede,
e migliorare il sistema"."""
from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.config import settings
from app.trading.onchain import legit, outcomes

T0 = 1_790_000_000.0
H = 3600.0


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(outcomes, "_STORE_FILE", tmp_path / "outcomes.json")
    outcomes.reset_for_tests()
    yield
    outcomes.reset_for_tests()


def _item(token="Tok", *, security=90, github=80, cap=80_000, liq=20_000, chain="solana"):
    return {"chain": chain, "symbol": token.upper(), "name": token, "token_address": token, "pair_address": f"P{token}",
            "market_cap": cap, "liquidity_usd": liq, "age_hours": 12,
            "checks": [{"key": "security", "ok": True, "score": security},
                       {"key": "github", "ok": True, "score": github},
                       {"key": "gem", "ok": True}],
            "report": {"score": (security + github) // 2}}


def test_journal_keeps_the_strongest_decision_and_its_moment():
    assert outcomes.observe(_item(), "rejected", T0, "nome da meme", "radar", now=T0)
    assert outcomes.observe(_item(), "rejected", T0 + H, now=T0 + H) is None
    e = outcomes.observe(_item(), "proposed", T0 + 2 * H, now=T0 + 2 * H)
    assert e["decision"] == "proposed" and e["previous"] == "rejected" and e["at"] == T0 + 2 * H
    assert e["features"]["checks"] == {"security": {"ok": True, "score": 90}, "github": {"ok": True, "score": 80}}
    assert e["features"]["liq_mcap"] == 0.25
    assert outcomes.observe({**_item("x"), "pair_address": ""}, "listed") is None


def test_holder_concentration_is_learned_in_the_right_direction():
    for i in range(30):
        rug = i % 3 == 0
        it = _item(f"h{i}")
        it["checks"][0]["facts"] = {"top_holder_pct": 12.0 if rug else 3.0, "top10_pct": 30.0 if rug else 15.0}
        e = outcomes.observe(it, "listed", T0, now=T0)
        assert e["features"]["top_holder_pct"] in (12.0, 3.0)
        outcomes.apply_sample(e, 1.0, 20_000, T0)
        outcomes.apply_sample(e, 0.05 if rug else 1.05, 20_000, T0 + outcomes.HORIZON_S)
    sig = {s["key"]: s for s in outcomes.signals(T0 + outcomes.HORIZON_S)}
    assert sig["top_holder_pct"]["rug_auc"] == 1.0 and sig["top_holder_pct"]["verdict"] == "prevede i rug"


def test_liquidity_pulled_is_a_rug_even_if_price_holds():
    e = outcomes.observe(_item(), "listed", T0, now=T0)
    outcomes.apply_sample(e, 1.0, 20_000, T0)
    outcomes.apply_sample(e, 1.1, 15_000, T0 + H)
    assert outcomes.outcome(e, T0 + H) is None
    outcomes.apply_sample(e, 0.9, 3_000, T0 + 2 * H)
    assert e["rug"] and e["closed"] and "liquidità" in e["rug_why"]
    assert outcomes.outcome(e) == "rug" and outcomes.rug_label(e) is True


def test_price_collapse_and_vanished_pool_are_rugs():
    a = outcomes.observe(_item("a"), "listed", T0, now=T0)
    outcomes.apply_sample(a, 1.0, 20_000, T0)
    outcomes.apply_sample(a, 0.07, 19_000, T0 + 600)     # VISE: -93% in pochi minuti
    assert a["rug"] and a["rug_why"].startswith("prezzo")
    b = outcomes.observe(_item("b"), "listed", T0, now=T0)
    outcomes.apply_sample(b, 1.0, 20_000, T0)
    for i in range(outcomes.MISSING_TICKS):
        outcomes.apply_sample(b, None, None, T0 + (i + 1) * 600)
    assert b["rug_why"] == "pool sparito"


def test_good_is_known_early_non_rug_after_three_days_flat_at_the_horizon():
    e = outcomes.observe(_item(), "proposed", T0, now=T0)
    outcomes.apply_sample(e, 1.0, 20_000, T0)
    outcomes.apply_sample(e, 1.2, 20_000, T0 + H)
    assert outcomes.rug_label(e, T0 + H) is None
    assert outcomes.rug_label(e, T0 + outcomes.RUG_FINAL_S) is False
    outcomes.apply_sample(e, 1.6, 20_000, T0 + 2 * H)
    assert outcomes.outcome(e, T0 + 2 * H) == "buono"
    f = outcomes.observe(_item("f"), "proposed", T0, now=T0)
    outcomes.apply_sample(f, 1.0, 20_000, T0)
    outcomes.apply_sample(f, 0.45, 20_000, T0 + outcomes.HORIZON_S)
    assert f["closed"] and outcomes.outcome(f) == "crollo"


def test_auc_matches_the_definition():
    assert outcomes.auc([3, 4, 1, 2], [True, True, False, False]) == 1.0
    assert outcomes.auc([1, 2, 3, 4], [True, True, False, False]) == 0.0
    assert outcomes.auc([1, 1], [True, False]) == 0.5
    assert outcomes.auc([1, 2], [True, True]) is None


def _history(n=80, informative=True, seed=0):
    """n token passati: con `informative` i rug hanno la sicurezza bassa."""
    rng = np.random.default_rng(seed)
    for i in range(n):
        rug = i % 3 == 0
        sec = (rng.uniform(20, 55) if rug else rng.uniform(60, 100)) if informative else rng.uniform(20, 100)
        e = outcomes.observe(_item(f"t{i}", security=int(sec), github=int(rng.uniform(40, 100))),
                             "listed", T0, now=T0)
        outcomes.apply_sample(e, 1.0, 20_000, T0)
        outcomes.apply_sample(e, 0.05 if rug else 1.05, 20_000, T0 + outcomes.HORIZON_S)


def test_model_waits_for_enough_outcomes():
    _history(20)
    m = outcomes.train(T0 + outcomes.HORIZON_S)
    assert not m["active"] and "servono" in m["why"]
    assert outcomes.judge(_item(), [], None) is None


def test_model_enters_only_when_it_predicts_out_of_sample():
    _history(90, informative=False)
    assert not outcomes.train(T0 + outcomes.HORIZON_S)["active"]
    outcomes.reset_for_tests()
    _history(90)
    m = outcomes.train(T0 + outcomes.HORIZON_S)
    assert m["active"] and m["cv_auc"] >= outcomes.MODEL_MIN_AUC
    bad = outcomes.judge(_item("new", security=25), _item("new", security=25)["checks"], {"score": 50})
    good = outcomes.judge(_item("new", security=95), _item("new", security=95)["checks"], {"score": 90})
    assert bad["ok"] is False and good["ok"] is True and bad["key"] == "memory"
    top = outcomes.signals(T0 + outcomes.HORIZON_S)[0]
    assert top["key"] == "security" and top["rug_auc"] > 0.9 and top["verdict"] == "prevede i rug"


def test_lessons_split_passed_and_rejected_and_list_the_misses():
    e = outcomes.observe(_item("vise"), "proposed", T0, now=T0)
    outcomes.apply_sample(e, 1.0, 20_000, T0)
    outcomes.apply_sample(e, 0.07, 1_000, T0 + 600)
    r = outcomes.observe(_item("moon"), "rejected", T0, "GitHub: nessun commit", now=T0)
    outcomes.apply_sample(r, 1.0, 20_000, T0)
    outcomes.apply_sample(r, 3.0, 60_000, T0 + H)
    out = outcomes.lessons(T0 + H)
    assert out["passed"]["rug"] == 1 and out["rejected"]["buono"] == 1
    assert [s["symbol"] for s in out["slipped"]] == ["VISE"]
    assert [m["symbol"] for m in out["missed"]] == ["MOON"]
    assert out["notes"][0].startswith("Passati dal filtro: 100% rug")


def test_late_entries_take_their_entry_from_the_candles():
    e = outcomes.observe(_item(), "rejected", T0, now=T0 + 10 * H)
    assert e["late"]
    idx = pd.date_range(pd.Timestamp(T0 - 1800, unit="s", tz="UTC"), periods=8, freq="15min")
    df = pd.DataFrame({"open": [5, 2, 2.1, 2, 1.5, 0.2, 0.1, 0.1], "high": [5, 2.5, 2.2, 2, 1.5, 0.3, 0.1, 0.1],
                       "low": [5, 1.9, 2, 1.8, 0.3, 0.1, 0.1, 0.1], "close": [2, 2.1, 2, 1.5, 0.2, 0.1, 0.1, 0.1]},
                      index=idx)
    outcomes.replay_candles(e, df)
    assert e["entry"] == {"price": 2.1, "liq": None, "at": T0, "from": "candles"}
    assert e["rug"] and round(e["min_ret"], 2) == -0.95
    assert outcomes.outcome(e) == "rug"


def test_collect_reads_radar_and_listings(monkeypatch):
    from app.trading.onchain import listings, radar
    monkeypatch.setattr(radar, "snapshot", lambda: {"proposals": [{**_item("p"), "found_at": T0}],
                                                    "tested": [_item("t")]})
    monkeypatch.setattr(listings, "recent", lambda: [{**_item("l"), "found_at": T0}])
    monkeypatch.setattr(listings, "rejected", lambda: [{**_item("r"), "at": T0, "reason": "meme"}])
    assert outcomes.collect(T0 + 60) == 4
    assert {e["decision"] for e in outcomes._journal.values()} == {"proposed", "tested", "listed", "rejected"}
    assert outcomes.collect(T0 + 120) == 0


def test_memory_check_blocks_only_with_the_gate_on(monkeypatch):
    check = {"key": "memory", "label": "Memoria", "ok": False, "detail": "somiglia ai rug passati: rischio 80%",
             "score": 20}
    monkeypatch.setattr(outcomes, "judge", lambda *a: dict(check))

    async def fake(*a, **k):
        return None

    async def site(*a, **k):
        return {"ok": True, "title": "Proj", "text": "a real project " * 50, "final_url": "https://p.io"}

    async def gh(*a, **k):
        return legit._check("github", "GitHub", True, "ok", 80), {"repo": "x"}

    monkeypatch.setattr(legit, "rugcheck", lambda *a: _const({"lpLockedPct": 100, "risks": []}))
    monkeypatch.setattr(legit, "goplus_solana", lambda *a: _const({"mintable": {"status": "0"}}))
    monkeypatch.setattr(legit, "fetch_site", site)
    monkeypatch.setattr(legit, "check_github", gh)
    monkeypatch.setattr(legit, "ai_review", fake)
    token = {"chain": "solana", "symbol": "PROJ", "name": "Project", "token_address": "Tok", "market_cap": 50_000}
    links = {"websites": ["https://p.io"], "socials": [{"type": "twitter", "url": "https://x.com/p"}]}

    def run():
        return asyncio.run(legit.assess(token, links, None))

    monkeypatch.setattr(settings, "onchain_memory_gate", False)
    off = run()
    assert off["status"] == "ok" and off["checks"][-1]["key"] == "memory"
    monkeypatch.setattr(settings, "onchain_memory_gate", True)
    on = run()
    assert on["status"] == "fail" and on["reason"].startswith("Memoria")


async def _value(v):
    return v


def _const(v):
    return _value(v)
