"""DeepSeek on Telegram, and the ledger of what DeepSeek does for us.

Lorenzo, 27/09: "mettiamo possibilita' di parlare con deepseek su
telegram?" and "voglio un riepilogo giornaliero di quanti token ci ha fatto
risparmiare, su telegram".

- Chat: a message to the bot (private chat, or a mention / reply / /ask in
  a group) from a known chat gets DeepSeek's answer, with the site's data
  (the system, the latest alerts, the writer's wallet and autotrader) in
  the prompt. A short memory per chat; /reset clears it. A daily token cap.
- Ledger: every DeepSeek call on the server (chat, token reviews) is
  counted per day and kind, from the API's own usage. The GitHub PR
  reviews run elsewhere; their usage rides in a hidden marker in each
  review comment and is read back from GitHub for the recap.
- Recap: once a day, in Italian: calls, tokens, what DeepSeek cost, and
  what the same tokens would have cost on Claude (an estimate at list
  prices, said as such).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.trading.onchain.storage import data_file

logger = logging.getLogger(__name__)

_STORE_FILE = data_file("deepseek_usage.json")
ROME = ZoneInfo("Europe/Rome")
RECAP_HOUR = 21                      # Rome time
# $ per million tokens. DeepSeek: deepseek-chat list price (cache miss).
# Claude: what these calls would have used instead (Sonnet list price).
PRICE = {"deepseek": (0.28, 0.42), "claude": (3.0, 15.0)}
CHAT_DAILY_TOKENS = 300_000
MEMORY = 10                          # messages kept per chat
KINDS = {"chat": "chat Telegram", "scanner": "scanner (giudizio token)", "research": "letture approfondite gemme",
         "review": "revisioni token",
         "pr_review": "revisioni PR"}

_lock = threading.Lock()
_state: dict = {"days": {}, "recap_sent": ""}
_memory: dict[str, list[dict]] = {}


def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        _state["days"] = raw.get("days") or {}
        _state["recap_sent"] = raw.get("recap_sent") or ""


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps(_state, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass


def reset_for_tests() -> None:
    _state.update(days={}, recap_sent="")
    _memory.clear()


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, ROME).strftime("%Y-%m-%d")


def record(kind: str, tokens_in: int, tokens_out: int, now: float | None = None) -> None:
    now = now or time.time()
    with _lock:
        day = _state["days"].setdefault(day_of(now), {})
        k = day.setdefault(kind, {"calls": 0, "in": 0, "out": 0})
        k["calls"] += 1
        k["in"] += int(tokens_in or 0)
        k["out"] += int(tokens_out or 0)
        cutoff = day_of(now - 60 * 86400)
        _state["days"] = {d: v for d, v in _state["days"].items() if d >= cutoff}
        _save()


def spent_today(kind: str, now: float | None = None) -> int:
    k = (_state["days"].get(day_of(now or time.time())) or {}).get(kind) or {}
    return int(k.get("in", 0)) + int(k.get("out", 0))


def cost(provider: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = PRICE[provider]
    return (tokens_in * p_in + tokens_out * p_out) / 1e6


# ------------------------------------------------------------------ DeepSeek

async def ask_message(messages: list[dict], *, kind: str, max_tokens: int = 1200, tools: list[dict] | None = None,
                      http=None) -> dict:
    """One call, returning DeepSeek's whole message (content and tool_calls)."""
    body = {"model": settings.deepseek_model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.4}
    if tools:
        body["tools"] = tools
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"}
    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    if http is None:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(url, json=body, headers=headers)
    else:
        r = await http.post(url, json=body, headers=headers)
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage") or {}
    record(kind, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    return ((data.get("choices") or [{}])[0].get("message") or {})


async def ask(messages: list[dict], *, kind: str, max_tokens: int = 1200, http=None, json_mode: bool = False) -> str:
    """One DeepSeek chat call, counted in the ledger under `kind`. Keep the
    system message identical between calls: DeepSeek caches a repeated
    prefix and bills it at a tenth."""
    body = {"model": settings.deepseek_model, "messages": messages, "max_tokens": max_tokens,
            "temperature": 0 if json_mode else 0.4}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"}
    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    if http is None:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(url, json=body, headers=headers)
    else:
        r = await http.post(url, json=body, headers=headers)
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage") or {}
    record(kind, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    return (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()


CHAT_SYSTEM = (
    "Sei l'assistente di Liquidity Engine (liquidityengine.app), un sito che segnala meme coin e gemme "
    "on-chain (Solana, Robinhood Chain, BSC, Base, Ethereum) e le segue con un sistema trend-following "
    "(ingresso e uscita automatici, finestra 48h). Rispondi in italiano, breve e concreto, come in chat. "
    "Usa i dati del sito qui sotto quando servono e non inventare numeri che non ci sono: se un dato manca, "
    "dillo. Non promettere guadagni: sono mercati molto rischiosi. Non chiedere mai chiavi private o seed.")


def wants_answer(message: dict, bot_username: str) -> str | None:
    """The text to answer, or None. Private chat: every text. Group: only
    /ask, a mention of the bot, or a reply to it."""
    text = (message.get("text") or "").strip()
    if not text:
        return None
    chat = message.get("chat") or {}
    if chat.get("type") == "private":
        return re.sub(r"^/ask(@\w+)?\s*", "", text) or None
    mention = f"@{bot_username}".lower() if bot_username else None
    reply_to_bot = ((message.get("reply_to_message") or {}).get("from") or {}).get("username", "").lower() == (bot_username or "").lower()
    if re.match(r"^/ask(@\w+)?\b", text):
        return re.sub(r"^/ask(@\w+)?\s*", "", text) or None
    if mention and mention in text.lower():
        return re.sub(re.escape(f"@{bot_username}"), "", text, flags=re.I).strip() or None
    if reply_to_bot and bot_username:
        return text
    return None


TOOL_ROUNDS = 3


async def answer(chat_id: str, text: str, context: str, tools: dict | None = None) -> str:
    """tools: {name: (openai-style function schema, callable(**args) -> json-able)}.
    DeepSeek may call them (up to TOOL_ROUNDS rounds) to read the database."""
    if text.strip().lower() in ("/reset", "reset"):
        _memory.pop(chat_id, None)
        return "Fatto: ho dimenticato la conversazione."
    if spent_today("chat") >= CHAT_DAILY_TOKENS:
        return "Per oggi ho finito il budget di token della chat. Riprova domani."
    history = _memory.setdefault(chat_id, [])
    messages = [{"role": "system", "content": f"{CHAT_SYSTEM}\n\n<dati_del_sito>\n{context}\n</dati_del_sito>"},
                *history, {"role": "user", "content": text}]
    specs = [{"type": "function", "function": spec} for spec, _fn in (tools or {}).values()]
    reply = ""
    for _round in range(TOOL_ROUNDS + 1):
        msg = await ask_message(messages, kind="chat", tools=specs if specs and _round < TOOL_ROUNDS else None)
        calls = msg.get("tool_calls") or []
        if not calls:
            reply = (msg.get("content") or "").strip()
            break
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            name = (call.get("function") or {}).get("name")
            try:
                args = json.loads((call.get("function") or {}).get("arguments") or "{}")
                result = tools[name][1](**args)
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"[:200]}
            messages.append({"role": "tool", "tool_call_id": call.get("id"),
                             "content": json.dumps(result, default=str)[:6000]})
    reply = reply or "Non ho una risposta."
    history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    del history[:-MEMORY]
    return reply


# ------------------------------------------------------------------ recap

MARK_RE = re.compile(r"<!-- deepseek-usage (\{.*?\}) -->")


async def pr_review_usage(since: float, until: float, http=None) -> dict:
    """The PR reviews' usage, from the markers in their GitHub comments."""
    repo = "lorenzocorazzi-wq/liquidity-analysis-engine"
    out = {"calls": 0, "in": 0, "out": 0}
    if not settings.github_api_token:
        return out
    iso = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"Authorization": f"Bearer {settings.github_api_token}", "Accept": "application/vnd.github+json"}
    own = http is None
    http = http or httpx.AsyncClient(timeout=20.0)
    try:
        r = await http.get(f"https://api.github.com/repos/{repo}/issues/comments",
                           params={"since": iso, "per_page": 100}, headers=headers)
        rows = r.json() if r.status_code == 200 else []
    except httpx.HTTPError:
        rows = []
    finally:
        if own:
            await http.aclose()
    for c in rows if isinstance(rows, list) else []:
        for m in MARK_RE.finditer(c.get("body") or ""):
            try:
                u = json.loads(m[1])
                at = float(u.get("at") or 0)
            except (ValueError, TypeError):
                continue
            if since <= at < until:
                out["calls"] += 1
                out["in"] += int(u.get("in", 0))
                out["out"] += int(u.get("out", 0))
    return out


def _n(v: int) -> str:
    return f"{v:,}".replace(",", ".")


def recap_text(day: str, rows: dict) -> str:
    """rows: {kind: {calls, in, out}}. Italian, for Lorenzo."""
    lines = [f"🤖 <b>DeepSeek — {datetime.strptime(day, '%Y-%m-%d').strftime('%d/%m')}</b>"]
    tot_in = tot_out = calls = 0
    for kind, label in KINDS.items():
        k = rows.get(kind) or {}
        if not k.get("calls"):
            continue
        calls += k["calls"]
        tot_in += k["in"]
        tot_out += k["out"]
        lines.append(f"• {label}: {k['calls']} richieste, {_n(k['in'] + k['out'])} token")
    if not calls:
        return "\n".join(lines + ["Oggi nessun lavoro per DeepSeek."])
    ds, cl = cost("deepseek", tot_in, tot_out), cost("claude", tot_in, tot_out)
    lines += ["",
              f"Token lavorati da DeepSeek: <b>{_n(tot_in + tot_out)}</b> ({_n(tot_in)} letti, {_n(tot_out)} scritti)",
              f"Costo DeepSeek: <b>${ds:.3f}</b> · con Claude sarebbero stati ~${cl:.2f}",
              f"Risparmio stimato: <b>${cl - ds:.2f}</b> (prezzi di listino)"]
    return "\n".join(lines)


def recap_due(now: float) -> str | None:
    """The day to recap (yesterday or today at RECAP_HOUR), if not sent yet."""
    local = datetime.fromtimestamp(now, ROME)
    if local.hour < RECAP_HOUR:
        return None
    day = local.strftime("%Y-%m-%d")
    return None if _state["recap_sent"] == day else day


def mark_sent(day: str) -> None:
    _state["recap_sent"] = day
    _save()


def day_bounds(day: str) -> tuple[float, float]:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=ROME)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


_load()
