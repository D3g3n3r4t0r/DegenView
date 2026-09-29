"""The agent log shows how DeepSeek reasons, not only what it touched.

Lorenzo, 28/09: "voglio che si veda il log su quello su cui sta lavorando,
un log preciso, non soltanto cose generiche, voglio vedere come ragiona".
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.notify import deepseek_desk
from app.trading.onchain import judge


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(deepseek_desk, "_STORE_FILE", tmp_path / "desk.json")
    monkeypatch.setattr(judge, "_FILE", tmp_path / "judge.json")
    monkeypatch.setattr(judge, "_cache", {})
    monkeypatch.setattr(judge, "_calls", {})
    deepseek_desk.reset_for_tests()
    yield
    deepseek_desk.reset_for_tests()


def test_steps_are_kept_short_and_few():
    deepseek_desk.note("judge", "X", steps=[str(i) * 300 for i in range(12)], outcome="o" * 300)
    item = deepseek_desk.log()[0]
    assert len(item["steps"]) == 8 and all(len(s) == 200 for s in item["steps"])
    assert len(item["outcome"]) == 200


def test_log_pages_newest_first():
    for i in range(5):
        deepseek_desk.note("scan", f"n{i}", now=1000.0 + i)
    first = deepseek_desk.log(limit=2)
    assert [a["text"] for a in first] == ["n4", "n3"]
    more = deepseek_desk.log(limit=2, before=first[-1]["t"])
    assert [a["text"] for a in more] == ["n2", "n1"]


def test_judge_writes_its_reasoning():
    async def ask(messages, **_):
        return json.dumps({"verdict": "avoid", "score": 30, "confidence": 0.8,
                           "problems": ["team anonymous", "no audit"], "strengths": ["real users"],
                           "admit_reason": ""})
    e = {"chain": "solana", "token_address": "T1", "symbol": "ABC", "name": "Abc", "market_cap": 50_000,
         "liquidity_usd": 9_000, "pillars": {"github": {"score": 40}, "site": {"score": 55}, "tokenomics": {"score": 70}}}
    out = asyncio.run(judge.judge(e, "site too weak", ask=ask))
    assert out["verdict"] == "avoid"
    items = deepseek_desk.log()
    verdict, dossier = items[0], items[1]
    assert verdict["kind"] == "judge" and "avoid" in verdict["text"]
    assert verdict["steps"][:2] == ["✗ team anonymous", "✗ no audit"] and verdict["steps"][2] == "✓ real users"
    assert verdict["outcome"] == "vetoed"
    assert any(s.startswith("Pillars: github 40, site 55, tokenomics 70") for s in dossier["steps"])


def test_done_counts_every_note_by_kind_for_today():
    """Lorenzo, 28/09: "voglio avere la sensazione che la gente stia lavorando
    costantemente". The Agent page counts all work, not only LLM calls."""
    for _ in range(3):
        deepseek_desk.note("backtest", "Backtested X", now=86_400 * 10 + 5)
    deepseek_desk.note("study", "Studied Y", now=86_400 * 10 + 6)
    deepseek_desk.note("backtest", "yesterday", now=86_400 * 9 + 5)
    done = deepseek_desk.activity(now=86_400 * 10 + 7)["done"]
    assert done == {"backtest": 3, "study": 1}


def test_a_study_lands_in_the_agent_log_with_its_score():
    from app.trading.onchain import leaderboard
    e = {"symbol": "DREGG", "chain": "solana", "token_address": "T",
         "pillars": {"github": {"score": 91.4}, "site": {"detail": "no site"}},
         "overall": {"score": 77.6, "fatal": None, "pending": []}}
    leaderboard._note_study(e, ["github", "site"])
    item = deepseek_desk.log()[0]
    assert item["kind"] == "study" and item["text"] == "Studied DREGG: GitHub, site"
    assert item["steps"] == ["GitHub: 91", "site: no site"] and item["outcome"] == "score 78"
    e["overall"] = {"score": 0, "fatal": "renounced? no"}
    leaderboard._note_study(e, ["github"])
    assert deepseek_desk.log()[0]["outcome"].startswith("rejected: ")


def test_a_token_studied_many_times_is_one_project():
    """#366: 27849 study notes against 893 projects were never comparable."""
    now = 86_400 * 10 + 5
    for _ in range(30):
        deepseek_desk.note("study", "Studied X", now=now, chain="solana", token="A")
    deepseek_desk.note("study", "Studied Y", now=now, chain="base", token="A")
    deepseek_desk.note("backtest", "Backtested X", now=now)
    act = deepseek_desk.activity(now=now + 1)
    assert act["done"] == {"study": 31, "backtest": 1}
    assert act["distinct"] == {"study": 2}


def test_ai_calls_and_tokens_stay_apart_from_notes():
    now = 86_400 * 10 + 5
    deepseek_desk.record("research", 1000, 200, now=now)
    deepseek_desk.note("research", "Judging X", now=now)
    act = deepseek_desk.activity(now=now + 1)
    assert act["today"] == {"research": 1} and act["tokens"] == 1200
    assert act["done"] == {"research": 1}
