"""The second look at the Scout's red points (scout_recheck.py)."""
import asyncio
import json

from app.trading.onchain import legit, scout_recheck as sr


def _entry():
    return {"judge": {"problems": ["no public GitHub found", "team is anonymous", "liquidity is tiny"]},
            "pillars": {"github": {"score": None, "flags": ["no public GitHub"]},
                        "site": {"score": 60, "flags": ["content rendered via JavaScript"], "facts": {"url": "https://x.io"}}}}


def test_red_points_take_problems_and_flags_once():
    pts = [p["text"] for p in sr.red_points(_entry())]
    assert pts == ["no public GitHub found", "team is anonymous", "liquidity is tiny", "no public GitHub",
                   "content rendered via JavaScript"]


def test_heuristic_keeps_absences_unverified_and_a_found_github_clears_them():
    pts = sr.red_points(_entry())
    out = {p["text"]: p["status"] for p in sr.heuristic(pts, {"found": [], "pages": []})}
    assert out["no public GitHub"] == "unverified" and out["liquidity is tiny"] == "confirmed"
    out = {p["text"]: p["status"] for p in sr.heuristic(pts, {"found": ["GitHub found (x): https://github.com/a"], "pages": []})}
    assert out["no public GitHub found"] == "refuted"


def test_parse_defaults_unknown_statuses_to_confirmed():
    pts = sr.red_points(_entry())[:2]
    raw = json.dumps({"items": [{"i": 0, "status": "refuted", "note": "repo a/b found"}, {"i": 1, "status": "maybe"}]})
    out = sr.parse(raw, pts)
    assert [p["status"] for p in out] == ["refuted", "confirmed"] and out[0]["note"] == "repo a/b found"
    assert sr.parse("not json", pts) is None


def test_other_pages_guesses_docs_next_to_the_site():
    pages = sr.other_pages({"website": "https://www.hyperdex.io"}, {"https://hyperdex.io"})
    assert pages[0] == "https://docs.hyperdex.io" and "https://hyperdex.io/docs" in pages
    assert sr.other_pages({}, set()) == []


def test_recheck_uses_deepseek_on_the_evidence(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "deepseek_api_key", "k")
    monkeypatch.setattr(sr, "_cache", {})

    async def none(*a, **k):
        return None

    async def page(url, client):
        return {"ok": True, "final_url": url, "text": "docs " * 60} if "docs." in url else {"ok": False}

    monkeypatch.setattr(legit, "github_find", none)
    monkeypatch.setattr(sr, "_code_search", none)
    monkeypatch.setattr(legit, "fetch_site", page)
    seen = {}

    async def ask(messages, **kw):
        seen["user"] = messages[1]["content"]
        return json.dumps({"items": [{"i": 0, "status": "unverified"}, {"i": 1, "status": "unverified"},
                                     {"i": 2, "status": "confirmed", "note": "$3k"}, {"i": 3, "status": "unverified"},
                                     {"i": 4, "status": "refuted", "note": "docs read"}]})

    e = _entry()
    rc = asyncio.run(sr.recheck(e, {"chain": "robinhood", "token_address": "0xA", "website": "https://x.io"}, None, ask=ask))
    assert [p["text"] for p in rc["confirmed"]] == ["liquidity is tiny"]
    assert len(rc["unverified"]) == 3 and rc["refuted"][0]["text"] == "content rendered via JavaScript"
    assert "page read: https://docs.x.io" in rc["found"] and "docs docs" in seen["user"]


def test_lock_flag_is_unverified_when_goplus_misses_the_main_pool(monkeypatch):
    async def gp(chain, token, client):
        return {"dex": [{"liquidity": "635.1"}, {"liquidity": "20"}]}

    monkeypatch.setattr(legit, "goplus", gp)
    note = asyncio.run(sr.lp_coverage({"chain": "robinhood", "token_address": "0xA", "liquidity_usd": 58_000}, None))
    assert "$655" in note and "$58,000" in note
    pts = [{"text": "only 0% of liquidity locked", "from": "tokenomics"}]
    assert sr.heuristic(pts, {"found": [note], "pages": []})[0]["status"] == "unverified"
    assert asyncio.run(sr.lp_coverage({"chain": "solana", "token_address": "M"}, None)) == ""
