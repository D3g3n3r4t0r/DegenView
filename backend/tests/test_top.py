"""Top 15/25/50: the board first, the database fills the rest (main.onchain_top)."""
import asyncio

from app import main


def test_the_database_fills_what_the_board_lacks(monkeypatch):
    monkeypatch.setattr(main.settings, "onchain_enabled", True)
    board = [{"chain": "solana", "token_address": f"B{i}", "symbol": f"B{i}", "score": 90 - i} for i in range(3)]
    monkeypatch.setattr(main.onchain_leaderboard, "board", lambda: {"entries": board})
    db = [{"chain": "solana", "token": "B0", "symbol": "B0", "score": 90}] + \
         [{"chain": "solana", "token": f"D{i}", "symbol": f"D{i}", "score": 70 - i, "why": "too old"} for i in range(40)]
    monkeypatch.setattr(main.onchain_projects_db, "search", lambda *a, **k: {"items": db})
    out = asyncio.run(main.onchain_top(n=15, user=None))
    assert len(out["entries"]) == 15 and out["on_board"] == 3
    assert [e["symbol"] for e in out["entries"][:4]] == ["B0", "B1", "B2", "D0"]
    assert out["entries"][3]["on_board"] is False and out["entries"][3]["why"] == "too old"
    assert len(asyncio.run(main.onchain_top(n=50, user=None))["entries"]) == 43
