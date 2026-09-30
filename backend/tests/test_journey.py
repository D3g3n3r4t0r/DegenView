import hashlib

from app.notify import deepseek_calls, deepseek_desk
from app.trading.onchain import journey, projects_db, strategy_lab

TOKEN = "So1AbCdEfGh123"


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(deepseek_desk, "_STORE_FILE", tmp_path / "desk.json")
    deepseek_desk.reset_for_tests()
    monkeypatch.setattr(strategy_lab, "_results", {})
    projects_db.upsert({"chain": "solana", "token_address": TOKEN, "symbol": "DREG"}, "jupiter", now=100)
    deepseek_desk.note("scan", "Checked DREG", chain="solana", token=TOKEN, symbol="DREG", now=110)
    deepseek_desk.note("study", "Studied DREG", chain="solana", token=TOKEN, now=120)
    deepseek_desk.note("study", "Other token", chain="solana", token="Other111", now=121)
    deepseek_calls.log(kind="code", purpose="code", subject=f"solana:{TOKEN.lower()}", body={"messages": []},
                       content="{}", usage={}, ms=5, now=130)
    projects_db.record({"chain": "solana", "token_address": TOKEN}, "ranked", why="solid", score=71, now=140)
    strategy_lab._results[f"solana:{TOKEN}"] = {"at": 150, "pair": "p", "backtests": {}}


def test_journey_orders_real_records_and_chains_hashes(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    j = journey.journey("solana", TOKEN)
    assert [s["node"] for s in j["steps"]] == ["scan", "scan", "study", "code", "decision", "backtest"]
    link = journey.GENESIS
    for s in j["steps"]:
        assert s["id"] == hashlib.sha256(s["record"].encode()).hexdigest()
        link = hashlib.sha256((link + s["id"]).encode()).hexdigest()
        assert s["link"] == link
    assert j["head"] == link and "Other token" not in str(j)


def test_resolve_by_ticker_any_case_and_by_address(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert [m["token"] for m in journey.resolve("$dreg")] == [TOKEN]
    assert journey.resolve(TOKEN)[0]["symbol"] == "DREG"
    assert journey.resolve("nope") == [] and journey.resolve("") == []
