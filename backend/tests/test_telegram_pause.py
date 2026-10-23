"""Telegram notifications paused per group (asked on 23/10)."""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.config import settings
from app.models import User
from app.notify import pause, telegram


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(pause, "_STORE_FILE", tmp_path / "telegram_pauses.json")
    monkeypatch.setattr(pause, "_store", None)
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    sent: list[tuple[str, str]] = []

    async def deliver(client, chat_id, text):
        sent.append((chat_id, text))
        return True
    monkeypatch.setattr(telegram, "_deliver", deliver)
    return sent


def test_a_paused_chat_gets_nothing_and_counts_it(store):
    pause.pause("-100", "u1", None)
    assert asyncio.run(telegram.send_to("-100", "signal")) is False
    assert asyncio.run(telegram.send_to("-100", "signal 2")) is False
    assert asyncio.run(telegram.send_to("-200", "elsewhere")) is True
    assert store == [("-200", "elsewhere")]
    assert pause.state("-100")["skipped"] == 2


def test_answers_to_the_bot_go_through_a_pause(store):
    pause.pause("-100", "u1", None)
    assert asyncio.run(telegram.send_to("-100", "Chat ID: -100", force=True)) is True
    assert pause.state("-100")["skipped"] == 0


def test_a_pause_that_ran_out_lifts_itself_with_the_count(store, monkeypatch):
    pause.pause("-100", "u1", 60)
    asyncio.run(telegram.send_to("-100", "missed"))
    real = time.time
    monkeypatch.setattr(pause.time, "time", lambda: real() + 3601)
    assert asyncio.run(telegram.send_to("-100", "after")) is True
    assert store == [("-100", "▶️ Notifiche riprese: 1 messaggio non inviato durante la pausa."), ("-100", "after")]
    assert pause.state("-100") is None


def test_system_messages_skip_a_paused_dev_chat(store, monkeypatch):
    monkeypatch.setattr(settings, "telegram_dev_chat_ids", "-9,-8")
    monkeypatch.setattr(telegram, "signal_only_chats", lambda: set())
    pause.pause("-9", "admin", None)
    asyncio.run(telegram.send_message("deploy"))
    assert store == [("-8", "deploy")]


@pytest.fixture
def client(monkeypatch):
    user = User(id="u1", email="u@example.com", password_hash="x",
                telegram_chat_id="111", telegram_signal_chat_id="-100", telegram_gems_chat_id="")
    main.app.dependency_overrides[auth.get_current_user] = lambda: user
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_the_page_pauses_and_resumes_its_own_groups(client, store):
    groups = client.get("/api/telegram/groups").json()
    assert [g["kind"] for g in groups] == ["main", "signals"]       # no gems chat, not an admin
    assert all(not g["paused"] for g in groups)
    assert client.post("/api/telegram/pause", json={"kind": "signals", "minutes": 60}).status_code == 200
    g = {x["kind"]: x for x in client.get("/api/telegram/groups").json()}
    assert g["signals"]["paused"] and g["signals"]["until"] > time.time() and not g["main"]["paused"]
    asyncio.run(telegram.send_to("-100", "x"))
    assert client.get("/api/telegram/groups").json()[1]["skipped"] == 1
    assert client.post("/api/telegram/resume", json={"kind": "signals"}).status_code == 200
    assert store[-1][0] == "-100" and "1 messaggio non inviato" in store[-1][1]
    assert not pause.is_paused("-100")


def test_only_your_chats_and_the_system_one_only_for_admins(client):
    assert client.post("/api/telegram/pause", json={"kind": "gems"}).status_code == 404
    assert client.post("/api/telegram/pause", json={"kind": "system"}).status_code == 404
    assert client.post("/api/telegram/pause", json={"kind": "other"}).status_code == 422
