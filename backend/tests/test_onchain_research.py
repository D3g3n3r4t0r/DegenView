"""The Gem Finder's researcher: substance over launch noise."""
import time

import pytest

from app.trading.onchain import depth, leaderboard as lb, research as rs

SOLROUTER = (
    "Solrouter is a privacy-preserving AI inference layer built on Solana. The protocol allows users to submit "
    "prompts to open-source language models without exposing the prompt content, model inputs, or agent state "
    "to any centralized provider. Queries are encrypted client-side in the browser. Encrypted payloads are "
    "processed inside a Trusted Execution Environment (TEE) running on a decentralized GPU network, where "
    "open-source models perform inference. Each query produces a cryptographic attestation anchored to Solana. "
    "The architecture removes three trust assumptions found in conventional AI inference services: prompts "
    "are not visible to a shared server, agent reasoning state is not held by a centralized provider, and "
    "settlement does not depend on trusting the inference operator. "
    "$ROUTER is the native token used to pay for inference on the network."
)


@pytest.fixture(autouse=True)
def _clean():
    lb.reset_for_tests()
    rs._cache.clear()
    yield


def _site(score, **facts):
    return depth._pillar("site", score, {"narratives": [], **facts}, [])


def test_substance_rewards_mechanisms_and_punishes_hype():
    good, facts = rs.substance(SOLROUTER)
    hype, _ = rs.substance("The next 100x gem, ape in before it moons, lambo soon, degen army!")
    assert good >= 80 and "inference" in facts["mechanisms"] and hype == 0


def test_js_home_page_does_not_sink_a_real_project():
    """Solrouter: JS shell home (20), real docs (55), rich description."""
    p = rs.judge_research([_site(20), _site(55, url="https://docs.solrouter.com")], SOLROUTER, None)
    assert p["score"] >= 70 and not p["fatal"]
    assert p["facts"]["summary"].startswith("Solrouter is a privacy-preserving")
    assert "privacy" in p["facts"]["narratives"]


def test_claude_reading_weighs_most_and_can_call_a_scam():
    ai = {"summary": "Private AI inference on Solana", "stage": "live", "substance": 9, "original": True,
          "verdict": "gem", "red_flags": []}
    p = rs.judge_research([_site(30)], "", ai)
    assert p["score"] >= 65 and p["facts"]["summary"] == "Private AI inference on Solana"
    scam = rs.judge_research([_site(80)], SOLROUTER, {**ai, "verdict": "scam", "substance": 1})
    assert scam["fatal"]


def test_site_urls_one_per_host_home_first():
    item = {"website": "https://solrouter.com", "websites": ["https://docs.solrouter.com", "https://www.solrouter.com/x"]}
    assert rs.site_urls(item, ["https://app.solrouter.com", "https://x.com/foo"]) == [
        "https://solrouter.com", "https://docs.solrouter.com", "https://app.solrouter.com"]


def test_research_floor_keeps_launches_out():
    base = {"chain": "solana", "token_address": "T", "symbol": "ABC", "liquidity_usd": 50_000,
            "launched_at": time.time() - 60 * 86400}
    assert lb.research_floor(base) == ""
    assert lb.research_floor({**base, "symbol": "?"}) == "no name"
    assert "younger" in lb.research_floor({**base, "launched_at": time.time() - 15 * 60})
    assert "liquidity" in lb.research_floor({**base, "liquidity_usd": 1})


def test_radar_launches_leave_the_board_and_references_are_examined(tmp_path, monkeypatch):
    f = tmp_path / "lb.json"
    f.write_text('{"rules": 3, "entries": {"solana:R": {"source": "radar", "symbol": "?"}, '
                 '"solana:C": {"source": "coingecko", "symbol": "C", "chain": "solana", "token_address": "C", '
                 '"pillars": {}}}}')
    monkeypatch.setattr(lb, "_STORE_FILE", f)
    lb._load()
    assert "solana:R" not in lb._entries and "solana:C" in lb._entries
    lb.collect_saved()
    assert lb._key("solana", lb.REFERENCES[0]["token_address"]) in lb._entries


def _funnel(monkeypatch, tmp_path, key="sk-test"):
    """Stub the network: one decent docs site, Solrouter's description."""
    calls = []

    async def info(chain, token, client):
        return {"description": SOLROUTER, "websites": []}

    async def site(url, client, token, launched):
        return _site(55, excerpt="docs"), []

    async def dossier(item, description, texts):
        calls.append(item["token_address"])
        return {"summary": "x", "stage": "live", "substance": 8, "original": True,
                "verdict": "promising", "red_flags": []}

    monkeypatch.setattr(rs, "gecko_info", info)
    monkeypatch.setattr(depth, "analyze_site", site)
    monkeypatch.setattr(rs, "ai_dossier", dossier)
    monkeypatch.setattr(rs, "_STORE", tmp_path / "research.json")
    monkeypatch.setattr(rs.legit.settings, "anthropic_api_key", key)
    rs._calls.clear()
    return calls


def _run(token, finalist=True):
    import asyncio
    item = {"chain": "solana", "token_address": token, "website": "https://docs.example.org",
            "finalist": finalist}
    return asyncio.run(rs.analyze(item, None, None))[0]


def test_claude_reads_only_finalists_once(monkeypatch, tmp_path):
    calls = _funnel(monkeypatch, tmp_path)
    assert _run("A", finalist=False)["facts"].get("verdict") is None
    assert _run("B")["facts"]["verdict"] == "promising"
    _run("B")
    assert calls == ["B"] and rs.ai_status()["today"] == 1


def test_daily_cap_bounds_the_bill(monkeypatch, tmp_path):
    calls = _funnel(monkeypatch, tmp_path)
    monkeypatch.setattr(rs, "AI_DAILY_MAX", 2)
    for t in "CDE":
        _run(t)
    assert calls == ["C", "D"]


def test_no_key_no_call(monkeypatch, tmp_path):
    calls = _funnel(monkeypatch, tmp_path, key="")
    p = _run("F")
    assert calls == [] and p["score"] is not None and not rs.ai_status()["enabled"]
