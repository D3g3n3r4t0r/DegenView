import asyncio
import json

import pytest

from app.trading.onchain import solana_clusters as sc, storage, sync_sells as ss, sync_watch as sw, wallet_clusters as wc

MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
# On-curve (wallet) owners, case kept: Solana addresses are case-sensitive.
W = ["4ncj9vRi8ZACsJkbts24swLFgcSzvVrNMA2FRnyT4VTL", "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
     "6hNRqrwpY44nfKhqNC1NH1eG5pjdMEWD6pCpDCLeCbqn"]
ACC = ["Acc1" + "a" * 40, "Acc2" + "b" * 40, "Acc3" + "c" * 40]


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    return tmp_path


def test_same_slot_links():
    assert sc.same_slot_links({"a": 5, "b": 5, "c": 9}) == [("a", "b")]


def test_moves_sell_vs_outflow(monkeypatch):
    monkeypatch.setattr(sc.legit, "is_program_account", lambda o: o == "POOL")

    def tx(gainer):
        return {"slot": 7, "blockTime": 100, "transaction": {"signatures": ["sig"]},
                "meta": {"preTokenBalances": [{"mint": MINT, "owner": W[0], "uiTokenAmount": {"amount": "50"}}],
                         "postTokenBalances": [{"mint": MINT, "owner": W[0], "uiTokenAmount": {"amount": "20"}},
                                               {"mint": MINT, "owner": gainer, "uiTokenAmount": {"amount": "30"}}]}}
    assert sc._moves(tx("POOL"), MINT, W[0])[0] | {} == {"block": 7, "ts": 100, "tx": "sig", "log_index": 0,
                                                         "from": W[0], "to": "pool", "amount": 30}
    assert sc._moves(tx(W[1]), MINT, W[0])[0]["to"] == W[1]
    assert sc._moves(tx(W[1]), MINT, W[1]) == []


def test_build_and_watch_keep_case(data, monkeypatch):
    rep = {"token": {"supply": 1000, "decimals": 6}, "markets": [], "knownAccounts": {},
           "topHolders": [{"owner": o, "address": a, "pct": 10} for o, a in zip(W, ACC)]}

    async def fake_report(mint):
        return rep

    async def fake_sigs(acc, until=None):
        slot = {ACC[0]: 5, ACC[1]: 5, ACC[2]: 9}[acc]
        return [{"signature": acc + "new", "slot": slot + 1}, {"signature": acc + "old", "slot": slot}]

    async def fake_sells(cfg):
        return [{"block": 10, "ts": 2_000_000_000, "tx": "t1", "log_index": 0, "from": W[0], "to": "pool", "amount": 40},
                {"block": 10, "ts": 2_000_000_001, "tx": "t2", "log_index": 0, "from": W[1], "to": "pool", "amount": 40}], {}
    monkeypatch.setattr(sc, "report", fake_report)
    monkeypatch.setattr(sc, "signatures", fake_sigs)
    monkeypatch.setattr(sc, "new_sells", fake_sells)
    monkeypatch.setattr(sc.legit, "is_program_account", lambda o: False)
    monkeypatch.setattr(sw, "KEEP_S", 10**10)
    res = asyncio.run(wc.build("solana", MINT, "X"))
    assert [set(c["wallets"]) for c in res["clusters"]] == [{W[0], W[1]}]
    cfg = sw.watched()[0]
    assert cfg["token"] == MINT and cfg["accounts"][W[0]] == ACC[0] and cfg["state"]["last_sig"][ACC[0]] == ACC[0] + "new"
    asyncio.run(sw.run_all(force=True))
    out = json.loads(ss.report_path("solana", MINT).read_text())
    assert out["token"] == MINT and out["coverage"]["note"].startswith("top 20")
    assert out["events"] and out["risk"]["score"] > 0
    assert wc.request("solana", "not-an-address", now=0) is False
