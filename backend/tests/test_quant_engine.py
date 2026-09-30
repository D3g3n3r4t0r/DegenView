import json
import sqlite3
from pathlib import Path

import pytest

from app.trading.onchain import quant_engine as q
from app.trading.onchain import quant_memory as memory
from app.trading.onchain import quant_runtime as runtime


def bars(n=100, offset=0):
    return [[offset + i * 300, 100 + i, 102 + i, 99 + i, 101 + i, 1000] for i in range(n)]


def case(n=100, offset=0, token="A"):
    return {"chain": "solana", "token": token, "feed": q.FEED, "bars": bars(n, offset), "born": 0,
            "start": offset + 60 * 300, "end": offset + n * 300,
            "gem_eligible": True, "eligibility_at": offset + 60 * 300}


def signals(rows, strategy):
    return [(i == 61, i == 80) for i in range(len(rows))]


def test_policy_search_includes_fixed_baselines_and_boundaries():
    policies = q.candidates([300, 3600], [86400])
    assert len(policies) == 3
    progressive = policies[-1]
    assert progressive.interval(86399) == 300
    assert progressive.interval(86400) == 3600
    with pytest.raises(ValueError):
        q.Policy(((0, 3600), (86400, 300)))
    with pytest.raises(ValueError):
        q.candidates(q.ALLOWED, [86400, 172800, 259200])


def test_complete_candles_only_and_gap_not_filled():
    raw = bars(10)
    assert len(q.aggregate(raw, 900, 899)) == 0
    assert len(q.aggregate(raw, 900, 900)) == 1
    assert len(q.aggregate(raw[:1] + raw[2:], 900, 3000)) == 2
    with pytest.raises(ValueError):
        q.clean_bars([raw[0], raw[0]])
    bad = bars(1)
    bad[0][2] = float("nan")
    with pytest.raises(ValueError):
        q.clean_bars(bad)


def test_alert_never_buys_and_fill_is_next_open():
    c = case()
    result = q.replay(c, q.Policy(((0, 300),)), provider=signals)
    assert result["events"][0]["t"] == 62 * 300
    assert result["events"][0]["reason"] == "trend_entry"
    assert result["events"][0]["price"] == c["bars"][62][1]
    assert result["events"][1]["t"] == 81 * 300
    expected = 181 / 162 * (1 - .003) ** 2 * (1 - .01) / (1 + .01) - 1
    assert result["ret"] == pytest.approx(expected)
    empty = q.replay(c, q.Policy(((0, 300),)), provider=lambda rows, _: [(False, False)] * len(rows))
    assert empty["entries"] == 0


def test_policy_does_not_change_timeframe_of_open_position():
    p = q.Policy(((0, 300), (63 * 300, 900)))
    result = q.replay(case(), p, provider=signals)
    assert [e["tf"] for e in result["events"]] == [300, 300]


def test_future_bars_do_not_change_past_result():
    c = case()
    past = {**c, "end": 70 * 300}
    a = q.replay(past, q.Policy(((0, 300),)), provider=signals)
    past["bars"] = past["bars"][:70]
    b = q.replay(past, q.Policy(((0, 300),)), provider=signals)
    assert a == b


@pytest.mark.parametrize("field,value", [("born", None), ("gem_eligible", False), ("eligibility_at", 999999)])
def test_unknown_or_retrospective_eligibility_cannot_enter(field, value):
    c = case()
    c[field] = value
    assert q.replay(c, q.Policy(((0, 300),)), provider=signals)["state"] == "unavailable"


def test_gap_invalidates_research_and_catastrophe_is_not_profitable():
    c = case()
    c["bars"].pop(70)
    assert q.replay(c, q.Policy(((0, 300),)), provider=signals)["state"] == "unavailable"
    c = case()
    c["untradeable_at"] = 70 * 300
    result = q.replay(c, q.Policy(((0, 300),)), provider=signals)
    assert result["ret"] == -1
    assert result["drawdown"] == 1


