"""Deep studies asked through the repo: request format, the tick against a
faked GitHub and DeepSeek, and the public endpoints. No network."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.notify import deepseek_desk, deepseek_studies as ds

NOW = 1_790_000_000.0


class _Resp:
    def __init__(self, status: int, data=None, text: str = ""):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeGitHub:
    """The contents listing and the raw files of requests/."""

    def __init__(self, files: dict[str, tuple[str, str]]):
        self.files = files          # id -> (sha, text)
        self.downloads: list[str] = []

    async def get(self, url, **kw):
        if url == ds.LIST_URL:
            return _Resp(200, [{"name": f"{i}.md", "type": "file", "sha": sha, "download_url": f"raw://{i}"}
                               for i, (sha, _) in self.files.items()]
                         + [{"name": "README.md", "type": "file", "sha": "x", "download_url": "raw://README"}])
        if url.startswith("raw://"):
            rid = url[6:]
            self.downloads.append(rid)
            return _Resp(200, text=self.files[rid][1])
        return _Resp(404, [])

    async def aclose(self):
        pass


class FakeAsk:
    def __init__(self, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    async def __call__(self, messages, *, kind, max_tokens, http=None, **kw):
        self.calls.append({"messages": messages, "kind": kind, "max_tokens": max_tokens})
        if self.fail:
            raise RuntimeError("down")
        return f"answer {len(self.calls)}"


async def _fake_dossier(ref, client):
    return f"## {ref}\nfacts"


@pytest.fixture(autouse=True)
def _private(monkeypatch, tmp_path):
    monkeypatch.setattr(ds, "_FILE", tmp_path / "studies.json")
    monkeypatch.setattr(deepseek_desk, "_STORE_FILE", tmp_path / "usage.json")
    ds.reset_for_tests()
    yield
    ds.reset_for_tests()


def _tick(gh, ask, now=NOW):
    return asyncio.run(ds.tick(now=now, client=gh, ask=ask, dossier_fn=_fake_dossier))


def test_parse_request_headers_and_body():
    r = ds.parse_request("001-x", "# Gem models\ntokens: solana:Mint1, Base:0xAb\nfollow_up: 000-a\n"
                                  "max_tokens: 99999\n\nWhy do they fail?\n\nmax_tokens: in body stays")
    assert r["title"] == "Gem models"
    assert r["tokens"] == ["solana:Mint1", "base:0xAb"]
    assert r["follow_up"] == "000-a"
    assert r["max_tokens"] == ds.MAX_TOKENS_CAP
    assert r["prompt"] == "Why do they fail?\n\nmax_tokens: in body stays"


def test_parse_request_defaults():
    r = ds.parse_request("002", "# T\n\nJust a question")
    assert (r["tokens"], r["follow_up"], r["max_tokens"], r["prompt"]) == ([], None, ds.DEFAULT_MAX_TOKENS,
                                                                          "Just a question")


def test_tick_answers_once_per_sha_and_again_on_edit():
    gh = FakeGitHub({"001-a": ("s1", "# A\ntokens: solana:M\n\nStudy it")})
    ask = FakeAsk()
    assert _tick(gh, ask) == ["001-a"]
    rec = ds.get("001-a")
    assert rec["answer"] == "answer 1" and rec["sha"] == "s1" and rec["dossiers"] == ["## solana:M\nfacts"]
    user = ask.calls[0]["messages"][-1]["content"]
    assert "Study it" in user and "solana:M" in user and ask.calls[0]["kind"] == "study"
    assert ask.calls[0]["messages"][0]["role"] == "system"
    assert _tick(gh, ask, NOW + 600) == [] and len(ask.calls) == 1 and gh.downloads == ["001-a"]
    gh.files["001-a"] = ("s2", "# A v2\n\nStudy it better")
    assert _tick(gh, ask, NOW + 1200) == ["001-a"]
    assert ds.get("001-a")["title"] == "A v2" and ds.get("001-a")["answer"] == "answer 2"


def test_follow_up_carries_prior_turns():
    gh = FakeGitHub({"001-a": ("s1", "# A\n\nFirst question"),
                     "002-b": ("s2", "# B\nfollow_up: 001-a\n\nSecond question")})
    ask = FakeAsk()
    assert _tick(gh, ask) == ["001-a", "002-b"]
    msgs = ask.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"] == "First question" and msgs[2]["content"] == "answer 1"
    assert msgs[3]["content"] == "Second question"


def test_follow_up_waits_for_missing_answer():
    gh = FakeGitHub({"002-b": ("s2", "# B\nfollow_up: 001-a\n\nQ")})
    ask = FakeAsk()
    assert _tick(gh, ask) == [] and not ask.calls
    assert "waiting" in ds.get("002-b")["error"]


def test_daily_cap(monkeypatch):
    monkeypatch.setattr(ds, "DAILY_MAX", 2)
    gh = FakeGitHub({f"00{i}": (f"s{i}", f"# T{i}\n\nQ{i}") for i in range(4)})
    ask = FakeAsk()
    assert len(_tick(gh, ask)) == 2
    assert len(_tick(gh, ask, NOW + 600)) == 0
    assert len(ask.calls) == 2


def test_failure_retried_after_an_hour_at_most_three_times():
    gh = FakeGitHub({"001": ("s1", "# T\n\nQ")})
    ask = FakeAsk(fail=True)
    _tick(gh, ask)
    assert "down" in ds.get("001")["error"] and ds.get("001")["tries"] == 1
    _tick(gh, ask, NOW + 600)
    assert len(ask.calls) == 1                     # not before an hour
    _tick(gh, ask, NOW + 3700)
    _tick(gh, ask, NOW + 7400)
    _tick(gh, ask, NOW + 11100)
    assert len(ask.calls) == 3 and not ds.get("001")["answer"]


def test_unresolved_token_dossier(monkeypatch):
    class Empty:
        async def get(self, url, **kw):
            return _Resp(200, [])
    text = asyncio.run(ds.dossier("solana:Nothing111", Empty()))
    assert "could not be resolved" in text


def test_endpoints_are_public_and_return_the_record():
    from app import main
    gh = FakeGitHub({"001-a": ("s1", "# A\n\nQ")})
    _tick(gh, FakeAsk())
    client = TestClient(main.app)
    lst = client.get("/api/deepseek/studies")
    assert lst.status_code == 200
    assert lst.json() == [{"id": "001-a", "title": "A", "at": NOW, "has_answer": True, "error": None}]
    one = client.get("/api/deepseek/studies/001-a")
    assert one.status_code == 200 and one.json()["answer"] == "answer 1" and one.json()["prompt"] == "Q"
    assert client.get("/api/deepseek/studies/nope").status_code == 404


def test_dossier_reads_board_entry_without_touching_it(monkeypatch):
    from app.trading.onchain import depth, leaderboard
    entry = {"chain": "solana", "token_address": "Tok1", "symbol": "GEM", "name": "Gem", "market_cap": 500_000,
             "liquidity_usd": 40_000, "launched_at": NOW - 30 * 86400,
             "pillars": {n: {"score": 70, "facts": {"excerpt": "we build a DEX"}, "flags": []} for n in depth.WEIGHTS},
             "overall": {"score": 70}}
    monkeypatch.setitem(leaderboard._entries, "solana:Tok1", entry)
    snapshot = repr(entry)

    async def no_analysis(*a, **k):
        raise AssertionError("pillars are complete, nothing to fetch")
    monkeypatch.setattr(depth, "analyze", no_analysis)

    class Dex:
        async def get(self, url, **kw):
            return _Resp(200, [{"baseToken": {"symbol": "GEM"}, "marketCap": 750_000, "liquidity": {"usd": 60_000},
                                "volume": {"h24": 12_000}, "pairCreatedAt": (NOW - 40 * 86400) * 1000,
                                "info": {"websites": [{"url": "https://gem.xyz"}]}}])
    text = asyncio.run(ds.dossier("solana:Tok1", Dex()))
    assert "$750,000" in text and "$12,000" in text and "Rules verdict" in text
    assert "<project_text>" in text and "we build a DEX" in text and len(text) <= ds.DOSSIER_CHARS
    assert repr(entry) == snapshot
