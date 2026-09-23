"""Listing appena usciti con liquidita': Lorenzo li vuole "quasi istantanei"."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.trading.onchain import legit
from app.trading.onchain import listings as L

VERDICTS: dict[str, dict] = {}
NO_CHART: set[str] = set()


def _verdict(status="ok", reason=""):
    return {"status": status, "reason": reason, "website": "https://proj.xyz",
            "socials": [{"type": "twitter", "url": "https://x.com/proj"}], "github": None,
            "checks": [{"key": "site", "label": "Sito", "ok": True, "detail": ""}], "ai": None}


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "_STORE_FILE", tmp_path / "listings.json")
    monkeypatch.setattr(L, "_callbacks", [])
    monkeypatch.setattr(L, "_vet_slots", asyncio.Semaphore(4))
    VERDICTS.clear()

    async def fake_assess(token, links, client):
        return VERDICTS.get(token["symbol"], _verdict())
    monkeypatch.setattr(legit, "assess", fake_assess)

    async def chart_ready(item):
        return item["symbol"] not in NO_CHART
    monkeypatch.setattr(L, "_chart_ready", chart_ready)
    NO_CHART.clear()
    L.reset_for_tests()
    yield
    L.reset_for_tests()


def _accept(pairs):
    return asyncio.run(L.accept_pairs(pairs, wait=True))


def _pair(pool="P1", symbol="NEW", liq=20_000, cap=80_000, age_s=120, chain="solana"):
    return {"chainId": chain, "pairAddress": pool, "dexId": "pumpswap", "url": f"https://dexscreener.com/{chain}/{pool}",
            "baseToken": {"address": f"T{pool}", "symbol": symbol, "name": symbol},
            "liquidity": {"usd": liq}, "marketCap": cap, "pairCreatedAt": (time.time() - age_s) * 1000}


def test_pool_address_from_v3_and_v2_creation_logs():
    v3 = {"topics": [L.POOL_CREATED_V3], "data": "0x" + "0" * 63 + "a" + "0" * 24 + "ab" * 20}
    v2 = {"topics": [L.PAIR_CREATED_V2], "data": "0x" + "0" * 24 + "cd" * 20 + "0" * 63 + "1"}
    other = {"topics": ["0xdead"], "data": "0x" + "0" * 128}
    assert L.pools_from_logs([v3, v2, other]) == ["0x" + "ab" * 20, "0x" + "cd" * 20]


def test_pumpfun_only_young_graduates():
    now = time.time()
    coins = [
        {"complete": True, "created_timestamp": (now - 600) * 1000, "pump_swap_pool": "Fresh",
         "website": "https://fresh.io", "twitter": "https://x.com/fresh"},
        {"complete": False, "created_timestamp": (now - 60) * 1000, "pump_swap_pool": "Curve"},
        {"complete": True, "created_timestamp": (now - 10 * 3600) * 1000, "pump_swap_pool": "Old"},
    ]
    assert L.pools_from_pumpfun(coins, now) == [
        ("Fresh", {"websites": ["https://fresh.io"], "socials": [{"type": "twitter", "url": "https://x.com/fresh"}]})]


@pytest.mark.parametrize("kw, ok", [
    ({}, True),
    ({"liq": 5_000}, False),
    ({"cap": 150_000}, False),                    # Lorenzo: non oltre i $100k
    ({"liq": 5_000, "cap": 60_000}, False),
    ({"liq": 9_000, "cap": 95_000}, False),       # 9% della cap
    ({"age_s": 8 * 3600}, False),
    ({"symbol": "WETH"}, False),
])
def test_thresholds(kw, ok):
    assert (L.evaluate_pair(_pair(**kw)) is not None) is ok


def test_one_alert_per_ticker_and_waits_for_liquidity():
    L.add_pending("solana", "P1", "pumpfun")
    L.add_pending("solana", "P2", "gecko")
    assert _accept([_pair("P1", liq=100)]) == []   # ancora senza liquidita'
    assert "solana:P1" in L._pending
    got = _accept([_pair("P1"), _pair("P2", symbol="new")])
    assert [g["pair_address"] for g in got] == ["P1"]
    assert got[0]["source"] == "pumpfun" and got[0]["latency_s"] >= 119
    assert L.recent()[0]["symbol"] == "NEW"
    assert not L.add_pending("solana", "P1", "gecko")  # gia' chiuso


def test_subscribers_get_every_listing_but_telegram_only_fresh_ones():
    seen = []

    async def cb(item):
        seen.append(item["symbol"])
    L.on_listing(cb)
    q = L.subscribe()
    L.add_pending("solana", "A", "gecko")
    L.add_pending("solana", "B", "gecko")
    _accept([_pair("A", symbol="FRESH", age_s=60), _pair("B", symbol="LATE", age_s=3 * 3600)])
    assert seen == ["FRESH"]
    assert q.qsize() == 2


def test_full_pending_drops_the_oldest_never_the_new(monkeypatch):
    monkeypatch.setattr(L, "MAX_PENDING", 2)
    L.add_pending("robinhood", "0x1", "chain")
    L.add_pending("robinhood", "0x2", "chain")
    assert L.add_pending("robinhood", "0x3", "chain")
    assert set(L._pending) == {"robinhood:0x2", "robinhood:0x3"}


def test_pending_expires():
    L.add_pending("solana", "Z", "gecko")
    L._pending["solana:Z"].detected_at -= L.PENDING_TTL_S + 1
    _accept([])
    assert not L._pending


def test_legit_filter_rejects_waits_and_attaches_site():
    VERDICTS["RUG"] = _verdict("fail", "RugCheck: Mint authority")
    VERDICTS["SOON"] = _verdict("wait", "manca il sito del progetto")
    for pool in ("A", "B", "C"):
        L.add_pending("solana", pool, "gecko")
    got = _accept([_pair("A", symbol="RUG"), _pair("B", symbol="SOON"), _pair("C", symbol="REAL")])
    assert [g["symbol"] for g in got] == ["REAL"]
    assert got[0]["website"] == "https://proj.xyz" and got[0]["checks"]
    assert L.status()["recent_rejected"][0]["reason"] == "RugCheck: Mint authority"
    assert "solana:A" not in L._pending
    waiting = L._pending["solana:B"]
    assert waiting.waiting_for == "manca il sito del progetto"
    assert _accept([_pair("B", symbol="SOON")]) == []            # non prima di VET_RETRY_S
    waiting.next_vet_at = 0
    VERDICTS["SOON"] = _verdict()
    assert [g["symbol"] for g in _accept([_pair("B", symbol="SOON")])] == ["SOON"]


def test_pumpfun_links_reach_the_filter(monkeypatch):
    seen = {}

    async def spy(token, links, client):
        seen.update(links)
        return _verdict()
    monkeypatch.setattr(legit, "assess", spy)
    L.add_pending("solana", "P", "pumpfun", {"websites": ["https://a.io"], "socials": []})
    pair = _pair("P")
    pair["info"] = {"socials": [{"type": "telegram", "url": "https://t.me/a"}]}
    _accept([pair])
    assert seen == {"websites": ["https://a.io"], "socials": [{"type": "telegram", "url": "https://t.me/a"}]}


def test_telegram_message_links_the_project_site():
    item = {"chain": "solana", "symbol": "ACME", "name": "Acme <Protocol>", "liquidity_usd": 20_000,
            "market_cap": 80_000, "created_at": 1000.0, "pair_url": "https://dexscreener.com/solana/P",
            "website": "https://acme.io/?a=1&b=2", "github": "https://github.com/acme/core",
            "socials": [{"type": "twitter", "url": "https://x.com/acme"}],
            "checks": [{"label": "Sito", "ok": True}, {"label": "GitHub", "ok": True}, {"label": "Claude sul sito", "ok": None}],
            "ai": None, "tokensniffer": "https://tokensniffer.com/token/solana/T"}
    text = L.telegram_text(item, now=1000.0 + 300, app_url="https://liquidityengine.app/onchain-app.html#listing=solana:P")
    assert '<a href="https://acme.io/?a=1&amp;b=2">🌐 Sito</a>' in text
    assert "Acme &lt;Protocol&gt;" in text and "nato 5 min fa" in text
    assert "✅ Sito · GitHub\n" in text and "Claude" not in text
    assert 'href="https://github.com/acme/core"' in text and "Apri in DEGEN" in text
    assert '<a href="https://tokensniffer.com/token/solana/T">Token Sniffer</a>' in text


def test_a_listing_without_a_chart_is_never_shown(monkeypatch):
    calls = []

    async def assess(token, links, client):
        calls.append(token["symbol"])
        return _verdict()
    monkeypatch.setattr(legit, "assess", assess)
    NO_CHART.add("NEW")
    L.add_pending("solana", "P1", "pumpfun")
    assert _accept([_pair("P1")]) == []
    pending = L._pending["solana:P1"]
    assert pending.waiting_for == "grafico non ancora disponibile" and pending.verdict["status"] == "ok"
    NO_CHART.clear()
    pending.next_vet_at = 0
    assert [g["symbol"] for g in _accept([_pair("P1")])] == ["NEW"]
    assert calls == ["NEW"]   # il filtro non si ripete mentre si aspetta il grafico
