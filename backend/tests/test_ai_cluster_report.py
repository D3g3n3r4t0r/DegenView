"""Lorenzo, 22/10: the AI re-check and the AI veto read the wallet cluster
report, and a missing one is built first."""
import asyncio
import json
import time

import httpx
from app import free_ai
from app.trading.onchain import ai_veto, coordinated_sells as cs, deep_recheck, projects_db, scout_recheck, storage
from app.trading.onchain import wallet_clusters as wc

REAL_ENSURE, REAL_STATE = wc.ensure, wc.report_state
TOKEN = "0x" + "ab" * 20


def _report(now, risk=72):
    return {"version": 1, "chain": "base", "token": TOKEN, "symbol": "XYZ", "updated_at": now - 3600,
            "risk": {"score": risk, "reasons": ["linked clusters hold 14% of supply"]},
            "clusters": [{"id": "c1", "wallets": [{"address": "0x" + "1" * 40, "share": 0.09},
                                                  {"address": "0x" + "2" * 40, "share": 0.05}],
                          "share": 0.14, "links": ["transfer"]},
                         {"id": "top", "wallets": [{"address": "0x" + "3" * 40, "share": 0.5}], "share": 0.6,
                          "links": ["top_holders"]}],
            "events": [{"id": "c1-1", "cluster": "c1", "ts": now - 7200, "wallets": 2, "share_sold": 0.02}],
            "coverage": {"source": "blockscout", "partial": True}}


def test_ai_facts_and_text_carry_counts_not_addresses(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    now = time.time()
    cs.write(_report(now))
    f = cs.ai_facts("base", TOKEN.upper().replace("0X", "0x"), now)
    assert f["risk"] == 72 and f["linked_clusters"] == 1 and f["linked_supply_pct"] == 14.0
    assert f["top_holders_supply_pct"] == 60.0 and f["sell_waves_7d"] == 1
    text = cs.ai_text(f)
    assert "risk 72/100" in text and "partial" in text and "0x1111" not in text
    assert "unverified" in cs.ai_text(None, "chain not covered")


def test_an_old_report_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    now = time.time()
    cs.write(_report(now - 8 * 86400))
    assert cs.ai_facts("base", TOKEN, now) is None


def test_ensure_builds_a_missing_report_and_waits_for_it(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(wc, "report_state", REAL_STATE)
    monkeypatch.setattr(wc, "_state", lambda: {})
    built = []

    async def fake_build(item, now):
        built.append(item["token"])
        cs.write(_report(time.time()))
        return {"clusters": []}
    monkeypatch.setattr(wc, "_build_tracked", fake_build)

    async def run():
        assert await REAL_ENSURE("base", TOKEN, "XYZ", wait_s=5) == "ready"
        assert await REAL_ENSURE("base", TOKEN, "XYZ", wait_s=5) == "ready"
    asyncio.run(run())
    assert built == [TOKEN]


def test_ensure_does_not_build_a_chain_it_cannot_read(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(wc, "report_state", REAL_STATE)
    assert asyncio.run(REAL_ENSURE("sui", TOKEN)) == "chain not covered"


def test_the_veto_waits_for_a_missing_report_and_queues_it_first(monkeypatch):
    monkeypatch.setattr(free_ai, "keys", lambda: {"groq": "k"})
    monkeypatch.setattr(wc, "report_state", lambda chain, token, now=None: "pending")
    queued = []
    monkeypatch.setattr(wc, "request", lambda chain, token, symbol="", **kw: queued.append((token, kw.get("urgent"))))

    async def run():
        def handler(request):
            raise AssertionError("no AI call without the cluster report")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ai_veto.run_once([{"chain": "base", "token_address": TOKEN, "symbol": "XYZ"}], c)
    assert asyncio.run(run()) == 0
    assert queued == [(TOKEN, True)]


def test_the_veto_sends_the_report_to_the_ai(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(free_ai, "keys", lambda: {"groq": "k"})
    monkeypatch.setattr(wc, "report_state", lambda chain, token, now=None: "ready")
    cs.write(_report(time.time()))
    sent = []

    async def run():
        def handler(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
                {"verdict": "scam", "confidence": 0.9, "reason": "linked wallets hold 14%"})}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ai_veto.run_once([{"chain": "base", "token_address": TOKEN, "symbol": "XYZ"}], c)
    assert asyncio.run(run()) == 1
    data = sent[0]["messages"][1]["content"]
    assert '"linked_supply_pct": 14.0' in data and "linked_pct" not in data.replace("linked_supply_pct", "")


def test_the_deep_recheck_builds_the_report_and_puts_it_in_the_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(deep_recheck, "_STORE", tmp_path / "deep.json")
    deep_recheck.reset_for_tests()
    monkeypatch.setattr(free_ai, "keys", lambda: {"groq": "k"})
    projects_db.upsert({"chain": "base", "token_address": TOKEN, "symbol": "XYZ"}, "test", now=100)
    ensured, asked = [], []

    async def ensure(chain, token, symbol="", wait_s=0):
        ensured.append(token)
        return "ready"

    async def gather(entry, item, client):
        return {"found": [], "pages": [], "checked": [], "snippets": [], "gecko": None}

    async def tokenomics(chain, token, client, **kw):
        return None

    async def ask(messages, **kw):
        asked.append(messages[1]["content"])
        return json.dumps({"verdict": "ok", "confidence": 0.9, "product": "x", "summary": "y", "reason": "z"})
    monkeypatch.setattr(wc, "ensure", ensure)
    monkeypatch.setattr(scout_recheck, "gather", gather)
    monkeypatch.setattr(deep_recheck.depth, "analyze_tokenomics", tokenomics)
    monkeypatch.setattr(cs, "ai_facts", lambda chain, token, now=None: {
        "risk": 80, "risk_reasons": [], "linked_clusters": 2, "linked_wallets": 9, "linked_supply_pct": 15.0,
        "biggest_cluster_pct": 10.0, "links": ["transfer"], "top_holders_supply_pct": None, "sell_waves": 0,
        "sell_waves_7d": 0, "supply_sold_in_waves_pct": 0, "last_wave_hours_ago": None, "report_age_hours": 1,
        "coverage": None})
    res = asyncio.run(deep_recheck.run("base", TOKEN, None, ask=ask))
    assert ensured == [TOKEN] and "Risk 80/100" in asked[0] and "risk 80/100" in res["clusters"]
    assert res["areas"][0]["status"] == "bad" and res["keep"] is False and res["by"] == "holders"
    deep_recheck.reset_for_tests()
