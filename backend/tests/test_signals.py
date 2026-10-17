"""Telegram alert track record, early gems with their alerts, and the daily
Claude reviewer with its token budget."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.config import settings
from app.trading.onchain import ai_review, alert_track as at
from app.trading.onchain import leaderboard as lb

T0 = 1_790_000_000.0
H = 3600.0


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(at, "_STORE_FILE", tmp_path / "alerts.json")
    monkeypatch.setattr(ai_review, "_STORE_FILE", tmp_path / "review.json")
    at.reset_for_tests()
    ai_review.reset_for_tests()
    lb.reset_for_tests()
    yield
    lb.reset_for_tests()


def _alert(token="Frog", kind="meme"):
    return at.record({"chain": "solana", "symbol": token.upper(), "token_address": token,
                      "pair_address": f"P{token}", "market_cap": 90_000, "liquidity_usd": 20_000}, kind, T0)


def test_entry_is_the_first_price_after_the_message_and_checkpoints_fill():
    a = _alert()
    assert _alert() is None                              # once per token
    at.apply_price(a, 1.0, T0 + 20)
    for h, p in [(0.5, 1.2), (1.01, 1.5), (2.2, 0.9), (6.1, 2.0), (24.5, 3.0), (48.2, 2.5)]:
        at.apply_price(a, p, T0 + 20 + h * H)
    assert a["entry"] == 1.0
    assert a["returns"]["1"] == 0.5 and a["returns"]["2"] == -0.1 and a["returns"]["3"] == 1.0 and a["returns"]["6"] == 1.0
    assert a["returns"]["8"] == 2.0 and a["returns"]["24"] == 2.0 and a["returns"]["48"] == 1.5
    assert a["last"]["ret"] == 1.5 and a["max_ret"] == 2.0


def test_vanished_pool_is_minus_100_and_board_ranks_by_now():
    good, bad = _alert("good"), _alert("bad")
    for a, p in ((good, 1.0), (bad, 1.0)):
        at.apply_price(a, p, T0)
    at.apply_price(good, 1.4, T0 + 1.5 * H)
    at.apply_price(bad, 0.8, T0 + 1.5 * H)
    for i in range(at.GONE_AFTER):
        at.apply_price(bad, None, T0 + 2 * H + i)
    assert bad["gone"] and bad["returns"]["48"] == -1.0
    at.set_strategy("meme", "solana", "good", {"return_pct": 37.5, "label": "Trend EMA", "trades": 4})
    b = at.board("meme", now=T0 + 3 * H)
    assert [i["symbol"] for i in b["items"]] == ["GOOD", "BAD"]
    assert b["items"][0]["strategy"]["return_pct"] == 37.5 and b["strategy"]["median_pct"] == 37.5
    one = next(s for s in b["summary"] if s["h"] == 1)
    assert one["n"] == 2 and one["positive"] == 0.5


def _gem(cap, *, gh=80, site=75, tok=70, liq=8_000):
    e = {"chain": "solana", "token_address": f"T{cap}", "symbol": f"G{cap}", "name": "Gem", "source": "coingecko",
         "market_cap": cap, "liquidity_usd": liq, "launched_at": T0 - 60 * 86400, "found_at": T0,
         "pair_address": f"P{cap}", "price_usd": "0.001", "checked_at": {},
         "pillars": {"github": {"score": gh, "facts": {}}, "site": {"score": site, "facts": {}},
                     "tokenomics": {"score": tok, "facts": {}}}}
    from app.trading.onchain import depth
    e["overall"] = depth.overall(e["pillars"])
    lb._entries[lb._key("solana", e["token_address"])] = e
    return e


def test_early_gem_under_50k_with_fundamentals_is_flagged_and_alerted(monkeypatch):
    monkeypatch.setattr("time.time", lambda: T0)
    early = _gem(30_000)
    weak = _gem(35_000, tok=40)
    big = _gem(400_000, liq=60_000)
    thin = _gem(420_000)                                 # $8k of liquidity: under the $10k floor above $50k
    lb._rank()
    assert thin.get("rank") is None
    assert lb.is_early(early) and not lb.is_early(weak) and not lb.is_early(big)
    got = []

    async def hook(kind, item):
        got.append((kind, item["symbol"], item["early"]))
    lb.on_alert(hook)
    asyncio.run(lb.drain_alerts())
    assert ("early", "G30000", True) in got and not any(k == "new" for k, _, _ in got)   # "new" is the Top's
    assert not any(s == "G35000" and k == "early" for k, s, _ in got)
    got.clear()
    lb._rank()
    asyncio.run(lb.drain_alerts())
    assert got == []                                     # each alert once


def test_board_already_there_at_first_start_is_not_news(monkeypatch):
    monkeypatch.setattr("time.time", lambda: T0)
    _gem(400_000, liq=60_000)
    lb._priming = True
    lb._rank()
    lb._priming = False
    assert lb._outbox == []


class _FakeClaude:
    def __init__(self, out_tokens=900):
        self.calls = []
        self.out_tokens = out_tokens

    @property
    def messages(self):
        return self

    async def create(self, **kw):
        self.calls.append(kw)
        body = {"summary": "Poco da dire.", "actions": ["Alzare la soglia X", "B", "C", "D"]}
        return SimpleNamespace(stop_reason="end_turn", model="claude-sonnet-5",
                               usage=SimpleNamespace(input_tokens=5_000, output_tokens=self.out_tokens),
                               content=[SimpleNamespace(type="text", text=json.dumps(body))])


def test_review_counts_tokens_and_stops_at_the_daily_budget(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_daily_tokens", 30_000)
    monkeypatch.setattr(settings, "ai_review_monthly_tokens", 600_000)
    fake = _FakeClaude()
    e = asyncio.run(ai_review.review(T0, client=fake))
    assert e["actions"] == ["Alzare la soglia X", "B", "C"] and e["tokens"] == 5_900
    kw = fake.calls[0]
    assert kw["model"] == settings.ai_review_model and kw["output_config"]["format"]["type"] == "json_schema"
    assert ai_review.used_today(T0) == 5_900
    ai_review._state["usage"][ai_review._day(T0)] = 29_000
    assert asyncio.run(ai_review.review(T0 + 60, client=fake)) is None
    assert ai_review.status(T0)["error"] is None or "budget" in ai_review._state["error"]
    assert len(fake.calls) == 1
    assert "Revisione" in ai_review.telegram_text(e) and "• B" in ai_review.telegram_text(e)
    # The month cap binds too.
    ai_review._state["usage"] = {ai_review._day(T0 - 86400): 599_000}
    monkeypatch.setattr(settings, "ai_review_daily_tokens", 40_000)
    assert ai_review.budget_left(T0) <= 1_000


def test_review_needs_a_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert not ai_review.enabled()
    assert asyncio.run(ai_review.review(T0)) is None


def test_deepseek_reviewer_reads_like_claude(monkeypatch):
    import asyncio

    from app.config import settings
    from app.trading.onchain import ai_review
    monkeypatch.setattr(settings, "deepseek_api_key", "k")
    monkeypatch.setattr(settings, "ai_review_provider", "auto")
    assert ai_review.provider() == "deepseek"

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"model": "deepseek-chat", "usage": {"prompt_tokens": 900, "completion_tokens": 100},
                    "choices": [{"finish_reason": "stop", "message": {"content": '{"summary": "ok", "actions": ["a"]}'}}]}

    class H:
        async def post(self, url, json, headers):
            assert url.endswith("/chat/completions") and json["response_format"]["type"] == "json_object"
            assert headers["Authorization"] == "Bearer k"
            return R()
    reply = asyncio.run(ai_review._ask_deepseek("{}", http=H()))
    assert reply.usage.input_tokens + reply.usage.output_tokens == 1000 and reply.content[0].text.startswith("{")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert ai_review.provider() is None


def test_new_gem_alert_names_the_tops_place(monkeypatch):
    """The Telegram place is the Top's, and a gem not in the Top is not announced (29/09: PFWA "4th")."""
    monkeypatch.setattr("time.time", lambda: T0)
    a, b = _gem(400_000, liq=60_000), _gem(500_000, liq=60_000)
    lb._rank()
    db_row = {"chain": "solana", "token_address": "DB", "symbol": "DBR", "on_board": False}
    top = [db_row]
    monkeypatch.setattr(lb, "_top_source", lambda n: top)
    assert lb.queue_top_news(top) == 0                   # first look: what is there is not news
    top.append({"chain": "solana", "token_address": a["token_address"]})
    got = []

    async def hook(kind, item):
        got.append((kind, item["symbol"], item["rank"]))
    lb.on_alert(hook)
    assert lb.queue_top_news(top) == 1
    asyncio.run(lb.drain_alerts())
    assert got == [("new", a["symbol"], 2)] and not any(s == b["symbol"] for _, s, _ in got)


