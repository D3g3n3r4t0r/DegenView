"""Il giudice di DeepSeek: parse, dossier, cache e tetto giornaliero."""
import asyncio
import json
import time

from app.trading.onchain import judge


def _entry(**item) -> dict:
    return {"chain": "solana", "token_address": "ABCmint", "symbol": "ABC", "name": "Abc", "market_cap": 50_000,
            "liquidity_usd": 20_000, "launched_at": time.time() - 30 * 86400,
            "pillars": {"github": {"score": 70, "facts": {"commits": "10"}, "flags": []},
                        "site": {"score": 60, "facts": {"summary": "we are the best"}, "flags": []},
                        "tokenomics": {"score": 65, "facts": {}, "flags": []}}, **item}


def test_parse_clamps_and_rejects():
    out = judge.parse(json.dumps({"score": 150, "verdict": "gem", "confidence": 2,
                                  "problems": ["a"], "strengths": ["b"], "admit_reason": "x"}))
    assert out["score"] == 100 and out["confidence"] == 1.0
    assert judge.parse(json.dumps({"score": 50, "verdict": "maybe"})) is None
    assert judge.parse("not json") is None


def test_dossier_wraps_project_text():
    d = judge.dossier(_entry(), "site too weak (20)")
    assert "<project_text>" in d and "</project_text>" in d
    assert "we are the best" in d
    assert "site too weak (20)" in d


def test_judge_caches_and_respects_daily_max(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "_FILE", str(tmp_path / "judge.json"))
    judge.reset_for_tests()
    calls = []

    async def ask(messages, **kw):
        calls.append(messages)
        return json.dumps({"score": 85, "verdict": "gem", "confidence": 0.8, "problems": [], "strengths": [],
                           "admit_reason": ""})

    e = _entry()
    out = asyncio.run(judge.judge(e, "site too weak (20)", ask=ask))
    assert out["score"] == 85 and len(calls) == 1
    again = asyncio.run(judge.judge(e, "site too weak (20)", ask=ask))
    assert again["score"] == 85 and len(calls) == 1

    judge.reset_for_tests()
    monkeypatch.setattr(judge, "DAILY_MAX", 0)
    assert asyncio.run(judge.judge(e, "site too weak (20)", ask=ask)) is None
    assert len(calls) == 1
