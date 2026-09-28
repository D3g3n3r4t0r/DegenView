import asyncio

from app import main
from app.trading.onchain import ai_review, outcomes


def test_deepseek_context_includes_reviews(monkeypatch):
    monkeypatch.setattr(ai_review, "_state",
                        {"reviews": [{"at": 1790000000, "summary": "S1", "actions": ["A1"]}]})
    out = asyncio.run(main._deepseek_context("nobody"))
    assert "S1" in out
    assert "A1" in out


def test_deepseek_context_survives_lessons_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no data")

    monkeypatch.setattr(outcomes, "lessons", boom)
    out = asyncio.run(main._deepseek_context("nobody"))
    assert isinstance(out, str)
