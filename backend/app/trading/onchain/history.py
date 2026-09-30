"""Append-only log of evaluation events per token.

Lorenzo, 30/09: the Trace must show every step, "TUTTI". The verdict in
projects_db, the judge and research caches and the pillar checks keep only
their latest value, so every re-evaluation overwrote the one before. Each
of those writers now also appends one line here; the journey reads these
lines, so past re-evaluations survive. Nothing is rewritten: when the file
grows past MAX_BYTES the oldest half is dropped (the last lines stay).
Writing never raises: a failed append must not break an analysis.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from app.trading.onchain.storage import data_file

logger = logging.getLogger(__name__)

_FILE = data_file("onchain_history.jsonl")
MAX_BYTES = 40 * 1024 * 1024
_lock = threading.Lock()


def append(key: str, source: str, rec: dict, t: float | None = None) -> None:
    try:
        line = json.dumps({"t": round(t or time.time(), 3), "key": key, "source": source, "rec": rec},
                          separators=(",", ":"), ensure_ascii=False, default=str)
        with _lock:
            with _FILE.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if _FILE.stat().st_size > MAX_BYTES:
                lines = _FILE.read_text(encoding="utf-8").splitlines()
                tmp = _FILE.with_suffix(".tmp")
                tmp.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")
                tmp.replace(_FILE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("history: append failed: %s", exc)


def of(key: str) -> list[dict]:
    """Every logged event of one token (`chain:token`), oldest first."""
    needle = json.dumps(key)
    out = []
    try:
        with _lock, _FILE.open(encoding="utf-8") as fh:
            for line in fh:
                if needle in line:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("key") == key:
                        out.append(row)
    except FileNotFoundError:
        pass
    return out