def test_a_database_row_entering_the_top_is_announced_once(monkeypatch):
    """Lorenzo, 17/10: three projects entered the arenas overnight and the gems
    chat stayed silent. Rows from the database are gems too."""
    lb.queue_top_news([])
    row = {"chain": "base", "token_address": "0xabc", "symbol": "NEWG", "name": "New", "score": 74,
           "market_cap": 900_000, "on_board": False}
    top = [{"chain": "solana", "token_address": "OLD", "symbol": "OLD"}, row]
    monkeypatch.setattr(lb, "_top_source", lambda n: top)
    got = []

    async def hook(kind, item):
        got.append((kind, item["symbol"], item["rank"], item["score"]))
    lb.on_alert(hook)
    assert lb.queue_top_news(top) == 2
    asyncio.run(lb.drain_alerts())
    assert ("new", "NEWG", 2, 74) in got
    got.clear()
    assert lb.queue_top_news(top) == 0                   # once
    lb._outbox.append(("new", lb._key("base", "0xgone")))
    asyncio.run(lb.drain_alerts())
    assert got == []                                     # left the Top before its turn: skipped


def test_flush_sends_what_entered_after_the_last_tick(monkeypatch):
    """Lorenzo, 17/10: the 18:00 run listed new gems, the gems chat heard
    nothing. The nightly run's ticks stop before the settle and the deep
    re-check, which also put projects in the Top: the flush queues and sends
    them all, not five a tick."""
    top = [{"chain": "solana", "token_address": "OLD", "symbol": "OLD"}]
    monkeypatch.setattr(lb, "_top_source", lambda n: top)
    lb.queue_top_news(top)                                # the Top as first seen
    top += [{"chain": "solana", "token_address": f"N{i}", "symbol": f"N{i}", "score": 70} for i in range(7)]
    got, flushed = [], []

    async def hook(kind, item):
        got.append(item["symbol"])

    async def done():
        flushed.append(True)
    lb.on_alert(hook)
    lb.on_flush(done)
    assert asyncio.run(lb.flush_alerts(T0)) == 7
    assert got == [f"N{i}" for i in range(7)] and flushed == [True] and not lb._outbox


