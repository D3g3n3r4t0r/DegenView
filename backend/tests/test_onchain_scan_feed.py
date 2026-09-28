"""The scanners' live tape (Lorenzo, 28/09: "voglio vedere i ticker girare,
non cose ferme")."""
from app.trading.onchain import scan_feed


def setup_function():
    scan_feed.reset_for_tests()


def test_counts_the_hour_and_the_rate():
    now = 10_000.0
    scan_feed.event("solana", "OLD", "fail", now=now - 4000)
    scan_feed.seen(120, now=now - 60)
    scan_feed.event("solana", "AAA", "fail", "no website", now=now - 30)
    scan_feed.event("solana", "BBB", "pass", now=now - 20)
    scan_feed.event("solana", "CCC", "seen", "below thresholds", now=now - 10)
    f = scan_feed.snapshot(now)
    assert f["seen_1h"] == 121 and f["checked_1h"] == 2
    assert f["passed_1h"] == 1 and f["rejected_1h"] == 1
    assert f["per_min"] == round((121 + 2) / 10, 1)
    assert [x["symbol"] for x in f["feed"][:3]] == ["CCC", "BBB", "AAA"]


def test_a_nameless_pool_is_not_on_the_tape():
    scan_feed.event("solana", "", "fail")
    assert scan_feed.snapshot()["feed"] == []


def test_the_tape_keeps_only_the_latest():
    for i in range(scan_feed.FEED_KEEP + 10):
        scan_feed.event("bsc", f"T{i}", "seen", now=1000.0 + i)
    feed = scan_feed.snapshot(2000.0)["feed"]
    assert len(feed) == scan_feed.FEED_KEEP and feed[0]["symbol"] == f"T{scan_feed.FEED_KEEP + 9}"
