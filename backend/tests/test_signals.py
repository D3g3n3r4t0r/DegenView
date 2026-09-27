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
    assert ("early", "G30000", True) in got and ("new", "G400000", False) in got
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
