"""Pause and resume Telegram notifications per group (notify/pause.py).

The page sends a group kind, never a chat id: an account can only pause the
chats saved on it, and the system chat only an admin (settings.admin_emails).
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import auth
from app import guest as guest_links
from app.config import email_allowlist, settings
from app.models import User
from app.notify import pause, telegram

router = APIRouter()

Kind = Literal["main", "signals", "gems", "system"]
LABELS = {"main": "Main chat", "signals": "Alerts chat", "gems": "Gems chat", "system": "System messages"}
WHAT = {"main": "optimizations, listings, and gems or signals when no separate chat is set",
        "signals": "strategy signals and price alerts",
        "gems": "new gems found by the research",
        "system": "deploys, server errors, infrastructure"}


def _member(user: User = Depends(auth.get_current_user)) -> User:
    if guest_links.is_guest(user):
        raise HTTPException(status_code=403, detail="Not available on a guest link.")
    return user


def _chats(user: User) -> dict[str, list[str]]:
    out = {"main": [user.telegram_chat_id], "signals": [user.telegram_signal_chat_id],
           "gems": [user.telegram_gems_chat_id]}
    if user.email.lower() in email_allowlist(settings.admin_emails):
        out["system"] = telegram._chat_ids()
    return {k: [c for c in v if c] for k, v in out.items() if any(v)}


def _mask(chat_id: str) -> str:
    return chat_id if len(chat_id) <= 6 else f"…{chat_id[-4:]}"


@router.get("/api/telegram/groups")
async def telegram_groups(user: User = Depends(_member)) -> list[dict]:
    out = []
    for kind, ids in _chats(user).items():
        rows = [pause.state(c) for c in ids]
        live = [r for r in rows if r and not r.get("expired")]
        until = [r["until"] for r in live]
        out.append({
            "kind": kind, "label": LABELS[kind], "what": WHAT[kind],
            "chats": [_mask(c) for c in ids],
            "paused": bool(live),
            "until": (0 if 0 in until else max(until)) if live else None,
            "skipped": sum(r.get("skipped", 0) for r in live),
        })
    return out


class PauseRequest(BaseModel):
    kind: Kind
    minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 30)   # None = until resumed


class ResumeRequest(BaseModel):
    kind: Kind


def _ids(user: User, kind: str) -> list[str]:
    ids = _chats(user).get(kind)
    if not ids:
        raise HTTPException(status_code=404, detail="No chat of this kind on your account.")
    return ids


@router.post("/api/telegram/pause")
async def telegram_pause(body: PauseRequest, user: User = Depends(_member)) -> dict:
    for c in _ids(user, body.kind):
        pause.pause(c, user.id, body.minutes)
    return {"ok": True}


@router.post("/api/telegram/resume")
async def telegram_resume(body: ResumeRequest, user: User = Depends(_member)) -> dict:
    for c in _ids(user, body.kind):
        row = pause.resume(c)
        if row is not None:
            await telegram.send_to(c, pause.resume_notice(row), force=True)
    return {"ok": True}
