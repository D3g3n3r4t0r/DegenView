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
