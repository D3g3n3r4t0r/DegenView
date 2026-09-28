"""X as a source for DeepSeek's dossier: off without a token, counted when on."""
import asyncio

from app.trading.onchain import judge, x_signal


def setup_function():
    x_signal.reset_for_tests()


def test_off_without_a_token(monkeypatch):
    monkeypatch.setattr(x_signal.settings, "x_bearer_token", "")
    assert asyncio.run(x_signal.lookup({"chain": "solana", "token_address": "T", "symbol": "ROUTER"})) is None
    assert "X: not read" in judge.dossier({"chain": "solana", "symbol": "R", "name": "R"}, "")


def test_query_uses_cashtag_name_and_address():
    q = x_signal.query({"symbol": "ROUTER", "name": "Solrouter", "token_address": "6Sj"})
    assert q == '($ROUTER OR "Solrouter" OR 6Sj) -is:retweet'


def test_summary_counts_authors_and_followers(monkeypatch):
    monkeypatch.setattr(x_signal.settings, "x_bearer_token", "t")
    data = {"data": [{"text": "a", "author_id": "1", "public_metrics": {"like_count": 5}},
                     {"text": "b", "author_id": "1", "public_metrics": {"like_count": 50}},
                     {"text": "c", "author_id": "2", "public_metrics": {}}],
            "includes": {"users": [{"id": "1", "public_metrics": {"followers_count": 10}},
                                   {"id": "2", "public_metrics": {"followers_count": 5000}}]}}

    class R:
        status_code = 200

        def json(self):
            return data

    class C:
        calls = 0

        async def get(self, url, **kw):
            C.calls += 1
            assert kw["headers"]["Authorization"] == "Bearer t"
            return R()

    e = {"chain": "solana", "token_address": "T", "symbol": "ROUTER", "name": "Solrouter"}
    x = asyncio.run(x_signal.lookup(e, client=C()))
    assert x["posts_7d"] == 3 and x["authors"] == 2 and x["top_posts"][0] == "b"
    asyncio.run(x_signal.lookup(e, client=C()))
    assert C.calls == 1                                    # cached for a day
    assert "3 posts by 2 authors" in judge.dossier({**e, "pillars": {}}, "", x)
