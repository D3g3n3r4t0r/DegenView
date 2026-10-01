from app.trading.onchain import gem_track


def _e(token, price=1.0):
    return {"chain": "solana", "token_address": token, "symbol": token.upper(), "price_usd": price}


def test_record_lists_picks_and_misses(monkeypatch, tmp_path):
    monkeypatch.setattr(gem_track, "_STORE_FILE", tmp_path / "track.json")
    monkeypatch.setattr(gem_track, "bench_price", lambda chain, now: None)
    gem_track.reset_for_tests()
    try:
        gem_track.enter(_e("a"), 70, 1, now=1000)
        gem_track.enter(_e("b"), 60, 2, now=2000)
        rej = next(f"r{i}" for i in range(500) if gem_track.sampled("solana", f"r{i}"))
        gem_track.decide(_e(rej), "rejected", "no site", now=1000)
        gem_track.sample("solana", "a", 1.5, now=1000 + 86400)
        gem_track.sample("solana", rej, 2.5, now=1000 + 3 * 86400)
        out = gem_track.record()
        assert [p["token_address"] for p in out["picks"]] == ["b", "a"]
        a = out["picks"][1]
        assert a["checkpoint"] == {"days": 1, "ret": 0.5, "excess": None}
        assert a["now"] == 0.5
        assert [m["token_address"] for m in out["missed"]] == [rej]
        assert out["missed"][0]["why"] == "no site"
        assert out["stats"]["tracked"] == 2
    finally:
        gem_track.reset_for_tests()