def dataset():
    return [case(offset=i * 40000 // 300 * 300, token=str(i)) for i in range(9)]


def test_research_is_deterministic_and_holdout_cannot_select_winner():
    data = dataset()
    kwargs = dict(train_end=120000, validation_end=240000, min_cases=2, min_entries=2, provider=signals)
    policies = q.candidates([300, 900], [86400])
    a = q.experiment(data, policies, **kwargs)
    assert a == q.experiment(data, policies, **kwargs)
    assert a["status"] == "review_required"
    assert a["llm_calls"] == 0
    for c in data[6:]:
        c["untradeable_at"] = c["start"] + 4 * 300
    b = q.experiment(data, policies, **kwargs)
    assert a["selected"] == b["selected"]
    assert b["status"] == "not_validated"


def test_small_dataset_and_project_overlap_fail_closed():
    data = dataset()
    a = q.experiment(data, q.candidates([300], []), train_end=120000, validation_end=240000, provider=signals)
    assert a["selected"] is None
    with pytest.raises(ValueError):
        q.experiment(data + [data[0]], q.candidates([300], []), train_end=120000, validation_end=240000)


def test_memory_deduplicates_versions_and_preserves_case_sensitive_identity(tmp_path):
    path = tmp_path / "observer.sqlite3"
    e = {"chain": "solana", "token_address": "AbC", "rug": True, "rug_why": "price -90%", "features": {"liq": 50}}
    assert memory.record([e], path=path, now=1) == 1
    assert memory.record([e], path=path, now=2) == 0
    assert memory.record([{**e, "token_address": "abc"}], path=path, now=2) == 1
    assert memory.record([{**e, "rug_why": "pool gone"}], path=path, now=3) == 1
    with sqlite3.connect(path) as db:
        rows = [json.loads(r[0]) for r in db.execute("SELECT payload FROM quant_incidents")]
    assert len(rows) == 3
    assert all(r["classification"] == "suspected_incident" and r["confirmed_fraud"] is False for r in rows)


def test_pattern_report_counts_healthy_rejections_and_does_not_create_veto():
    rows = [{"features": {"liq": n}, "rug": label} for n, label in [(1, True), (2, False), (9, False), (8, True)]]
    rows.append({"features": {"liq": float("nan")}, "rug": True})
    r = memory.pattern_report(rows, "liq", 3, min_support=2)
    assert r["false_rejection_rate"] == .5
    assert r["unknown"] == 1
    assert r["automatic_veto"] is False


def test_activation_requires_integrity_review_and_paper_run(tmp_path):
    path = tmp_path / "policy.json"
    assert runtime.approved(path) is None
    report = q.experiment(dataset(), q.candidates([300], []), train_end=120000, validation_end=240000,
                          min_cases=2, min_entries=2, provider=signals)
    report["report_hash"] = q.fingerprint(report)
    m = {"report": report, "approved": True, "reviewer": "review", "paper_run_id": "paper-1", "active_from": 999999}
    path.write_text(json.dumps(m))
    assert runtime.approved(path)["policy"].stages == ((0, 300),)
    m["report"]["costs"]["slippage"] = 0
    path.write_text(json.dumps(m))
    assert runtime.approved(path) is None


def test_live_gate_requires_fresh_signal_and_current_gem_evidence(monkeypatch):
    monkeypatch.setattr(runtime, "approved", lambda: {"reviewed": True})
    a = {"last": {"price": 10, "at": 100}, "quant_system": {"eligible": True, "state": "in", "in_at": 100, "evaluated_at": 100}}
    monkeypatch.setattr(runtime, "gem_verdict", lambda a, now: (True, "ok"))
    assert runtime.can_enter(a, 150)
    assert not runtime.can_enter(a, 99)
    assert not runtime.can_enter(a, 1001)
    monkeypatch.setattr(runtime, "gem_verdict", lambda a, now: (False, "new fatal"))
    assert not runtime.can_enter(a, 150)


def test_modules_have_no_model_or_order_dependency():
    for module in (q, memory, runtime):
        source = Path(module.__file__).read_text()
        assert "deepseek_desk.ask" not in source
        assert "execute_order(" not in source


def test_patterns_require_independent_healthy_controls_and_holdout():
    rows = []
    for cohort in range(3):
        for i in range(12):
            rows.append({"chain": "solana", "token_address": f"{cohort}-{i}",
                         "features": {"liq": 1 if i < 4 else 100}, "rug": i < 4,
                         "observed_at": cohort * 100 + 1, "label_at": cohort * 100 + 2})
    rules = [{"feature": "liq", "threshold": 10}]
    kwargs = dict(train_end=100, validation_end=200, min_support=2)
    result = memory.validate_patterns(rows, rules, **kwargs)
    assert result["status"] == "review_required" and not result["automatic_veto"]
    for row in rows[24:28]:
        row["rug"] = False
    result = memory.validate_patterns(rows, rules, **kwargs)
    assert result["status"] == "not_validated"


def test_memory_exports_migration_time_honestly(tmp_path):
    path = tmp_path / "history.sqlite3"
    memory.record([{"chain": "solana", "token_address": "abc", "at": 10, "rug": True}], path=path, now=100)
    row = memory.export_latest(path)[0]
    assert row["label_at"] == 100 and row["observed_at"] == 10


def test_prospective_collector_freezes_eligibility_before_export(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "gem_verdict", lambda a, now: (True, "ok"))
    from app.trading.onchain import projects_db, leaderboard, outcomes
    monkeypatch.setattr(projects_db, "get", lambda *args: {"launched_at": 1})
    monkeypatch.setattr(leaderboard, "db_entry", lambda p: p)
    monkeypatch.setattr(outcomes, "features", lambda e, now: {"liq": 10000})
    a = {"chain": "solana", "token_address": "A"}
    path = tmp_path / "observer.sqlite3"
    memory.capture_case(a, bars(100), 30000, path)
    memory.capture_case(a, bars(110), 31800, path)
    exported = memory.export_cases(path)
    assert len(exported) == 1
    assert exported[0]["eligibility_at"] == 30000
    assert exported[0]["end"] == 31800
    assert exported[0]["features"] == {"liq": 10000}
    memory.capture_case(a, bars(112), 32100, path)
    assert memory.export_cases(path) == exported