def test_gems_over_the_hourly_cap_arrive_together(monkeypatch):
    from app import main
    users = [SimpleNamespace(id="a", email="new@x", telegram_gems_chat_id="111", telegram_chat_id="", telegram_signal_chat_id="")]
    monkeypatch.setattr(main.auth, "list_users", lambda: users)
    monkeypatch.setattr(main, "_telegram_allowed", lambda u: True)
    monkeypatch.setattr(main, "_onchain_variant", lambda u: "current")
    sent = []
    monkeypatch.setattr(main, "_fire", lambda coro: (sent.append(coro.cr_frame.f_locals.get("text")), coro.close()))
    main._gem_notified.clear()
    main._gem_overflow.clear()
    for i in range(main._GEM_NOTIFY_PER_HOUR + 3):
        asyncio.run(main._notify_gem("new", {"chain": "solana", "token_address": f"T{i}", "symbol": f"G{i}",
                                             "score": 70, "rank": i + 1}))
    assert len(sent) == main._GEM_NOTIFY_PER_HOUR
    asyncio.run(main._send_gem_overflow())
    assert len(sent) == main._GEM_NOTIFY_PER_HOUR + 1
    last = sent[-1]
    assert "Altre 3 gemme" in last and all(f"G{i}" in last for i in range(6, 9))
    asyncio.run(main._send_gem_overflow())
    assert len(sent) == main._GEM_NOTIFY_PER_HOUR + 1    # once


def test_an_old_board_mark_does_not_hide_a_gem_entering_the_top(monkeypatch):
    """Lorenzo, 17/10: 8 gems entered the Top at 18:00, no message. The old
    _rank() had marked "new:" every project that ever entered the board's
    own ranking, and the Top's alert read the same mark."""
    row = {"chain": "solana", "token_address": "WAS", "symbol": "WAS", "score": 72}
    lb._alerted.add("new:" + lb._key("solana", "WAS"))
    top = [{"chain": "solana", "token_address": "OLD", "symbol": "OLD"}]
    monkeypatch.setattr(lb, "_top_source", lambda n: top)
    assert lb.queue_top_news(top) == 0                   # first look
    top.append(row)
    assert lb.queue_top_news(top) == 1


