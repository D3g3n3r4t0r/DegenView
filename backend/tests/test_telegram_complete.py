"""
I messaggi Telegram arrivano interi.

Lorenzo: "i messaggi su Telegram arrivano tagliati, non sono mai completi".
L'avviso di deploy tagliava ogni riga a 120 caratteri; un messaggio oltre il
limite di Telegram (4096) o con un "<" fuori posto non arrivava proprio.
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import settings
from app.notify import telegram
from app.notify.weekly_recap import build_recap


def test_short_text_is_one_piece():
    assert telegram.chunks("ciao\nmondo") == ["ciao\nmondo"]


def test_long_text_is_split_on_lines_and_nothing_is_lost():
    lines = [f"• riga {i} " + "x" * 90 for i in range(200)]
    text = "\n".join(lines)
    parts = telegram.chunks(text)
    assert len(parts) > 1
    assert all(len(p) <= telegram.MAX_LEN for p in parts)
    assert "\n".join(parts) == text


def test_a_single_huge_line_is_split_too():
    text = "parola " * 2000
    parts = telegram.chunks(text)
    assert all(len(p) <= telegram.MAX_LEN for p in parts)
    assert " ".join(parts).split() == text.split()


def test_plain_drops_tags_and_keeps_text():
    assert telegram.plain('<b>BTC</b> a <a href="x">1 &lt; 2</a>') == "BTC a 1 < 2"


def _fake_transport(sent: list, reject_html: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        if reject_html and body.get("parse_mode") == "HTML":
            return httpx.Response(400, json={"ok": False, "description": "can't parse entities"})
        sent.append(body)
        return httpx.Response(200, json={"ok": True})
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch, transport):
    real = httpx.AsyncClient
    monkeypatch.setattr(telegram.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
    monkeypatch.setattr(settings, "telegram_bot_token", "t", raising=False)


def test_long_message_is_delivered_in_several_messages(monkeypatch):
    sent: list = []
    _patch_client(monkeypatch, _fake_transport(sent))
    text = "\n".join(f"riga {i} " + "y" * 100 for i in range(100))
    assert asyncio.run(telegram.send_to("42", text))
    assert len(sent) > 1
    assert "\n".join(b["text"] for b in sent) == text


def test_bad_html_falls_back_to_plain_text_instead_of_vanishing(monkeypatch):
    sent: list = []
    _patch_client(monkeypatch, _fake_transport(sent, reject_html=True))
    assert asyncio.run(telegram.send_to("42", "⚠️ Ordine FALLITO <b>X</b>: <class 'Err'>"))
    assert sent[0]["text"] == "⚠️ Ordine FALLITO X: <class 'Err'>"
    assert "parse_mode" not in sent[0]


def test_weekly_recap_lists_every_change():
    msgs = [f"Title {i}\n\nAggiornamento: modifica numero {i} con <dettagli>" for i in range(30)]
    text = build_recap(msgs, now=1_800_000_000, resolutions_path=None)
    assert all(f"modifica numero {i} con &lt;dettagli&gt;" in text for i in range(30))
    assert "e altre" not in text
