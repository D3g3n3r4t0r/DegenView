"""Audit B02: a failed write must leave the previous file intact."""
from __future__ import annotations

import json

import pytest

from app import atomic_write


def test_replaces_content(tmp_path):
    p = tmp_path / "users.json"
    atomic_write.write_text_atomic(p, json.dumps([1]))
    atomic_write.write_text_atomic(p, json.dumps([1, 2]))
    assert json.loads(p.read_text()) == [1, 2]
    assert [f.name for f in tmp_path.iterdir()] == ["users.json"]


def test_crash_mid_write_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / "users.json"
    p.write_text('[{"id": "keep"}]')

    def boom(fd):
        raise OSError("disk full")

    monkeypatch.setattr(atomic_write.os, "fsync", boom)
    with pytest.raises(OSError):
        atomic_write.write_text_atomic(p, "[]")
    assert json.loads(p.read_text()) == [{"id": "keep"}]
    assert [f.name for f in tmp_path.iterdir()] == ["users.json"]
