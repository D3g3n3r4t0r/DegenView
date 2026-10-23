"""Lorenzo, 22/10: the deep re-check by facts, clusters without false
positives, and every cluster report built again under the new rules."""
import time

from app.trading.onchain import coordinated_sells as cs, depth, fact_check, solana_clusters, storage
from app.trading.onchain import wallet_clusters as wc

SOL = "So1aNaMint1111111111111111111111111111pump"


def test_a_bad_area_drops_before_the_ai_and_warnings_only_watch():
    areas = [fact_check._area("pool", "warn", "Liquidity thin", "DexScreener"),
             fact_check._area("usage", "good", "volume", "x")]
    v = fact_check.verdict(areas, {"verdict": "ok", "confidence": 0.9}, excellent=False)
    assert v["keep"] is True and "pool" in v["reason"]
    areas.append(fact_check._area("holders", "bad", "Risk 96/100", "clusters"))
    assert fact_check.verdict(areas, None, excellent=False) == {"keep": False, "reason": "Risk 96/100", "by": "holders"}


def test_a_confident_scam_never_drops_an_excellent_project():
    scam = {"verdict": "scam", "confidence": 0.95, "reason": "copied site"}
    assert fact_check.verdict([], scam, excellent=False)["keep"] is False
    assert fact_check.verdict([], scam, excellent=True)["keep"] is True


def test_the_contract_area_never_carries_rugchecks_linked_wallets():
    p = {"score": 0, "fatal": "linked wallets hold 40% of supply", "facts": {"holders": 900, "top10_pct": 20},
         "flags": ["linked wallets hold 40% of supply (807 wallets)"]}
    a = fact_check.contract(p)
    assert a["status"] == "good" and "linked" not in a["line"]
    assert fact_check.contract({**p, "fatal": "accounts can be frozen (freeze enabled)"})["status"] == "bad"


def test_holders_come_only_from_the_cluster_report():
    assert fact_check.holders(None, "chain not covered")["status"] == "unknown"
    f = {"risk": 10, "linked_supply_pct": 13.0, "linked_clusters": 1, "linked_wallets": 3, "sell_waves_7d": 0}
    assert fact_check.holders(f, "ready")["status"] == "bad"
    assert fact_check.holders({**f, "linked_supply_pct": 1.0}, "ready")["status"] == "good"


def test_one_airdrop_sender_links_nobody_in_the_same_slot():
    senders = {f"w{i}": "AirDropper1111111111111111111111111111111" for i in range(solana_clusters.AIRDROP_MIN)}
    senders["x"] = "pool"
    assert solana_clusters.same_airdrop(senders, "w0", "w1") is True
    few = {"a": "Sender11111111111111111111111111111111111", "b": "Sender11111111111111111111111111111111111"}
    assert solana_clusters.same_airdrop(few, "a", "b") is False


def test_pool_accounts_and_their_owners_are_out():
    rep = {"knownAccounts": {"K": {"type": "AMM"}},
           "markets": [{"pubkey": "M", "liquidityA": "LA", "liquidityB": "LB",
                        "liquidityAAccount": {"owner": "OA"}, "liquidityBAccount": {"owner": "OB"}}]}
    assert solana_clusters.pool_accounts(rep) == {"K", "M", "LA", "LB", "OA", "OB"}


def _report(rules, share=0.191):
    return {"version": 1, "chain": "solana", "token": SOL, "updated_at": time.time(),
            "risk": {"score": 0, "reasons": []}, "events": [],
            "clusters": [{"id": "a1", "share": share, "links": ["same_slot"],
                          "wallets": [{"address": f"W{i}", "share": share / 23} for i in range(23)]}],
            "coverage": {"source": "helius", "rules": rules}}


def test_the_structure_risk_is_read_from_clusters_built_under_the_new_rules():
    assert cs.clean(_report(2))["risk"]["score"] == 96
    # An older build may hold an airdrop read as a cluster: its stated risk stays until it is rebuilt.
    assert cs.clean(_report(None))["risk"]["score"] == 0


def test_every_token_built_under_old_rules_is_built_again():
    st = {"tokens": {"solana-a": {"built_at": 100}, "base-b": {"failed_at": 50}, "x": {}}}
    assert wc.rebuild_old_rules(st) == 2 and st["rules"] == wc.RULES
    assert st["tokens"]["solana-a"]["built_at"] is None
    assert wc.rebuild_old_rules(st) == 0


def test_rugchecks_linked_wallets_give_way_to_the_cluster_report():
    report = {"token": {"supply": 1000}, "topHolders": [{"address": "A", "owner": "O", "pct": 5}],
              "totalHolders": 900, "mintAuthority": None, "freezeAuthority": None,
              "insiderNetworks": [{"tokenAmount": 400, "size": 807}]}
    clusters = {"linked_supply_pct": 2.0, "linked_wallets": 4}
    out = depth.judge_tokenomics_solana(report, clusters=clusters)
    assert out["facts"]["linked_pct"] == 2.0 and not out.get("fatal")
    assert any("from our wallet cluster report" in f for f in out["flags"])


def test_ai_facts_reads_the_solana_report(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    from app.trading.onchain import sync_sells
    monkeypatch.setattr("app.trading.onchain.leaderboard.clusters_changed", lambda chain, token: False)
    sync_sells.write_report(_report(2))
    assert cs.ai_facts("solana", SOL)["risk"] == 96
