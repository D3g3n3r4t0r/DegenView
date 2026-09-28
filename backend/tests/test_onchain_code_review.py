"""DeepSeek legge il codice dei progetti: complessita' e innovazione."""
import asyncio
import json

from app.trading.onchain import code_review


def _tree():
    return [
        {"path": "src/core.rs", "type": "blob", "size": 50_000},
        {"path": "src/protocol.rs", "type": "blob", "size": 40_000},
        {"path": "src/crypto.rs", "type": "blob", "size": 30_000},
        {"path": "src/net.rs", "type": "blob", "size": 20_000},
        {"path": "src/small.rs", "type": "blob", "size": 100},
        {"path": "tests/core_test.rs", "type": "blob", "size": 90_000},
        {"path": "vendor/lib.rs", "type": "blob", "size": 80_000},
        {"path": "node_modules/x.js", "type": "blob", "size": 70_000},
        {"path": "README.md", "type": "blob", "size": 5_000},
    ]


def test_pick_files_skips_tests_and_vendor_and_keeps_the_largest():
    picked = code_review.pick_files(_tree())
    assert picked == ["src/core.rs", "src/protocol.rs", "src/crypto.rs", "src/net.rs"]


def test_parse_clamps_and_rejects_missing_scores():
    out = code_review.parse(json.dumps({"complexity": 150, "innovation": -20, "summary": "x"}))
    assert out["complexity"] == 100 and out["innovation"] == 0
    assert code_review.parse(json.dumps({"complexity": 50})) is None
    assert code_review.parse("not json") is None


def test_review_reads_the_code_and_caches(monkeypatch):
    code_review.reset_for_tests()
    monkeypatch.setattr(code_review, "_save", lambda: None)
    calls = {"ask": 0}

    class R:
        def __init__(self, status, payload=None, text=""):
            self.status_code = status
            self._payload = payload
            self.text = text

        def json(self):
            return self._payload

    class C:
        async def get(self, url, **kw):
            return R(200, text="fn main() {}")

    async def fake_gh_get(client, url, **kw):
        if "/readme" in url:
            return R(200, text="# Acme\nA protocol.")
        if "/git/trees/" in url:
            return R(200, {"tree": _tree()})
        return R(200, {"default_branch": "main", "pushed_at": "2026-09-01T00:00:00Z"})

    monkeypatch.setattr(code_review.legit, "gh_get", fake_gh_get)

    async def ask(messages, **kw):
        calls["ask"] += 1
        assert "<code" in messages[1]["content"]
        return json.dumps({"complexity": 90, "innovation": 85, "fork_of": None, "summary": "real protocol",
                           "strengths": ["crypto"], "concerns": ["docs"]})

    import app.notify.deepseek_desk as desk
    monkeypatch.setattr(desk, "note", lambda *a, **k: None)
    e = {"symbol": "ACME", "chain": "solana", "token_address": "x",
         "pillars": {"github": {"facts": {"repo": "acme/core"}}}}
    out = asyncio.run(code_review.review(e, C(), ask=ask))
    assert out["complexity"] == 90 and out["innovation"] == 85
    again = asyncio.run(code_review.review(e, C(), ask=ask))
    assert again["complexity"] == 90 and calls["ask"] == 1
