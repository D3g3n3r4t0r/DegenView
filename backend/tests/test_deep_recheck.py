import asyncio
import json
import time

import pytest

from app import free_ai
from app.trading.onchain import coordinated_sells, deep_recheck, depth, leaderboard, projects_db, scout_recheck


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(deep_recheck, "_STORE", tmp_path / "deep.json")
    deep_recheck.reset_for_tests()
    monkeypatch.setattr(free_ai, "keys", lambda: {"groq": "k"})
    monkeypatch.setattr(scout_recheck, "gather", _fake_gather({}))
    monkeypatch.setattr(depth, "analyze_tokenomics", _fake_tokenomics(_TOK))
    yield
    deep_recheck.reset_for_tests()


def _row(tok):
    projects_db.upsert({"chain": "solana", "token_address": tok, "symbol": "T"}, "test", now=100)
    projects_db.record({"chain": "solana", "token_address": tok, "pillars": {}}, "studied", why="DeepSeek review: old",
                       score=40, now=100)


def _fake_ask(payload):
    async def ask(messages, **kw):
        return json.dumps(payload)
    return ask


_TOK = {"key": "tokenomics", "score": 70, "facts": {"top10_pct": 20, "creator_pct": 0, "mint": False, "freeze": False},
        "flags": ["linked wallets hold 40% of supply (807 wallets)"]}


def _fake_gather(extra):
    async def gather(entry, item, client):
        return {"found": [], "pages": [], "checked": [{"source": "site", "result": "found", "detail": "x"}],
                "snippets": [], "gecko": None, **extra}
    return gather


def _fake_tokenomics(pillar):
    async def analyze(chain, token, client, **kw):
        return pillar
    return analyze


OK = {"verdict": "ok", "confidence": 0.9, "meme": False, "impersonates": None, "product": "a DEX aggregator",
      "reason": "live app", "summary": "A working aggregator."}


def test_a_kept_token_shows_areas_and_the_ai_opinion(monkeypatch):
    _row("tok1")
    res = asyncio.run(deep_recheck.run("solana", "tok1", None, ask=_fake_ask(OK)))
    assert res["v"] == 2 and res["keep"] is True and res["effect"] == "not_on_board"
    keys = [a["key"] for a in res["areas"]]
    assert keys[:3] == ["holders", "contract", "pool"] and res["ai"]["product"] == "a DEX aggregator"
    # RugCheck's linked wallets never reach the contract area: the holders are the cluster report's.
    contract = next(a for a in res["areas"] if a["key"] == "contract")
    assert "linked" not in contract["line"] and contract["status"] == "good"
    assert next(a for a in res["areas"] if a["key"] == "holders")["status"] == "unknown"
    row = projects_db.get("solana", "tok1")
    assert not (row.get("why") or "").startswith("DeepSeek")


def test_a_serious_cluster_report_drops_and_the_ai_cannot_save_it(monkeypatch):
    _row("tok2")
    monkeypatch.setattr(coordinated_sells, "ai_facts", lambda chain, token, now=None: {
        "risk": 96, "risk_reasons": [], "linked_clusters": 1, "linked_wallets": 23, "linked_supply_pct": 19.1,
        "biggest_cluster_pct": 19.1, "links": ["same_slot"], "top_holders_supply_pct": None, "sell_waves": 0,
        "sell_waves_7d": 0, "supply_sold_in_waves_pct": 0, "last_wave_hours_ago": None, "report_age_hours": 1,
        "coverage": None})
    res = asyncio.run(deep_recheck.run("solana", "tok2", None, ask=_fake_ask(OK)))
    assert res["keep"] is False and res["by"] == "holders" and "19.1%" in res["reason"]
    assert projects_db.get("solana", "tok2")["why"].startswith("Re-check:")


def test_a_confident_copy_drops_and_a_later_keep_restores_the_rank(monkeypatch):
    projects_db.upsert({"chain": "solana", "token_address": "tok3", "symbol": "T"}, "test", now=100)
    projects_db.record({"chain": "solana", "token_address": "tok3", "pillars": {}}, "studied", score=80, now=100)
    projects_db.set_standing("solana", "tok3", "ranked", 80, 4)
    copy = {**OK, "impersonates": "Apple", "reason": "uses the Apple name"}
    res = asyncio.run(deep_recheck.run("solana", "tok3", None, ask=_fake_ask(copy), limited=False))
    assert res["keep"] is False and res["by"] == "ai" and res["dropped_from"] == {"status": "ranked", "rank": 4}
    assert projects_db.get("solana", "tok3")["status"] == "studied"
    res = asyncio.run(deep_recheck.run("solana", "tok3", None, now=time.time() + 60, ask=_fake_ask(OK), limited=False))
    row = projects_db.get("solana", "tok3")
    assert res["keep"] is True and row["status"] == "ranked" and row["rank"] == 4 and not row.get("why")


def test_no_ai_answer_means_a_verdict_from_the_facts(monkeypatch):
    _row("tok4")

    async def ask(messages, **kw):
        return "not json"
    res = asyncio.run(deep_recheck.run("solana", "tok4", None, ask=ask))
    assert res["ai"] is None and res["keep"] is True and res["by"] == "facts"


