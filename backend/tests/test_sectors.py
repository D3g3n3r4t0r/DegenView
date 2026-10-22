from app.trading.onchain import sectors


def _e(sym, score, z=None, cap=1e6, ch=0.0, inn=True):
    return {"chain": "solana", "token_address": sym.lower(), "symbol": sym, "score": score, "z": z,
            "market_cap": cap, "change_24h": ch, "in": inn}


def _arenas(champ="VEIL", extra=()):
    priv = [_e(champ, 80, 1.8), _e("DREGG", 70, 0.9), _e("SHRD", 50, -0.5, inn=False)]
    ai = [_e("CRAWL", 66, 0.4), _e("ARGO", 64, 0.2), _e("NYXA", 62, 0.0), *extra]
    return [{"key": "ai_agents", "label": "AI Agents", "median": 63, "entries": ai},
            {"key": "privacy", "label": "Privacy", "median": 70, "entries": priv},
            {"key": "empty", "label": "Empty", "median": 0, "entries": []}]


def test_summarize_orders_by_strength_not_size():
    s = sectors.summarize(_arenas())
    assert [x["key"] for x in s] == ["privacy", "ai_agents"]   # empty arena dropped
    assert s[0]["strength"] == round((1.8 + 0.9 + 0) / 3, 2)
    assert [e["symbol"] for e in s[0]["top"]] == ["VEIL", "DREGG", "SHRD"]
    assert s[0]["change_24h"] == 0.0


def test_z_missing_falls_back_to_points_over_floor():
    s = sectors.summarize([{"key": "a", "label": "A", "median": 50, "entries": [_e("X", 60), _e("Y", 50)]}])
    assert s[0]["strength"] == round((10 / sectors.SPREAD_FLOOR + 0) / 2, 2)


def test_record_keeps_one_snapshot_per_hour_and_prunes():
    s = sectors.summarize(_arenas())
    snaps = sectors.record(s, 1000.0, [], persist=False)
    assert len(snaps) == 1
    assert sectors.record(s, 1000.0 + 60, snaps, persist=False) is snaps
    old = [{"t": 1000.0 + 3 * 86400 + h * 3600, "sectors": {}, "ranked": {}} for h in range(48)]
    now = 1000.0 + 6 * 86400
    kept = sectors.prune(old, now)
    assert len(kept) == len({int(x["t"] // 86400) for x in old if now - x["t"] > sectors.HOURLY_KEEP_S}) + \
        sum(1 for x in old if now - x["t"] <= sectors.HOURLY_KEEP_S)


def test_today_lists_new_champion_entry_drop_and_move():
    t0 = 1_000_000.0
    before = sectors.summarize(_arenas(extra=[_e("GRID", 63, 0.0)]))
    snaps = sectors.record(before, t0, [], persist=False)
    after_arenas = _arenas(champ="BOND")
    after_arenas[1]["entries"][1]["score"] = 80        # DREGG +10
    after = sectors.summarize(after_arenas)
    out = sectors.today(after, snaps, t0 + 86400)
    kinds = {(i["kind"], i["gem"]["symbol"]) for i in out["items"]}
    assert ("champion", "BOND") in kinds
    assert ("entered", "BOND") in kinds
    assert ("dropped", "VEIL") in kinds and ("dropped", "GRID") in kinds
    assert ("moved", "DREGG") in kinds
    assert out["counts"]["champion"] == 1
    assert out["items"][0]["kind"] == "champion"


def test_today_and_momentum_wait_for_old_enough_readings():
    t0 = 1_000_000.0
    s = sectors.summarize(_arenas())
    snaps = sectors.record(s, t0, [], persist=False)
    assert sectors.today(s, snaps, t0 + 60)["since"] is None
    assert all(v is None for v in sectors.momentum(s, snaps, t0 + 86400).values())
    week = sectors.momentum(s, snaps, t0 + 7 * 86400)
    assert week["privacy"] == 0.0
