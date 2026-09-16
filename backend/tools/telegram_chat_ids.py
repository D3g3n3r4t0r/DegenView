"""
Elenca le chat che il bot Telegram riesce a vedere, con il loro id.

Serve a una cosa sola: separare i messaggi di sistema (deploy, errori) dagli
alert di trading, che e' una riga in `.env` — ma richiede l'id della chat
nuova, e trovarlo voleva dire aprire a mano
`https://api.telegram.org/bot<TOKEN>/getUpdates` e leggere il JSON grezzo,
col token in chiaro nella barra degli indirizzi.

Uso, sul server (dove il token e' gia' in ambiente):

    cd /opt/liquidity/backend && .venv/bin/python -m tools.telegram_chat_ids

Con `--apply` scrive da se' `TELEGRAM_DEV_CHAT_IDS` nel file .env, invece di
lasciare il copia-incolla a mano:

    .venv/bin/python -m tools.telegram_chat_ids --apply

Scrive solo se il bot vede UN solo gruppo: con piu' gruppi non prova a
indovinare quale sia quello giusto, li elenca e si ferma.

Se una chat non compare: Telegram la mostra solo dopo che qualcuno ci ha
scritto qualcosa DOPO aver aggiunto il bot, e tiene gli aggiornamenti ~24 ore.
Manda un messaggio qualsiasi nel gruppo e rilancia.
"""

from __future__ import annotations

import argparse
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
_GROUPISH = {"group", "supergroup", "channel"}
_KEY = "TELEGRAM_DEV_CHAT_IDS"
_DEFAULT_ENV = Path("/opt/liquidity/deploy/.env")


def _write_dev_chat(env_path: Path, chat_id: str) -> str:
    """Scrive (o aggiorna) una sola chiave nel .env, lasciando il resto intatto.

    Il file contiene ogni segreto del sistema: si riscrive riga per riga
    cambiando solo la propria, mai rigenerandolo — e non se ne stampa nulla,
    nemmeno per conferma.
    """
    if not env_path.exists():
        raise FileNotFoundError(env_path)
    lines = env_path.read_text(encoding="utf-8").splitlines()
    line = f"{_KEY}={chat_id}"
    for i, existing in enumerate(lines):
        if existing.strip().startswith(f"{_KEY}="):
            if existing.strip() == line:
                return "era gia' impostato su questo gruppo"
            lines[i] = line
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return "aggiornato"
    lines.append(line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "aggiunto"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help=f"scrive {_KEY} nel .env quando il bot vede un solo gruppo")
    ap.add_argument("--env-file", default=str(_DEFAULT_ENV))
    args = ap.parse_args()

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
        seen[str(chat_id)] = {
            "name": name,
            "type": chat.get("type"),
            "kind": _KIND.get(chat.get("type"), chat.get("type")),
        }

    print(f"Chat visibili al bot: {len(seen)}\n")
    for chat_id, info in seen.items():
        print(f"  {chat_id:<16} {info['kind']:<14} {info['name']}")

    groups = {cid: info for cid, info in seen.items() if info["type"] in _GROUPISH}

    if not args.apply:
        print("\nPer mandare deploy ed errori in una chat separata dagli alert,\n"
              "metti l'id del GRUPPO in deploy/.env:\n\n"
              f"    {_KEY}=<id del gruppo>\n\n"
              "Gli id dei gruppi sono negativi (es. -1001234567890): non e' un errore.\n"
              "Oppure rilancia con --apply e lo scrive da se'.\n"
              "Gli alert di trading continuano ad andare alla chat personale di ogni\n"
              "utente, quella impostata dall'app — questa riga non li tocca.")
        return 0

    if not groups:
        print("\nNessun gruppo fra le chat visibili: niente da scrivere.\n"
              "Aggiungi il bot al gruppo, scrivici un messaggio e rilancia.")
        return 1
    if len(groups) > 1:
        # Scegliere al posto suo vorrebbe dire mandare i messaggi di sistema in
        # un gruppo a caso fra questi.
        print(f"\n{len(groups)} gruppi visibili: non indovino quale sia quello giusto.\n"
              f"Scegli l'id qui sopra e mettilo a mano in {_KEY}.")
        return 1

    chat_id, info = next(iter(groups.items()))
    env_path = Path(args.env_file)
    try:
        outcome = _write_dev_chat(env_path, chat_id)
    except FileNotFoundError:
        print(f"\n{env_path} non esiste: passa il percorso giusto con --env-file.")
        return 1
    except OSError as exc:
        print(f"\nNon sono riuscito a scrivere {env_path}: {exc}")
        return 1

    print(f"\n{_KEY} {outcome}: \"{info['name']}\" ({chat_id}), in {env_path}")
    print("Serve un riavvio perche' abbia effetto:\n"
          "    cd /opt/liquidity/deploy && docker compose up -d\n"
          "Da li' deploy ed errori vanno SOLO in quel gruppo; gli alert di trading\n"
          "restano nella chat personale di ciascun utente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
