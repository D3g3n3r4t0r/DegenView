"""Lorenzo, 18/10: a gem leaves for its cap only after 7 days over the
ceiling; the same for the $300k floor and the FDV rule, 3 days for the score."""
from app.trading.onchain import gem_hold as h

DAY = 86400


def test_a_member_stays_until_the_failure_lasts():
    assert h.keep("k", "cap", False, 1_000.0)
    assert h.keep("k", "cap", True, 2_000.0)                 # over the ceiling: held
    assert h.keep("k", "cap", True, 2_000.0 + 6.9 * DAY)
    assert not h.keep("k", "cap", True, 2_000.0 + 7 * DAY)   # 7 days in a row: out
    assert not h.keep("k", "cap", True, 2_000.0 + 8 * DAY)   # and not back until it passes


def test_one_reading_back_under_resets_the_clock():
    h.keep("k", "cap", False, 0.0)
    h.keep("k", "cap", True, 1.0)
    h.keep("k", "cap", False, 5 * DAY)
    assert h.keep("k", "cap", True, 6 * DAY) and h.keep("k", "cap", True, 12 * DAY)
    assert h.failing_since("k", "cap") == 6 * DAY


def test_holding_is_for_leaving_never_for_entering():
    assert not h.keep("new", "cap", True, 1.0)


def test_the_score_rule_waits_three_days():
    h.keep("k", "score", False, 0.0)
    assert h.keep("k", "score", True, 1.0) and not h.keep("k", "score", True, 1.0 + 3 * DAY)


def test_a_dropped_member_is_out_at_once():
    h.keep("k", "score", False, 0.0)
    h.drop("k", "score")
    assert not h.keep("k", "score", True, 1.0)
