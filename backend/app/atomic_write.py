"""Crash-safe file writes (audit B02).

`Path.write_text` truncates first and writes after: a crash, OOM kill or
full disk in between leaves an empty or half-written JSON, and most stores
here treat an unreadable file as "start empty" and then overwrite it —
users.json holds every account and the encrypted wallet keys. Writing to a
temporary file in the same directory and renaming over the target is atomic
on POSIX: readers see the old file or the new one, never a torn one.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
