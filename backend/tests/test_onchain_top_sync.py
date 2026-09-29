"""The Top is the ranking (Lorenzo, 29/09: HATCHER "Studied, excluded" and
first on the podium), and DeepSeek audits the two for contradictions."""
import asyncio
import json
import time

import pytest

from app.trading.onchain import consistency, judge, leaderboard as lb, projects_db as db


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    from app.notify import deepseek_desk
    monkeypatch.setattr(deepseek_desk, "_STORE_FILE", tmp_path / "desk.json")
    monkeypatch.setattr(consistency, "_FILE", tmp_path / "consistency.json")
    monkeypatch.setattr(judge, "_FILE", tmp_path / "judge.json")
    monkeypatch.setattr(judge, "_cache", {})
    lb.reset_for_tests()
    consistency.reset_for_tests()
    deepseek_desk.reset_for_tests()
    yield
    lb.reset_for_tests()
    consistency.reset_for_tests()
    deepseek_desk.reset_for_tests()


def _row(tok: str, score: float, why: str = "", status: str = "studied", now: float | None = None) -> None:
    now = now or time.time()
    db.upsert({"chain": "solana", "token_address": tok, "symbol": tok.upper(), "name": f"{tok} project",
               "market_cap": 400_000, "liquidity_usd": 50_000}, "x", now)
    db.record({"chain": "solana", "token_address": tok, "rank": 3 if status == "ranked" else None},
              status, why, score, now=now)


def _db_top():
    import app.main as m
    return [e["symbol"] for e in m._top_entries(50) if not e["on_board"]]


def test_only_deepseek_keeps_a_studied_row_out_of_the_top():
    # Band limits must not empty the Top (Lorenzo, 29/09: 2 tokens left).
    _row("hatch", 91, "above $100k without excellent pillars")
    _row("drop", 85, "DeepSeek review: parody of a brand")
    _row("clean", 70)
    assert _db_top() == ["HATCH", "CLEAN"]


def test_the_database_status_follows_the_top():
    import app.main as m
    _row("good", 80)
    _row("admit", 90, "tokenomics too weak (40)")
    _row("old", 60, "", status="ranked")       # ranked once, now out of the Top
    _row("bad", 95, "DeepSeek review: dropped")
    judge._cache["solana:admit"] = {"score": 85, "verdict": "watch", "confidence": 0.7, "at": time.time()}
    lb.set_top_source(lambda n: [e for e in m._top_entries(n) if e["symbol"] != "OLD"])
    lb.sync_top(time.time())
    admit, good, old, bad = (db.get("solana", t) for t in ("admit", "good", "old", "bad"))
    assert (admit["status"], admit["rank"], admit["why"]) == ("ranked", 1, None)
    assert (good["status"], good["rank"]) == ("ranked", 2)
    assert (old["status"], old["rank"]) == ("studied", None)
    assert bad["status"] == "studied" and bad["why"]
    assert db.search(status="ranked")["total"] == 2
    # Nothing changed: the second sync writes nothing.
    assert lb.sync_top(time.time()) == 0


def test_board_standing_uses_the_top_once_synced():
    assert lb._place("solana:INmint", 1) == ("ranked", 1)      # before any sync: the board's order
    lb._state["top_synced_at"] = time.time()
    lb._top_rank["solana:INmint"] = 4
    assert lb._place("solana:INmint", 1) == ("ranked", 4)
    assert lb._place("solana:OUTmint", 1) == ("studied", None)


def test_consistency_audit_reports_and_requeues_at_most_five(monkeypatch):
    now = time.time()
    for i in range(8):
        _row(f"t{i}", 90 - i)
    top = [{"chain": "solana", "token_address": f"t{i}", "symbol": f"T{i}", "score": 90 - i,
            "market_cap": 400_000, "liquidity_usd": 50_000, "on_board": False} for i in range(8)]
    seen = {}

    async def ask(messages, kind="", **_):
        seen["kind"], seen["table"] = kind, messages[1]["content"]
        return json.dumps({"issues": [*({"id": f"r{i}", "problem": "status studied in the Top", "action": "recheck"}
                                        for i in range(1, 9)),
                                      {"id": "r99", "problem": "unknown row", "action": "recheck"},
                                      {"id": "r2", "problem": "copy of T0", "action": "report"}]})

    requeued = []
    issues = asyncio.run(consistency.step(top, now, ask=ask,
                                          requeue=lambda c, t: requeued.append(t) or True))
    assert seen["kind"] == "consistency" and "T0" in seen["table"]
    assert len(issues) == 9 and all(i["id"] != "r99" for i in issues)
    assert len(requeued) == consistency.MAX_RECHECK
    assert consistency.last_run()["issues"][0]["symbol"] == "T0"
    from app.notify import deepseek_desk
    assert sum(1 for a in deepseek_desk.log(200) if a["kind"] == "consistency") >= 10
    # The gap holds: no second call within EVERY_S.
    assert asyncio.run(consistency.step(top, now + 60, ask=ask)) == []
    assert consistency.due(now + consistency.EVERY_S)


