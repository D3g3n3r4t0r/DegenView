"""
Notifiche push via Telegram Bot API — https://core.telegram.org/bots/api.
Bot personale creato via @BotFather, nessun servizio terzo, gratuito.

Setup (una tantum, fuori da questo codice):
  1. Su Telegram: cerca @BotFather -> /newbot -> segui i passaggi, copia il token.
  2. Manda un messaggio qualsiasi al bot appena creato (serve per trovare il chat_id).
  3. Metti TELEGRAM_BOT_TOKEN in backend/.env; per il chat_id apri nel browser
     https://api.telegram.org/bot<TOKEN>/getUpdates dopo il passo 2 e leggi "chat":{"id": ...}.
  4. Metti quell'id in TELEGRAM_CHAT_IDS in backend/.env (più id separati da virgola
     se vuoi notificare più persone/chat).

Due canali distinti, non uno
----------------------------
Le notifiche di questo progetto sono di due tipi, e non si leggono allo stesso
modo: un segnale operativo si guarda subito, un "nuovo deploy completato" no.

  * **Alert di trading** (ingressi, uscite, alert di prezzo) -> `send_to()`,
    alla chat PERSONALE di ciascun utente (`User.telegram_chat_id`, che ognuno
    imposta dall'app). Sono per chi opera.
  * **Messaggi di sistema** (deploy, errori 500) -> `send_message()`, alle chat
    in `TELEGRAM_DEV_CHAT_IDS` — o, se non impostata, a `TELEGRAM_CHAT_IDS`
    come è sempre stato. Sono per chi sviluppa.

Se le due finiscono nella stessa conversazione è solo perché puntano allo
stesso chat_id: basta un gruppo Telegram nuovo (stesso bot, nessun bot da
ricreare) il cui id va in `TELEGRAM_DEV_CHAT_IDS`. Per trovarlo:
`.venv/bin/python -m tools.telegram_chat_ids`.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger("telegram_notify")

API_BASE = "https://api.telegram.org"


def _split(raw: str) -> list[str]:
    return [c.strip() for c in raw.split(",") if c.strip()]


def _chat_ids() -> list[str]:
    """Le chat dei messaggi di sistema (deploy, errori 500).

    `TELEGRAM_DEV_CHAT_IDS` vince quando c'e'; altrimenti si ricade su
    `TELEGRAM_CHAT_IDS`, che e' dove finivano prima — cosi' separare i due
    canali e' una riga in `.env`, non una migrazione.
    """
    return _split(settings.telegram_dev_chat_ids) or _split(settings.telegram_chat_ids)


def is_configured() -> bool:
    return bool(settings.telegram_bot_token) and bool(_chat_ids())


async def send_to(chat_id: str, text: str) -> bool:
    """Send to one specific chat — used for per-user watchlist alerts now
    that each user has their own chat_id, instead of broadcasting to every
    configured recipient."""
    if not settings.telegram_bot_token or not chat_id:
        return False
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                f"{API_BASE}/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.warning("Invio Telegram fallito per chat_id=%s", chat_id, exc_info=True)
            return False


async def send_message(text: str) -> bool:
    """Manda a tutti i destinatari configurati. Non solleva mai — un errore qui non
    deve mai far fallire l'analisi in corso. Un destinatario che fallisce (es. ha
    bloccato il bot) non impedisce l'invio agli altri."""
    if not is_configured():
        return False

    sent_any = False
    async with httpx.AsyncClient(timeout=15.0) as client:
        for chat_id in _chat_ids():
            try:
                resp = await client.post(
                    f"{API_BASE}/bot{settings.telegram_bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                resp.raise_for_status()
                sent_any = True
            except httpx.HTTPError:
                logger.warning("Invio Telegram fallito per chat_id=%s", chat_id, exc_info=True)
                continue
    return sent_any
