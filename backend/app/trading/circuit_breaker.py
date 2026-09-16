"""Kill switch and circuit breaker for automated trading.

Checks are non-blocking reads — they never raise, they return a
(allowed: bool, reason: str) pair that the caller logs and acts on.
"""
from app.config import settings


def check_halt() -> tuple[bool, str]:
    """Return (True, "") when trading is allowed, (False, reason) when blocked."""
    if settings.trading_halt:
        return False, "trading in pausa (kill switch attivo)"
    return True, ""
