"""Standing instructions for the Telegram DeepSeek (deepseek_desk.teach)."""
import asyncio

import pytest

from app.notify import deepseek_desk as dd


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "_INSTR_FILE", tmp_path / "i.json")
    dd._instructions.clear()
    yield
    dd._instructions.clear()


def test_teach_list_forget_and_reload():
    assert dd.teach("rispondi sempre con i numeri", now=1)["saved"] == 1
    dd.teach("  guarda prima la tab Strategies  ")
    assert [i["text"] for i in dd.instructions()] == ["rispondi sempre con i numeri", "guarda prima la tab Strategies"]
    assert dd.forget(1)["removed"] == "rispondi sempre con i numeri"
    assert "error" in dd.forget(9)
    dd._instructions.clear()
    dd._load_instructions()
    assert [i["text"] for i in dd.instructions()] == ["guarda prima la tab Strategies"]
    assert "guarda prima la tab Strategies" in dd._system_prompt("ctx")


def test_only_the_owner_gets_the_teaching_tools(monkeypatch):
    seen = []

    async def fake(messages, kind, tools=None, **kw):
        seen.append({t["function"]["name"] for t in tools or []})
        return {"content": "ok"}
    monkeypatch.setattr(dd, "ask_message", fake)
    monkeypatch.setattr(dd, "spent_today", lambda kind: 0)
    asyncio.run(dd.answer("guest", "ciao", "ctx", tools={}))
    asyncio.run(dd.answer("owner", "ciao", "ctx", tools={}, can_teach=True))
    assert "ricorda" not in seen[0] and {"ricorda", "dimentica", "istruzioni"} <= seen[1]
