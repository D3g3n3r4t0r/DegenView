"""Scanning one token by hand (manual_scan.py)."""
from app.trading.onchain import manual_scan as ms


def _pair(chain, sym, addr, liq):
    return {"chainId": chain, "baseToken": {"symbol": sym, "address": addr, "name": sym}, "liquidity": {"usd": liq},
            "pairAddress": "p" + addr, "marketCap": 1e6}


def test_pick_prefers_the_exact_match_then_liquidity_on_our_chains():
    pairs = [_pair("solana", "PEPE", "A1", 5_000), _pair("solana", "PEPE", "A2", 90_000),
             _pair("arbitrum", "PEPE", "A3", 9e9), _pair("base", "PEPEX", "A4", 1e6)]
    assert ms.pick(pairs, "$pepe")["baseToken"]["address"] == "A2"
    addr = "0x" + "ab" * 20
    pairs.append(_pair("bsc", "ZZZ", addr, 10))
    assert ms.pick(pairs, addr.upper().replace("0X", "0x"))["chainId"] == "bsc"
    assert ms.pick([_pair("arbitrum", "X", "a", 1)], "X") is None


def test_pick_prefers_the_traded_token_over_a_deep_empty_copy():
    real = [{**_pair("robinhood", "HYDX", "0xAA57", 58_000), "volume": {"h24": 311_000}},
            {**_pair("robinhood", "HYDX", "0xaa57", 1_200), "volume": {"h24": 4_700}}]
    fake = {**_pair("ethereum", "HYDX", "0xD932", 98_000_000), "volume": {"h24": 0.01}}
    got = ms.pick([fake, *real], "HYDX")
    assert got["chainId"] == "robinhood" and got["liquidity"]["usd"] == 58_000


def test_item_has_what_the_checks_need():
    it = ms.item_of({**_pair("solana", "CAT", "C1", 20_000), "url": "u", "pairCreatedAt": 1_700_000_000_000})
    assert it["chain"] == "solana" and it["token_address"] == "C1" and it["liquidity_usd"] == 20_000
    assert it["created_at"] == 1_700_000_000


def test_memory_labels_are_english_and_ai_drops_its_own_memory_counts():
    assert ms.english("5 similar: 1 rug, after 13.2h, 4 buono, 1 finto") == \
        "5 similar: 1 rug, after 13.2h, 4 fine, 1 fake volume"
    ai = ms.clean_flags({"risk": 78, "flags": ["defi impersonation", "4/5 similar rugged", "no github"]})
    assert ai["flags"] == ["defi impersonation", "no github"]
    assert ms.clean_flags(None) is None


def test_backtest_view_keeps_the_best_fast_strategy_and_the_daily_trend():
    r = {"at": 1, "backtests": {"hold_pct": 40.0, "rows": [
        {"label": "Trend EMA", "return_pct": 12.0, "trades": 3, "win_rate": 66.0, "max_dd": 5.0},
        {"label": "Trend HF", "return_pct": 30.0, "trades": 9, "win_rate": 55.0, "max_dd": 8.0},
        {"label": "RSI+BB", "return_pct": None, "trades": 0}]},
        "daily": {"interval": "1d", "hold_pct": 90.0, "rows": [
            {"label": "Trend EMA", "return_pct": 120.0, "trades": 4, "win_rate": 75.0, "max_dd": 20.0}]}}
    v = ms.backtest_view(r)
    assert v["fast"]["label"] == "Trend HF" and v["fast"]["hold_pct"] == 40.0
    assert v["daily"]["return_pct"] == 120.0 and v["daily"]["interval"] == "1d"
    assert ms.backtest_view(None) is None
    assert ms.backtest_view({"backtests": {"rows": []}}) is None


def test_an_unknown_project_is_not_queued_until_added(monkeypatch):
    from app.trading.onchain import leaderboard, projects_db
    monkeypatch.setattr(projects_db, "get", lambda c, t: None)
    monkeypatch.setattr(leaderboard, "_entries", {})
    assert ms.gem_view({"chain": "robinhood", "token_address": "0xabc", "symbol": "HYDX"})["status"] == "unknown"


