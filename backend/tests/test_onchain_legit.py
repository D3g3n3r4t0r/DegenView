"""Il filtro di legittimita'. Lorenzo: "voglio evitare rug pull [...] voglio
token legittimi con progetti seri", e poi "fai un controllo anche per github
[...] voglio evitare SHITCOIN e MEMECOIN"."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.trading.onchain import legit


def test_launchpad_and_social_pages_are_not_a_website():
    assert legit.pick_website(["https://pump.fun/coin/X", "https://linktr.ee/x", "https://github.com/x"]) is None
    assert legit.pick_website(["https://x.com/p", "https://www.realproject.io/"]) == "https://www.realproject.io/"


@pytest.mark.parametrize("report, ok", [
    (None, None),
    ({"rugged": True}, False),
    ({"risks": [{"name": "Mint Authority still enabled", "level": "danger"}]}, False),
    ({"risks": [], "lpLockedPct": 40}, False),
    ({"risks": [{"name": "Low holders", "level": "warn"}], "lpLockedPct": 100}, True),
])
def test_rugcheck(report, ok):
    assert legit.judge_rugcheck(report)["ok"] is ok


@pytest.mark.parametrize("info, ok", [
    (None, None),
    ({"is_honeypot": "1"}, False),
    ({"sell_tax": "0.25"}, False),
    ({"is_mintable": "1"}, False),
    ({"can_take_back_ownership": "1"}, False),
    ({"is_open_source": "0"}, False),
    ({"holders": [{"percent": "0.6", "is_contract": 0, "is_locked": 0}]}, False),
    ({"holders": [{"percent": "0.6", "is_contract": 1}], "is_open_source": "1", "sell_tax": "0.01"}, True),
])
def test_goplus(info, ok):
    assert legit.judge_goplus(info)["ok"] is ok


def _commits(n, days):
    return [{"commit": {"author": {"date": f"2026-09-{10 + i % days:02d}T10:00:00Z"}}} for i in range(n)]


@pytest.mark.parametrize("repo, commits, ok", [
    (None, None, None),
    ({}, None, False),
    ({"full_name": "a/b", "fork": True}, _commits(40, 9), False),
    ({"full_name": "a/b"}, _commits(3, 3), False),
    ({"full_name": "a/b"}, _commits(12, 1), False),      # tutto in un giorno
    ({"full_name": "a/b", "stargazers_count": 4}, _commits(12, 4), True),
])
def test_github(repo, commits, ok):
    assert legit.judge_github(repo, commits)["ok"] is ok


def test_github_links_from_anywhere():
    assert legit.github_targets(["https://github.com/orgs/x", "https://github.com/acme/core.git",
                                 "https://github.com/acme", "https://x.com/a"]) == [("acme", "core"), ("acme", None)]


def test_page_text_drops_scripts():
    title, text = legit.page_text("<title>Acme &amp; Co</title><script>evil()</script><p>Real  product</p>")
    assert title == "Acme & Co" and text == "Real product"


def test_site_on_a_private_address_is_never_fetched():
    async def go():
        async with httpx.AsyncClient() as c:
            return await legit.fetch_site("http://127.0.0.1:8000/admin", c)
    assert asyncio.run(go())["error"] == "indirizzo non pubblico"


TOKEN = {"chain": "solana", "symbol": "ACME", "name": "Acme Protocol", "token_address": "Mint111",
         "market_cap": 80_000, "liquidity_usd": 20_000}
LINKS = {"websites": ["https://acme.io"], "socials": [{"type": "twitter", "url": "https://x.com/acme"}]}


def _net(repo_commits=12, lp=100):
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "rugcheck" in url:
            return httpx.Response(200, json={"risks": [], "lpLockedPct": lp})
        if url.startswith("https://acme.io"):
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  text="<title>Acme</title><a href='https://github.com/acme/core'>code</a> Mint111")
        if url.endswith("/repos/acme/core"):
            return httpx.Response(200, json={"full_name": "acme/core", "html_url": "https://github.com/acme/core"})
        if url.startswith("https://api.github.com/repos/acme/core/commits"):
            return httpx.Response(200, json=_commits(repo_commits, 5))
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    async def ok(host):
        return host != "127.0.0.1"
    monkeypatch.setattr(legit, "_public_host", ok)
    monkeypatch.setattr(legit.settings, "anthropic_api_key", "")
    monkeypatch.setattr(legit.settings, "tokensniffer_api_key", "")


def _assess(token=TOKEN, links=LINKS, **net):
    async def go():
        async with httpx.AsyncClient(transport=_net(**net)) as c:
            return await legit.assess(token, links, c)
    return asyncio.run(go())


def test_serious_project_passes_with_site_github_and_contract_on_the_site():
    out = _assess()
    assert out["status"] == "ok" and out["website"] == "https://acme.io"
    assert out["github"] == "https://github.com/acme/core"
    checks = {c["key"]: c for c in out["checks"]}
    assert "cita il contratto" in checks["site"]["detail"] and checks["ai"]["detail"] == "non attivo"


def test_meme_name_fails_before_any_request():
    assert _assess({**TOKEN, "symbol": "PEPE2", "name": "Pepe Two"})["status"] == "fail"


def test_unlocked_liquidity_fails():
    assert _assess(lp=10)["status"] == "fail"


def test_empty_github_fails():
    out = _assess(repo_commits=2)
    assert out["status"] == "fail" and out["reason"].startswith("GitHub")


def test_no_website_yet_waits():
    assert _assess(links={"websites": ["https://pump.fun/coin/x"], "socials": LINKS["socials"]})["status"] == "wait"


def test_claude_verdict_can_only_reject(monkeypatch):
    monkeypatch.setattr(legit.settings, "anthropic_api_key", "k")

    async def review(token, site, links):
        return {"legit": False, "score": 2, "reason": "solo hype, nessun prodotto", "red_flags": ["hype"]}
    monkeypatch.setattr(legit, "ai_review", review)
    out = _assess()
    assert out["status"] == "fail" and "solo hype" in out["reason"]


@pytest.mark.parametrize("report, ok", [
    (None, None),
    ({"status": "pending"}, None),
    ({"status": "ready", "score": 90, "is_flagged": True}, False),
    ({"status": "ready", "score": 90, "exploits": ["honeypot"]}, False),
    ({"status": "ready", "score": 40, "tests": [{"id": "t1", "description": "Owner can mint", "result": False}]}, False),
    ({"status": "ready", "score": 85, "tests": [{"id": "t1", "result": True}]}, True),
])
def test_tokensniffer(report, ok):
    assert legit.judge_tokensniffer(report)["ok"] is ok


def test_tokensniffer_is_a_filter_when_the_key_is_set(monkeypatch):
    monkeypatch.setattr(legit.settings, "tokensniffer_api_key", "k")
    base = _net()

    def handler(req):
        if "tokensniffer.com" in str(req.url):
            assert req.headers["X-API-Key"] == "k" and "/tokens/solana/Mint111" in str(req.url)
            return httpx.Response(200, json={"status": "ready", "score": 20, "is_flagged": False})
        return base.handle_request(req)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await legit.assess(TOKEN, LINKS, c)
    out = asyncio.run(go())
    assert out["status"] == "fail" and out["reason"].startswith("Token Sniffer")
    assert out["tokensniffer"] == "https://tokensniffer.com/token/solana/Mint111"


def test_without_a_key_the_report_link_stays_and_nothing_blocks():
    out = _assess()
    sniff = next(c for c in out["checks"] if c["key"] == "sniffer")
    assert sniff["detail"] == "non attivo" and out["status"] == "ok" and out["tokensniffer"]