def test_board_entry_gets_deep_review_and_the_effect(monkeypatch):
    entry = {"chain": "solana", "token_address": "tok5", "name": "T", "symbol": "T", "pillars": {},
             "review": {"keep": False, "reason": "old", "at": time.time() - 100}}
    leaderboard._entries["solana:tok5"] = entry

    async def retok(chain, token, client):
        return _TOK
    monkeypatch.setattr(leaderboard, "retokenomics", retok)
    try:
        res = asyncio.run(deep_recheck.run("solana", "tok5", None, ask=_fake_ask(OK)))
        assert leaderboard._entries["solana:tok5"]["review"]["deep"] is True
        assert res["effect"] == "back" and res["before"]["keep"] is False
    finally:
        leaderboard._entries.pop("solana:tok5", None)


def test_second_call_within_cooldown_and_daily_max(monkeypatch):
    _row("tok6")
    asyncio.run(deep_recheck.run("solana", "tok6", None, ask=_fake_ask(OK)))
    with pytest.raises(deep_recheck.TooSoon):
        asyncio.run(deep_recheck.run("solana", "tok6", None, ask=_fake_ask(OK)))
    _row("tok7")
    deep_recheck._state["calls"][time.strftime("%Y-%m-%d", time.gmtime())] = deep_recheck.DAILY_MAX
    with pytest.raises(deep_recheck.TooSoon):
        asyncio.run(deep_recheck.run("solana", "tok7", None, ask=_fake_ask(OK)))


def test_double_tap_asks_once(monkeypatch):
    _row("tok8")
    calls = []

    async def ask(messages, **kw):
        calls.append(1)
        await asyncio.sleep(0.01)
        return json.dumps(OK)

    async def both():
        return await asyncio.gather(deep_recheck.run("solana", "tok8", None, ask=ask),
                                    deep_recheck.run("solana", "tok8", None, ask=ask), return_exceptions=True)
    res = asyncio.run(both())
    assert len(calls) == 1 and sum(isinstance(r, deep_recheck.TooSoon) for r in res) == 1


def test_account_holders_recheck_whenever_they_want(monkeypatch):
    _row("tok9")
    now = time.time()
    deep_recheck._state["calls"][time.strftime("%Y-%m-%d", time.gmtime(now))] = deep_recheck.DAILY_MAX
    asyncio.run(deep_recheck.run("solana", "tok9", None, now=now, ask=_fake_ask(OK), limited=False))
    with pytest.raises(deep_recheck.TooSoon):   # a double tap
        asyncio.run(deep_recheck.run("solana", "tok9", None, now=now + 2, ask=_fake_ask(OK), limited=False))
    assert deep_recheck.wait_s("solana", "tok9", now + 3600, limited=False) == 0
    assert deep_recheck.wait_s("solana", "tok9", now + 3600) > 0


def test_progress_shows_the_real_steps(monkeypatch):
    _row("tok10")
    asyncio.run(deep_recheck.run("solana", "tok10", None, ask=_fake_ask(OK), limited=False))
    p = deep_recheck.progress("solana", "tok10")
    labels = [s["label"] for s in p["steps"]]
    assert p["running"] is False and all(s["state"] == "done" for s in p["steps"])
    assert labels[0] == "Loading the project and its last review"
    assert "Reading the wallet cluster report" in labels and "Asking the AI about the product" in labels
    assert labels[-1] == "Verdict" and not any("DeepSeek" in x for x in labels)
    assert scout_recheck.PROGRESS.get() is None


def test_old_results_still_read():
    res = {"problems": [{"text": "Pool holds 2% of the cap", "evidence": "q"}],
           "claims": [{"text": "single author", "status": "confirmed"}], "cleared": 0, "unverified": 0, "confirmed": 1}
    out = deep_recheck.tidy(res)
    assert out["confirmed"] == 1 and out["problems"][0]["text"] == "Pool holds 2% of the cap"


def test_weekly_sweep_walks_the_board_once_a_week():
    t0 = 1_800_000_000.0
    keys = ["solana:a", "robinhood:b"]
    assert deep_recheck.next_in_sweep(keys, t0) == "solana:a"
    deep_recheck._sweep_done("solana:a")
    assert deep_recheck.next_in_sweep(keys, t0 + 90) == "robinhood:b"
    deep_recheck._sweep_done("robinhood:b")
    assert deep_recheck.next_in_sweep(keys, t0 + 180) is None
    assert deep_recheck.next_in_sweep(keys + ["base:c"], t0 + 86400) is None
    assert deep_recheck.next_in_sweep(keys + ["base:c"], t0 + deep_recheck.WEEK_S) == "solana:a"
    assert deep_recheck._state["sweep"]["keys"] == keys + ["base:c"]


def test_a_stalled_sweep_restarts_after_a_week():
    t0 = 1_800_000_000.0
    assert deep_recheck.next_in_sweep(["solana:a"], t0) == "solana:a"
    assert deep_recheck.next_in_sweep(["base:z"], t0 + deep_recheck.WEEK_S) == "base:z"
