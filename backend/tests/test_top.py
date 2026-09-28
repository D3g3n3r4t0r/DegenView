"""Top 15/25/50: the gem board only, by score (main.onchain_top)."""
import asyncio

from app import main


def test_only_ranked_projects_by_score(monkeypatch):
    monkeypatch.setattr(main.settings, "onchain_enabled", True)
    board = [{"chain": "solana", "token_address": f"B{i}", "symbol": f"B{i}", "score": s} for i, s in enumerate([70, 90, 80])]
    monkeypatch.setattr(main.onchain_leaderboard, "board", lambda: {"entries": board})
    monkeypatch.setattr(main.onchain_projects_db, "search",
                        lambda *a, **k: {"items": [{"chain": "solana", "token": "D0", "symbol": "D0", "score": 99}]})
    out = asyncio.run(main.onchain_top(n=15, user=None))
    assert [e["symbol"] for e in out["entries"]] == ["B1", "B2", "B0"]
    assert out["on_board"] == 3 and all(e["on_board"] for e in out["entries"])
    assert len(asyncio.run(main.onchain_top(n=2, user=None))["entries"]) == 2