def test_add_enters_the_scanned_project_and_lifts_a_rejection(monkeypatch):
    from app.trading.onchain import leaderboard, projects_db
    added, rechecked = [], []
    monkeypatch.setattr(leaderboard, "add", lambda item, src, now=None: added.append((item["symbol"], src)) or True)
    monkeypatch.setattr(leaderboard, "_gone", {"robinhood:0xabc": 1.0})
    monkeypatch.setattr(leaderboard, "_entries", {})
    monkeypatch.setattr(projects_db, "recheck", lambda c, t: rechecked.append(t))
    monkeypatch.setattr(projects_db, "get", lambda c, t: None)
    monkeypatch.setattr(ms, "_recent", {})
    assert ms.add("robinhood", "0xabc")["error"].startswith("Scan")
    ms._recent["robinhood:0xabc"] = {"chain": "robinhood", "token_address": "0xabc", "symbol": "HYDX", "name": "HyperDex"}
    out = ms.add("robinhood", "0xabc")
    assert out["added"] and added == [("HYDX", "manual")] and rechecked == ["0xabc"]
    assert "robinhood:0xabc" not in leaderboard._gone
    ms._recent["solana:M"] = {"chain": "solana", "token_address": "M", "symbol": "PEPE", "name": "Pepe Inu"}
    assert "Meme" in ms.add("solana", "M")["error"]


def test_about_reads_geckoterminal_and_keeps_only_https_links():
    a = ms.about({"description": "HyperDex is a marketplace for real-world assets. More text here.",
                  "holders": 1234, "holders_split": {"top_10": "48.6"}},
                 [{"type": "twitter", "url": "https://x.com/h"}, {"type": "x", "url": "javascript:alert(1)"}])
    assert a["summary"].startswith("HyperDex is a marketplace") and a["holders"] == 1234 and a["top10_pct"] == 48.6
    assert a["socials"] == [{"type": "twitter", "url": "https://x.com/h"}]
    assert ms.about(None, None)["summary"] is None


def test_steps_follow_the_listing_checks_and_skip_what_did_not_run():
    events = []
    step = ms.Steps(events.append)
    step("name", "run")
    step.check({"key": "name", "ok": True, "detail": "not a meme name"})
    step.check({"key": "security", "ok": None, "detail": "report not available yet"})
    step.check({"key": "socials", "ok": False, "detail": "none"})
    step.skip_listing()
    states = {e["step"]: e["state"] for e in events}
    assert states["name"] == "ok" and states["security"] == "warn" and states["socials"] == "fail"
    assert states["site"] == states["github"] == states["ai"] == states["contract"] == "skip"
    assert {"step": "security", "state": "run", "detail": ""} in events
    step.check({"key": "gem", "ok": True})     # not a listing step: ignored
    assert events[-1]["step"] == "ai"


def test_assess_taps_each_check_as_it_lands():
    from app.trading.onchain import legit
    seen = []
    t = legit._Tap(lambda c: seen.append(c["key"]))
    t.append({"key": "name"})
    t.append({"key": "security"})
    assert list(t) == [{"key": "name"}, {"key": "security"}] and seen == ["name", "security"]
    boom = legit._Tap(lambda c: 1 / 0)
    boom.append({"key": "x"})
    assert len(boom) == 1


