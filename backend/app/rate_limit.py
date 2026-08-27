"""
Lightweight in-memory rate limiting for auth endpoints — no new dependency,
no external store, appropriate for this app's scale (single process, no
horizontal scaling). Resets on restart/redeploy, which is an acceptable
trade-off here: the goal is slowing down a live brute-force attempt, not
maintaining a permanent ban list.

Callers use two independent keys per login attempt — one scoped to the
client IP (blocks spraying many accounts from one source) and one scoped
to the email (blocks hammering one account from many sources/IPs) — so
either axis alone trips the lock.
"""

import time

_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 300  # failures older than this don't count toward the limit
_LOCKOUT_SECONDS = 300  # once tripped, stays locked this long regardless of new attempts

_attempts: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}


def _prune(key: str, now: float) -> None:
    recent = [t for t in _attempts.get(key, []) if now - t < _WINDOW_SECONDS]
    if recent:
        _attempts[key] = recent
    else:
        _attempts.pop(key, None)


def is_locked(key: str) -> bool:
    until = _locked_until.get(key)
    return until is not None and time.time() < until


def register_failure(key: str) -> None:
    now = time.time()
    _prune(key, now)
    _attempts.setdefault(key, []).append(now)
    if len(_attempts[key]) >= _MAX_ATTEMPTS:
        _locked_until[key] = now + _LOCKOUT_SECONDS


def register_success(key: str) -> None:
    _attempts.pop(key, None)
    _locked_until.pop(key, None)
