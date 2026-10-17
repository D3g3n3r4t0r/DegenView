"""The deploy notice: a "Solo-account: whitekobra" commit goes to that
account's chat only (Lorenzo, 17/10), the rest to the repository's chat."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

from app import main
from app.notify import weekly_recap

_KOBRA = "Fix the gems page\n\nAggiornamento: pagina gemme sistemata\nSolo-account: whitekobra\n"
_ALL = "Fix the chart\n\nAggiornamento: grafico sistemato\n"


def _run(monkeypatch, tmp_path, messages, signal_only=()):
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
    monkeypatch.setattr(main.settings, "whitekobra_emails", "kobra@x.it")
    monkeypatch.setattr(main, "_LAST_SHA_FILE", tmp_path / "sha.txt")
    (tmp_path / "sha.txt").write_text("old0000", encoding="utf-8")
    users = [SimpleNamespace(email="kobra@x.it", telegram_chat_id="111", telegram_gems_chat_id="333"),
             SimpleNamespace(email="other@x.it", telegram_chat_id="222", telegram_gems_chat_id="")]
    monkeypatch.setattr(main.auth, "list_users", lambda: users)
    monkeypatch.setattr(main, "_signal_only_chats", lambda: set(signal_only))
    repo, private = [], []

    async def send_message(text):
        repo.append(text)

    async def send_to(chat, text):
        private.append((chat, text))
    monkeypatch.setattr(main.telegram, "send_message", send_message)
    monkeypatch.setattr(main.telegram, "send_to", send_to)
    asyncio.run(main._notify_deploy())
    return repo, private


def test_a_whitekobra_only_change_is_announced_to_whitekobra_only(monkeypatch, tmp_path):
    repo, private = _run(monkeypatch, tmp_path, [_KOBRA, _ALL])
    assert len(repo) == 1 and "grafico sistemato" in repo[0] and "pagina gemme" not in repo[0]
    assert len(private) == 1 and private[0][0] == "111"
    assert "pagina gemme sistemata" in private[0][1] and "grafico" not in private[0][1]


def test_a_deploy_of_private_changes_only_stays_out_of_the_repository_chat(monkeypatch, tmp_path):
    repo, private = _run(monkeypatch, tmp_path, [_KOBRA])
    assert repo == [] and [c for c, _ in private] == ["111"]


def test_the_weekly_recap_leaves_private_changes_out():
    assert weekly_recap.private_account(_KOBRA) == "whitekobra" and weekly_recap.private_account(_ALL) == ""


def test_a_signals_only_main_chat_sends_the_private_lines_to_the_gems_chat(monkeypatch, tmp_path):
    repo, private = _run(monkeypatch, tmp_path, [_KOBRA], signal_only={"111"})
    assert [c for c, _ in private] == ["333"]


def test_the_weekly_count_leaves_private_changes_out():
    text = weekly_recap.build_recap([_KOBRA, _ALL], now=1_790_000_000, resolutions_path=None)
    assert "Modifiche al codice: 1" in text and "pagina gemme" not in text
