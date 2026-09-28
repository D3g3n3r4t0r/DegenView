"""What the scanners are looking at, token by token, for the live tape.

Lorenzo, 28/09: "qui voglio capire la capacita' di scansione del sistema,
voglio vedere i ticker girare, non cose ferme". The radar and the listings
hunt already judge dozens of pools a minute, but the page only showed the
few still waiting. Every judgement lands here (memory only: a restart
starts a new tape) and the Strategies page scrolls it with the counts.
"""
from __future__ import annotations

import time
from collections import deque

WINDOW_S = 3600
RATE_S = 600
FEED_KEEP = 60

# verdicts: seen (below thresholds), check (checks running), wait, pass,
# fail, tested (strategies run on the chart), alert
_feed: deque = deque(maxlen=FEED_KEEP)
_events: deque = deque(maxlen=50_000)   # (t, verdict)
_seen: deque = deque(maxlen=5_000)      # (t, n) pools looked at


def reset_for_tests() -> None:
    _feed.clear()
    _events.clear()
    _seen.clear()


def seen(n: int, now: float | None = None) -> None:
    """Pools looked at in bulk (a radar round), not one by one."""
    if n > 0:
        _seen.append((now or time.time(), int(n)))


def event(chain: str | None, symbol: str | None, verdict: str, why: str = "", now: float | None = None) -> None:
    if not symbol:
        return
    now = now or time.time()
    _events.append((now, verdict))
    if verdict == "seen":
        _seen.append((now, 1))
    _feed.appendleft({"t": now, "chain": chain or "", "symbol": str(symbol)[:16], "v": verdict,
                      "why": str(why or "")[:60]})


def snapshot(now: float | None = None) -> dict:
    now = now or time.time()
    while _events and now - _events[0][0] > WINDOW_S:
        _events.popleft()
    while _seen and now - _seen[0][0] > WINDOW_S:
        _seen.popleft()
    by: dict[str, int] = {}
    for t, v in _events:         # timestamps can arrive out of order
        if now - t <= WINDOW_S:
            by[v] = by.get(v, 0) + 1
    judged = sum(n for v, n in by.items() if v != "seen")
    recent = sum(1 for t, v in _events if v != "seen" and now - t <= RATE_S)
    recent += sum(n for t, n in _seen if now - t <= RATE_S)
    return {"at": now, "seen_1h": sum(n for t, n in _seen if now - t <= WINDOW_S), "checked_1h": judged,
            "passed_1h": by.get("pass", 0) + by.get("alert", 0), "rejected_1h": by.get("fail", 0),
            "tested_1h": by.get("tested", 0), "per_min": round(recent / (RATE_S / 60), 1),
            "feed": list(_feed)}