def test_the_top_is_looked_at_again_after_the_tag_change(tmp_path, monkeypatch):
    """A store written before 17/10 has "top_primed" and "new:" tags only:
    the first sync takes note of the Top instead of announcing all of it."""
    monkeypatch.setattr(lb, "_STORE_FILE", tmp_path / "board.json")
    (tmp_path / "board.json").write_text(json.dumps({"entries": {}, "alerted": ["new:solana:OLD"],
                                                     "top_primed": True}), encoding="utf-8")
    lb._load()
    top = [{"chain": "solana", "token_address": "OLD", "symbol": "OLD"}]
    assert lb.queue_top_news(top) == 0 and lb._top_primed


def test_early_alerts_are_not_held_to_the_top(monkeypatch):
    """Early gems sit under the Top's floor: the Top check dropped every one."""
    monkeypatch.setattr("time.time", lambda: T0)
    _gem(30_000)
    monkeypatch.setattr(lb, "_top_source", lambda n: [])
    lb._rank()
    got = []

    async def hook(kind, item):
        got.append((kind, item["symbol"]))
    lb.on_alert(hook)
    asyncio.run(lb.drain_alerts())
    assert got == [("early", "G30000")]


def test_a_gem_entering_pearl_is_announced_once(monkeypatch):
    """Lorenzo, 17/10: the gems chat hears about Pearl too (early, score 70 and up)."""
    monkeypatch.setattr("time.time", lambda: T0)
    assert lb.queue_pearl_news() == 0                    # first look: note only
    gem = _gem(30_000)
    weak = _gem(32_000)
    monkeypatch.setattr(lb, "final_score", lambda e: 80 if e is gem or e.get("symbol") == gem["symbol"] else 60)
    assert lb.is_pearl(gem) and not lb.is_pearl(weak)
    assert lb.queue_pearl_news() == 1
    got = []

    async def hook(kind, item):
        got.append((kind, item["symbol"]))
    lb.on_alert(hook)
    lb._outbox[:] = [x for x in lb._outbox if x[0] == "pearl"]
    asyncio.run(lb.drain_alerts())
    assert got == [("pearl", gem["symbol"])]
    assert lb.queue_pearl_news() == 0                    # once


def test_pearl_alert_goes_to_the_current_app_only(monkeypatch):
    from app import main
    users = [SimpleNamespace(id="a", email="new@x", telegram_gems_chat_id="111", telegram_chat_id="", telegram_signal_chat_id=""),
             SimpleNamespace(id="b", email="old@x", telegram_gems_chat_id="222", telegram_chat_id="", telegram_signal_chat_id="")]
    monkeypatch.setattr(main.auth, "list_users", lambda: users)
    monkeypatch.setattr(main, "_telegram_allowed", lambda u: True)
    monkeypatch.setattr(main, "_onchain_variant", lambda u: "v1" if u.id == "b" else "current")
    sent = []
    monkeypatch.setattr(main, "_fire", lambda coro: (sent.append(coro.cr_frame.f_locals.get("chat_id")), coro.close()))
    main._gem_notified.clear()
    item = {"chain": "solana", "token_address": "T", "symbol": "PRL", "score": 74}
    asyncio.run(main._notify_gem("pearl", item))
    assert sent == ["111"]
    assert "Nuova Pearl" in main._gem_telegram_text("pearl", item) and "#pearl&amp;token=" in main._gem_telegram_text("pearl", item)
    sent.clear()
    asyncio.run(main._notify_gem("new", {**item, "token_address": "U"}))
    assert sorted(sent) == ["111", "222"]


class _Everything:
    def __contains__(self, item):
        return True


def _unlimited_users(monkeypatch):
    from app import main
    users = [SimpleNamespace(id="k", email="kobra@x.it", telegram_gems_chat_id="111", telegram_chat_id="", telegram_signal_chat_id=""),
             SimpleNamespace(id="o", email="other@x.it", telegram_gems_chat_id="222", telegram_chat_id="", telegram_signal_chat_id="")]
    monkeypatch.setattr(main.auth, "list_users", lambda: users)
    monkeypatch.setattr(main, "_telegram_allowed", lambda u: True)
    monkeypatch.setattr(main, "_onchain_variant", lambda u: "current")
    monkeypatch.setattr(main.settings, "telegram_unlimited_emails", "kobra@x.it")
    monkeypatch.setattr(main, "_gem_view_keys", lambda kind: _Everything())
    sent = []
    monkeypatch.setattr(main, "_fire", lambda coro: (sent.append(coro.cr_frame.f_locals.get("chat_id")), coro.close()))
    main._gem_notified.clear()
    main._gem_overflow.clear()
    return main, sent