def test_requeue_puts_a_database_row_back_in_the_queue():
    _row("again", 70)
    assert db.get("solana", "again")["next_check"] > 0
    assert lb.requeue("solana", "again")
    assert db.get("solana", "again")["next_check"] == 0


def test_a_rejected_row_is_lifted_when_its_entry_has_no_fatal_pillar():
    """BV7X: rejected under an old check, its working-set entry was fine, and set_standing skips rejected rows."""
    from app.trading.onchain import depth
    _row("bv", 70, "tokenomics: a single wallet holds 41%", status="rejected")
    pillars = {"github": {"score": None, "facts": {"missing": True}, "flags": [], "fatal": ""},
               "site": {"score": 73, "facts": {}, "flags": [], "fatal": ""},
               "tokenomics": {"score": 67, "facts": {}, "flags": [], "fatal": ""}}
    lb._entries["solana:bv"] = {"chain": "solana", "token_address": "bv", "symbol": "BV", "name": "bv", "source": "x",
                                "market_cap": 400_000, "liquidity_usd": 50_000, "found_at": time.time(),
                                "pillars": pillars, "checked_at": {}, "rank": None,
                                "overall": depth.overall(pillars)}
    lb._sync_database([])
    assert db.get("solana", "bv")["status"] == "studied"


def test_lower_case_evm_rows_get_their_market_from_checksum_answers():
    """DexScreener answers 0xAbC..., the CoinGecko list stores 0xabc...: AUREON never got a cap."""
    tok = "0xd293291060334d42e5dbea6fb854c231af527777"
    db.upsert({"chain": "robinhood", "token_address": tok, "symbol": "AUREON", "name": "AUREON"}, "coingecko-list", 1.0)
    pair = {"baseToken": {"address": "0xd293291060334D42E5DBEa6fb854C231AF527777"}, "marketCap": 92_424,
            "liquidity": {"usd": 53_215}, "volume": {"h24": 10}, "priceUsd": "0.1", "pairCreatedAt": 1_700_000_000_000}
    db.apply_pairs("robinhood", [tok], [pair], 2.0)
    row = db.get("robinhood", tok)
    assert row["mcap"] == 92_424 and row["liq"] == 53_215
    # A row stamped empty before the fix is asked again.
    db.upsert({"chain": "robinhood", "token_address": "0xabc", "symbol": "X", "name": "X"}, "coingecko-list", 1.0)
    db.set_market("robinhood", "0xabc", now=3.0)
    assert db.reset_empty_market() >= 1 and db.get("robinhood", "0xabc")["market_at"] is None


def test_dexscreener_links_fill_a_row_without_website_or_github():
    """AUREON had a cap but no website: it waited for a CoinGecko page and was never analysed."""
    tok = "0xaaaa000000000000000000000000000000000001"
    db.upsert({"chain": "robinhood", "token_address": tok, "symbol": "LNK", "name": "LNK"}, "coingecko-list", 1.0)
    pair = {"baseToken": {"address": tok}, "marketCap": 500_000, "liquidity": {"usd": 60_000},
            "info": {"websites": [{"url": "https://lnk.xyz"}], "socials": [{"type": "github", "url": "https://github.com/lnk/core"}]}}
    db.apply_pairs("robinhood", [tok], [pair], 2.0)
    row = db.get("robinhood", tok)
    assert row["website"] == "https://lnk.xyz" and row["github"] == "https://github.com/lnk/core"
    assert [r["token"] for r in db.due_for_analysis(10)] == [tok]
    # Rows that got a cap but no links are asked again once.
    db.upsert({"chain": "robinhood", "token_address": "0xbbbb", "symbol": "N", "name": "N"}, "coingecko-list", 1.0)
    db.set_market("robinhood", "0xbbbb", mcap=400_000, liq=50_000, now=3.0)
    assert db.reset_linkless_market() >= 1 and db.get("robinhood", "0xbbbb")["market_at"] is None
