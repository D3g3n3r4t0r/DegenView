"""How long a gem of whitekobra's view has been failing a rule, so that it
leaves only when the failure lasts (Lorenzo, 18/10: "un progetto per uscire
per capitalizzazione dalle gemme deve superare il tetto della
capitalizzazione per almeno 7 giorni consecutivi [...] altrimenti si rischia
che un progetto salga e scenda continuamente"; then the same for the score
60, the $300k floor and the FDV rule, without an emergency ceiling).

Per rule, `keep()` remembers the keys that passed it (members) and, for a
member now failing, since when. A member stays while the failure is younger
than the rule's days; one reading that passes clears the clock. A key that
never passed is not held: holding is for leaving, never for entering.
"""

from __future__ import annotations

import json
import logging
import time

from app.atomic_write import write_text_atomic
from app.trading.onchain import storage

logger = logging.getLogger(__name__)

_FILE = storage.data_file("onchain_gem_hold.json")
SAVE_EVERY_S = 60
DAY = 86400

# rule -> days a member may fail before it leaves
DAYS = {"cap": 7, "floor": 7, "fdv": 7, "score": 3}

_members: dict[str, dict[str, float]] = {}   # rule -> key -> last time it passed
_since: dict[str, dict[str, float]] = {}     # rule -> key -> first failing reading
_state = {"loaded": False, "dirty": False, "saved_at": 0.0}


def _load() -> None:
    if _state["loaded"]:
        return
    _state["loaded"] = True
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    _members.update(raw.get("members") or {})
    _since.update(raw.get("since") or {})


def _save(now: float) -> None:
    if not _state["dirty"] or now - _state["saved_at"] < SAVE_EVERY_S:
        return
    _state.update(dirty=False, saved_at=now)
    try:
        write_text_atomic(_FILE, json.dumps({"members": _members, "since": _since}), encoding="utf-8")
    except OSError:
        logger.exception("gem hold not saved")


def reset_for_tests() -> None:
    _members.clear()
    _since.clear()
    _state.update(loaded=True, dirty=False, saved_at=0.0)


def keep(key: str, rule: str, failing: bool, now: float | None = None) -> bool:
    """True if the row stays: it passes the rule, or it is a member whose
    failure is younger than DAYS[rule]."""
    _load()
    now = now or time.time()
    members, since = _members.setdefault(rule, {}), _since.setdefault(rule, {})
    if not failing:
        if key not in members or key in since:
            _state["dirty"] = True
        members[key] = now
        since.pop(key, None)
        _save(now)
        return True
    if key not in members:
        return False
    start = since.setdefault(key, now)
    if start == now:
        _state["dirty"] = True
    if now - start < DAYS[rule] * DAY:
        _save(now)
        return True
    members.pop(key, None)          # gone: it comes back only by passing again
    since.pop(key, None)
    _state["dirty"] = True
    _save(now)
    return False


def drop(key: str, rule: str) -> None:
    """Out at once (a score under main.GEM_DROP_SCORE): no longer a member."""
    _load()
    if (_members.get(rule) or {}).pop(key, None) is not None:
        _state["dirty"] = True
    (_since.get(rule) or {}).pop(key, None)


def failing_since(key: str, rule: str) -> float | None:
    _load()
    return (_since.get(rule) or {}).get(key)
