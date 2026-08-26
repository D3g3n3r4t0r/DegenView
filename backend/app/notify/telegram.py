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
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger("telegram_notify")

API_BASE = "https://api.telegram.org"


def _chat_ids() -> list[str]:
    return [c.strip() for c in settings.telegram_chat_ids.split(",") if c.strip()]


def is_configured() -> bool:
    return bool(settings.telegram_bot_token) and bool(_chat_ids())


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