def test_the_unlimited_account_has_no_hourly_cap_on_gems(monkeypatch):
    """Lorenzo, 17/10: "Solo per account whitekobra: Rimuovi tutti i limiti"."""
    main, sent = _unlimited_users(monkeypatch)
    for i in range(main._GEM_NOTIFY_PER_HOUR + 4):
        asyncio.run(main._notify_gem("new", {"chain": "solana", "token_address": f"T{i}", "symbol": f"G{i}",
                                             "score": 70, "first_seen": True}))
    assert sent.count("111") == main._GEM_NOTIFY_PER_HOUR + 4
    assert sent.count("222") == main._GEM_NOTIFY_PER_HOUR      # the others keep the cap


def test_the_unlimited_account_hears_only_of_gems_new_to_every_ranking(monkeypatch):
    """A gem moving from Early to the Top, or into Pearl, was already there."""
    main, sent = _unlimited_users(monkeypatch)
    asyncio.run(main._notify_gem("new", {"chain": "solana", "token_address": "E", "symbol": "WASEARLY",
                                         "score": 70, "first_seen": False}))
    assert sent == ["222"]
    k = lb._key("solana", "E")
    lb._alerted.update({"early:" + k, "top:" + k})
    assert not lb.first_in_any_ranking("new", k) and not lb.first_in_any_ranking("pearl", k)
    assert lb.first_in_any_ranking("new", lb._key("solana", "FRESH"))


def test_paced_chats_wait_between_two_messages(monkeypatch):
    from app.notify import telegram
    monkeypatch.setattr(telegram.settings, "telegram_bot_token", "x")
    monkeypatch.setattr(telegram, "PACE_S", 0.2)
    times = []

    async def deliver(client, chat_id, text):
        times.append((chat_id, __import__("time").monotonic()))
        return True
    monkeypatch.setattr(telegram, "_deliver", deliver)
    telegram.set_paced_chats(lambda: {"111"})
    telegram._pace_last.clear()
    telegram._pace_locks.clear()

    async def go():
        await asyncio.gather(*(telegram.send_to(c, "hi") for c in ("111", "111", "222", "222")))
    try:
        asyncio.run(go())
    finally:
        telegram.set_paced_chats(None)
    paced = [t for c, t in times if c == "111"]
    free = [t for c, t in times if c == "222"]
    assert paced[1] - paced[0] >= 0.19 and abs(free[1] - free[0]) < 0.1


def test_pearl_entries_always_reach_the_unlimited_account(monkeypatch):
    """Lorenzo, 17/10: the one exception, a gem entering Pearl is always news."""
    main, sent = _unlimited_users(monkeypatch)
    asyncio.run(main._notify_gem("pearl", {"chain": "solana", "token_address": "P", "symbol": "PRL",
                                           "score": 75, "first_seen": False}))
    assert sorted(sent) == ["111", "222"]


def test_the_unlimited_account_hears_only_of_gems_its_view_lists(monkeypatch):
    main, sent = _unlimited_users(monkeypatch)
    monkeypatch.setattr(main, "_gem_view_keys", lambda kind: {("solana", "IN")})
    for tok in ("IN", "OUT"):
        asyncio.run(main._notify_gem("new", {"chain": "solana", "token_address": tok, "symbol": tok,
                                             "score": 70, "first_seen": True}))
    assert sent.count("111") == 1 and sent.count("222") == 2


def test_the_gem_view_drops_duplicates_old_and_weak_projects():
    """Lorenzo, 17/10: Sherwood Protocol twice with two scores; nothing over
    1000 days old; nothing under 60."""
    from app import main
    now = 1_790_000_000.0
    day = 86400
    rows = [
        {"chain": "base", "token_address": "S1", "name": "Sherwood Protocol", "score": 81, "liquidity_usd": 40_000, "launched_at": now - 90 * day},
        {"chain": "solana", "token_address": "S2", "name": "Sherwood  protocol", "score": 66, "liquidity_usd": 150_000, "launched_at": now - 90 * day},
        {"chain": "base", "token_address": "OLD", "name": "Old Coin", "score": 90, "launched_at": now - 1001 * day},
        {"chain": "base", "token_address": "WEAK", "name": "Weak", "score": 59.4, "launched_at": now - 10 * day},
        {"chain": "base", "token_address": "EDGE", "name": "Edge", "score": 59.6, "launched_at": None},
    ]
    kept = [r["token_address"] for r in main._gem_view(rows, now)]
    assert kept == ["S2", "EDGE"]          # the deeper pool of the two Sherwoods
