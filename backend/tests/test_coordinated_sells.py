import asyncio
import json

from app.trading.onchain import coordinated_sells as cs


def test_sample_is_a_valid_report():
    raw = json.loads(cs.SAMPLE.read_text(encoding="utf-8"))
    r = cs.clean(raw)
    assert r and r["token"] == "0x96f455a90a80dcf0c2df6703ea4ba3bedf286e43"
    assert len(r["events"]) == len(raw["events"])        # every wave points at a known cluster


def test_clean_drops_bad_rows_and_clamps():
    r = cs.clean({"version": 1, "token": "0xAB", "clusters": [{"id": "c1", "share": 3, "wallets": [{"address": "0x1"}, {}]}],
                  "events": [{"id": "e1", "cluster": "c1", "ts": 10}, {"id": "e2", "cluster": "nope", "ts": 5}]})
    assert r["token"] == "0xab" and r["clusters"][0]["share"] == 1 and len(r["clusters"][0]["wallets"]) == 1
    assert [e["id"] for e in r["events"]] == ["e1"]
    assert cs.clean({"version": 2, "token": "0x1"}) is None


def test_alerts_once_per_wave_and_never_for_the_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(cs.storage, "DATA_DIR", tmp_path)
    sent = []

    async def send(text):
        sent.append(text)
        return True

    assert asyncio.run(cs.notify_once(send, "u")) == 0          # no report yet: the sample is never alerted
    (tmp_path / "coordinated_sells").mkdir()
    now = 1_000_000.0
    report = {"version": 1, "chain": "robinhood", "token": "0xab", "symbol": "XYZ",
              "clusters": [{"id": "c1", "share": 0.1, "wallets": [{"address": "0x1", "share": 0.05}]}],
              "events": [{"id": "big", "cluster": "c1", "ts": now - 60, "wallets": 4, "share_sold": 0.02},
                         {"id": "small", "cluster": "c1", "ts": now - 60, "wallets": 4, "share_sold": 0.001},
                         {"id": "old", "cluster": "c1", "ts": now - 86400, "wallets": 4, "share_sold": 0.02}]}
    (tmp_path / "coordinated_sells" / "robinhood-0xab.json").write_text(json.dumps(report))
    assert asyncio.run(cs.notify_once(send, "u", now)) == 1
    assert "XYZ" in sent[0] and "2,00%" in sent[0]
    assert asyncio.run(cs.notify_once(send, "u", now)) == 0       # already sent


def test_from_analysis_maps_the_engine_output(tmp_path, monkeypatch):
    monkeypatch.setattr(cs.storage, "DATA_DIR", tmp_path)
    a = {"wallets": 2, "sellers": 2, "sync_pct": 2.5, "risk": {"score": 64},
         "groups": [{"first_block": 7, "last_block": 8, "first_ts": 100, "last_ts": 160,
                     "wallets": ["0x1", "0x2"], "same_block": True, "supply_pct": 2.5, "txs": 2}]}
    r = cs.from_analysis(a, "robinhood", "0xAB", ["0x1", "0x2"], holdings={"0x1": 0.03}, now=200)
    assert r["clusters"][0]["share"] == 0.03 and r["clusters"][0]["links"] == ["same_block_sells"]
    e = r["events"][0]
    assert (e["id"], e["window_s"], e["wallets"], e["share_sold"]) == ("c1-7", 60, 2, 0.025)
    assert cs.reports()[1] is True          # nothing written yet: the sample
    cs.write(r)
    assert cs.reports() == ([r], False)


def test_clean_keeps_map_edges_and_sellers():
    r = cs.clean({"version": 1, "token": "0xab",
                  "clusters": [{"id": "c1", "wallets": [{"address": "0x1"}, {"address": "0x2"}], "edges": [["0x1", "0x2"], ["bad"]]}],
                  "events": [{"id": "e1", "cluster": "c1", "ts": 10, "sellers": ["0x1"]}]})
    assert r["clusters"][0]["edges"] == [["0x1", "0x2"]] and r["events"][0]["sellers"] == ["0x1"]


def test_high_risk_report_excludes_the_token(tmp_path, monkeypatch):
    from app.trading.onchain import coordinated_sells as cs, leaderboard as lb, storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cs, "_excl_cache", (0.0, {}))
    tok = "0x" + "ab" * 20
    d = tmp_path / "coordinated_sells"
    d.mkdir()
    rep = {"version": 1, "chain": "robinhood", "token": tok, "updated_at": 1_000_000,
           "risk": {"score": 74, "reasons": []}, "clusters": [], "events": []}
    (d / f"robinhood-{tok}.json").write_text(json.dumps(rep))
    assert cs.exclusion("robinhood", tok, now=1_000_100) == "coordinated sells: risk 74"
    monkeypatch.setattr(cs, "_excl_cache", (0.0, {}))
    assert cs.exclusion("robinhood", tok, now=1_000_000 + 8 * 86400) == ""   # stale report
    monkeypatch.setattr(cs, "_excl_cache", (0.0, {}))
    rep["risk"]["score"] = 59
    (d / f"robinhood-{tok}.json").write_text(json.dumps(rep))
    assert lb.crash_reason("robinhood", tok) == ""


def test_only_linked_clusters_and_tokens_on_screen_alert(tmp_path, monkeypatch):
    """Lorenzo, 23/10 ("Applica A e C"): the top-holders group never alerts,
    and only tokens in the Top or Early do; another token's wave is kept
    for later, should the token enter the Top within the alert window."""
    monkeypatch.setattr(cs.storage, "DATA_DIR", tmp_path)
    (tmp_path / "coordinated_sells").mkdir()
    sent = []

    async def send(text):
        sent.append(text)
        return True

    now = 1_000_000.0
    for tok, sym in (("0xab", "INTOP"), ("0xcd", "ELSEWHERE")):
        report = {"version": 1, "chain": "base", "token": tok, "symbol": sym,
                  "clusters": [{"id": "c1", "share": 0.1, "wallets": [{"address": "0x1", "share": 0.05}]},
                               {"id": "top", "share": 0.4, "wallets": [{"address": "0x2", "share": 0.2}]}],
                  "events": [{"id": "linked", "cluster": "c1", "ts": now - 60, "wallets": 3, "share_sold": 0.02},
                             {"id": "holders", "cluster": "top", "ts": now - 60, "wallets": 5, "share_sold": 0.05}]}
        (tmp_path / "coordinated_sells" / f"base-{tok}.json").write_text(json.dumps(report))
    shown = {cs.shown_key("Base", "0xAB")}
    assert asyncio.run(cs.notify_once(send, "u", now, shown=shown)) == 1
    assert "INTOP" in sent[0]
    assert asyncio.run(cs.notify_once(send, "u", now, shown=shown | {cs.shown_key("base", "0xcd")})) == 1
    assert "ELSEWHERE" in sent[1]                    # entered the Top: its recent wave alerts now
    assert len(sent) == 2                            # the "top" group never did
