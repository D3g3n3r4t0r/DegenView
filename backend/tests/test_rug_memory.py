"""The rug memory read from outcomes' journal (rug_memory.py)."""
import pytest

from app.trading.onchain import outcomes, rug_memory as rm


@pytest.fixture(autouse=True)
def _clean():
    outcomes.reset_for_tests()
    yield
    outcomes.reset_for_tests()


def _entry(i, *, rug, mcap, liq, top, sec_ok, chain="solana", hours=None):
    now = 1_000_000.0
    e = {"chain": chain, "symbol": f"T{i}", "name": "", "token_address": f"addr{i:04d}xyz", "pair_address": f"p{i}",
         "decision": "listed", "at": now, "entry": {"at": now, "price": 1.0}, "rug": rug,
         "rug_at": now + hours * 3600 if rug and hours else None, "rug_why": "liquidity pulled: 5% left" if rug else "",
         "max_ret": 0.1, "min_ret": -0.9 if rug else -0.1, "closed": True, "sells_seen": True,
         "features": {"mcap": mcap, "liq": liq, "liq_mcap": liq / mcap, "age_h": 1.0, "top_holder_pct": top,
                      "checks": {"security": {"ok": sec_ok}, "socials": {"ok": True}}}}
    outcomes._journal[f"{chain}:{e['token_address']}"] = e
    return e


def _fill():
    for i in range(6):
        _entry(i, rug=True, mcap=30_000, liq=3_000, top=40, sec_ok=False, hours=2 + i)
    for i in range(6, 14):
        _entry(i, rug=False, mcap=500_000, liq=100_000, top=5, sec_ok=True)


def test_similar_cases_are_the_look_alikes():
    _fill()
    near = rm.similar({"mcap": 28_000, "liq": 2_500, "liq_mcap": 0.09, "top_holder_pct": 38,
                       "checks": {"security": {"ok": False}}}, "solana", now=2e6)
    assert len(near) == 5 and all(c["outcome"] == "rug" for c in near)
    assert rm.summary({"mcap": 28_000, "liq": 2_500, "top_holder_pct": 38, "checks": {"security": {"ok": False}}},
                      "solana", pool=rm.cases(2e6)).startswith("5 similar: 5 rug, after 2h, 3h, 4h")


def test_circumstances_contrast_rugs_with_the_rest():
    _fill()
    s = rm.circumstances(now=2e6)
    assert s["n"] == 14 and s["rugs"] == 6 and s["median_hours_to_rug"] == 4.5
    assert s["how"] == {"liquidity pulled": 6}
    assert s["numbers"]["top_holder_pct"] == {"rug_median": 40.0, "other_median": 5.0}
    assert s["checks"]["security"] == {"rug_ok_share": 0.0, "other_ok_share": 1.0}
    assert "6 rugs of 14 decided" in rm.circumstances_text(now=2e6)


def test_lookup_by_symbol_or_address():
    _fill()
    assert rm.lookup("$t3", now=2e6)[0]["outcome"] == "rug"
    assert rm.lookup("addr0007", now=2e6)[0]["symbol"] == "T7"
    assert rm.lookup("nothing", now=2e6) == []