def test_report_studies_an_unknown_project_like_the_top(monkeypatch):
    import asyncio
    from app.trading.onchain import code_review, depth, judge, leaderboard, projects_db
    monkeypatch.setattr(leaderboard, "_entries", {})
    monkeypatch.setattr(projects_db, "get", lambda c, t: None)
    pil = {"site": {"score": 76, "fatal": "", "flags": ["thin docs"], "facts": {"summary": "A proof computer.", "big": "x" * 999}},
           "github": {"score": 70, "fatal": "", "facts": {"repo": "a/b", "url": "https://github.com/a/b"}},
           "tokenomics": {"score": 82, "fatal": "", "facts": {}}}

    async def analyze(item, client, skip=frozenset()):
        return pil

    async def jd(e, why, now=None, ask=None, priority=False, fresh=False):
        assert priority
        return {"verdict": "gem", "score": 81, "problems": [], "strengths": ["real product"], "confidence": 0.8}

    async def rv(e, client, now=None, ask=None, priority=False):
        return {"complexity": 70, "innovation": 60, "summary": "a zkVM"}

    monkeypatch.setattr(depth, "analyze", analyze)
    monkeypatch.setattr(judge, "get", lambda c, t: None)
    monkeypatch.setattr(judge, "judge", jd)
    monkeypatch.setattr(code_review, "get", lambda repo: None)
    monkeypatch.setattr(code_review, "review", rv)
    events = []
    gem = {"status": "unknown", "why": ""}
    rep = asyncio.run(ms.report({"chain": "solana", "token_address": "T", "symbol": "DREGG", "market_cap": 1e6,
                                 "liquidity_usd": 2e5}, gem, None, ms.Steps(events.append)))
    assert rep["summary"] == "A proof computer." and rep["judge"]["verdict"] == "gem" and rep["code"]["innovation"] == 60
    assert rep["pillars"]["site"] == {"score": 76, "flags": ["thin docs"]}
    assert gem["judge"]["score"] == 81 and gem["pillars"]["tokenomics"] == 82
    done = {e["step"]: e["state"] for e in events}
    assert done == {"pillars": "ok", "report": "ok", "code": "ok", "recheck": "warn"}
    assert rep["recheck"] == {"unverified": [], "refuted": [], "found": []}


def test_report_reads_again_a_project_already_in_the_database(monkeypatch):
    import asyncio
    from app.trading.onchain import code_review, depth, judge, leaderboard, projects_db, scout_recheck
    monkeypatch.setattr(leaderboard, "_entries", {})
    stale = {"site": {"score": 0, "fatal": "placeholder text (lorem ipsum / coming soon)", "flags": [], "facts": {}},
             "tokenomics": {"score": 76, "fatal": "", "flags": ["only 0% of liquidity locked"], "facts": {}}}
    monkeypatch.setattr(projects_db, "get", lambda c, t: {"chain": c, "token": t, "pillars": stale,
                                                          "status": "rejected", "why": "site: placeholder text"})
    monkeypatch.setattr(leaderboard, "db_entry", lambda p: {"chain": p["chain"], "token_address": p["token"],
                                                            "pillars": p["pillars"], "why": p["why"]})
    fresh = {"site": {"score": 70, "fatal": "", "flags": [], "facts": {}},
             "tokenomics": {"score": 83, "fatal": "", "flags": [], "facts": {}}}
    calls = []

    async def analyze(item, client, skip=frozenset()):
        calls.append(item["token_address"])
        return fresh

    async def jd(e, why, now=None, ask=None, priority=False, fresh=False):
        assert fresh
        return {"verdict": "watch", "score": 60, "problems": [], "strengths": []}

    async def rc(e, item, client, ask=None):
        return None

    monkeypatch.setattr(depth, "analyze", analyze)
    monkeypatch.setattr(judge, "get", lambda c, t: None)
    monkeypatch.setattr(judge, "judge", jd)
    monkeypatch.setattr(code_review, "repo_of", lambda e: None)
    monkeypatch.setattr(scout_recheck, "recheck", rc)
    events = []
    rep = asyncio.run(ms.report({"chain": "base", "token_address": "0xa", "market_cap": 3e5, "liquidity_usd": 6e4},
                                {"status": "rejected", "why": "site: placeholder text"}, None, ms.Steps(events.append)))
    assert calls == ["0xa"] and rep["pillars"]["site"]["score"] == 70
    assert {"step": "pillars", "state": "ok", "detail": "site 70 · tokenomics 83"} in events


def test_a_timed_out_recheck_never_leaves_absences_red():
    from app.trading.onchain import scout_recheck
    e = {"judge": {"problems": ["Anonymous team", "Mint enabled", "No docs found"]}}
    q = scout_recheck.quick(e)
    assert [p["text"] for p in q["confirmed"]] == ["Mint enabled"]
