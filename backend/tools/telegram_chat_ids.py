"""
Elenca le chat che il bot Telegram riesce a vedere, con il loro id.

Serve a una cosa sola: separare i messaggi di sistema (deploy, errori) dagli
alert di trading, che e' una riga in `.env` — ma richiede l'id della chat
nuova, e trovarlo voleva dire aprire a mano
`https://api.telegram.org/bot<TOKEN>/getUpdates` e leggere il JSON grezzo,
col token in chiaro nella barra degli indirizzi.

Uso, sul server (dove il token e' gia' in ambiente):

    cd /opt/liquidity/backend && .venv/bin/python -m tools.telegram_chat_ids

Se una chat non compare: Telegram la mostra solo dopo che qualcuno ci ha
scritto qualcosa DOPO aver aggiunto il bot, e tiene gli aggiornamenti ~24 ore.
Manda un messaggio qualsiasi nel gruppo e rilancia.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from app.config import settings

_KIND = {
    "private": "chat privata",
    "group": "gruppo",
    "supergroup": "gruppo",
    "channel": "canale",
}


async def main() -> int:
    token = settings.telegram_bot_token
    if not token:
        print("TELEGRAM_BOT_TOKEN non configurato: niente da chiedere a Telegram.")
        return 1

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"https://api.telegram.org/bot{token}/getUpdates")
    if resp.status_code >= 400:
        # Il token non si stampa mai, nemmeno in un errore.
        print(f"Telegram ha risposto {resp.status_code}. Token non valido o revocato?")
        return 1

    updates = resp.json().get("result", [])
    if not updates:
        print("Nessun aggiornamento recente.\n"
              "Telegram mostra una chat solo dopo che ci e' stato scritto qualcosa,\n"
              "e tiene gli aggiornamenti circa 24 ore: manda un messaggio nella chat\n"
              "che ti interessa (nel gruppo, dopo averci aggiunto il bot) e rilancia.")
        return 0

    seen: dict[str, dict] = {}
    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        name = chat.get("title") or " ".join(
            filter(None, [chat.get("first_name"), chat.get("last_name")])
        ) or chat.get("username") or "(senza nome)"
        seen[str(chat_id)] = {"name": name, "kind": _KIND.get(chat.get("type"), chat.get("type"))}

    print(f"Chat visibili al bot: {len(seen)}\n")
    for chat_id, info in seen.items():
        print(f"  {chat_id:<16} {info['kind']:<14} {info['name']}")

    print("\nPer mandare deploy ed errori in una chat separata dagli alert,\n"
          "metti l'id del GRUPPO in deploy/.env:\n\n"
          "    TELEGRAM_DEV_CHAT_IDS=<id del gruppo>\n\n"
          "Gli id dei gruppi sono negativi (es. -1001234567890): non e' un errore.\n"
          "Gli alert di trading continuano ad andare alla chat personale di ogni\n"
          "utente, quella impostata dall'app — questa riga non li tocca.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
