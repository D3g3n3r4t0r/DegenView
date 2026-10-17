"""The deploy notice: a "Solo-account: whitekobra" commit sends no Telegram
at all (Lorenzo, 17/10), the rest goes to the repository's chat."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

from app import main
from app.notify import weekly_recap

_KOBRA = "Fix the gems page\n\nAggiornamento: pagina gemme sistemata\nSolo-account: whitekobra\n"
_ALL = "Fix the chart\n\nAggiornamento: grafico sistemato\n"


def _run(monkeypatch, tmp_path, messages):
    commits = [{"sha": f"{i:07d}abc", "commit": {"message": m}} for i, m in enumerate(messages)]
    commits.append({"sha": "old0000", "commit": {"message": "old"}})

    class _Client:
        async def get(self, *a, **kw):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: commits)

    @contextlib.asynccontextmanager
    async def pooled(**kw):
        yield _Client()
    monkeypatch.setattr(main.http_client, "pooled", pooled)
    monkeypatch.setattr(main.settings, "telegram_bot_token", "t")
    monkeypatch.setattr(main.settings, "github_api_token", "g")
    monkeypatch.setattr(main, "_LAST_SHA_FILE", tmp_path / "sha.txt")
    (tmp_path / "sha.txt").write_text("old0000", encoding="utf-8")
    sent = []

    async def send_message(text):
        sent.append(text)
    monkeypatch.setattr(main.telegram, "send_message", send_message)
    asyncio.run(main._notify_deploy())
    return sent


def test_a_whitekobra_only_change_is_left_out_of_the_deploy_notice(monkeypatch, tmp_path):
    sent = _run(monkeypatch, tmp_path, [_KOBRA, _ALL])
    assert len(sent) == 1 and "grafico sistemato" in sent[0] and "pagina gemme" not in sent[0]


def test_a_deploy_of_whitekobra_only_changes_sends_nothing(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, [_KOBRA]) == []


def test_the_weekly_recap_leaves_private_changes_out():
    assert weekly_recap.private_account(_KOBRA) == "whitekobra" and weekly_recap.private_account(_ALL) == ""
    text = weekly_recap.build_recap([_KOBRA, _ALL], now=1_790_000_000, resolutions_path=None)
    assert "Modifiche al codice: 1" in text and "pagina gemme" not in text
