"""Append-only audit log for every order action (submit, fill, error)."""
import json
import time
from pathlib import Path

# backend/data, the persistent volume like every other store. It used to be
# parent.parent (app/data, inside the image and the repo): in production the
# log was lost at every deploy, and test runs appended to a tracked file.
_AUDIT_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "audit.jsonl"


def log_order(
    action: str,
    exchange: str,
    symbol: str,
    signal_type: str,
    result: dict,
    *,
    entry_id: str = "",
    strategy_name: str = "",
    is_futures: bool = False,
) -> None:
    """Append one line to data/audit.jsonl.

    action: "submit" | "fill" | "error"
    Never raises — a log failure must not interrupt the order flow.
    """
    record = {
        "ts": int(time.time()),
        "action": action,
        "exchange": exchange,
        "symbol": symbol,
        "signal_type": signal_type,
        "is_futures": is_futures,
        "entry_id": entry_id,
        "strategy_name": strategy_name,
        "result": result,
    }
    try:
        _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass
