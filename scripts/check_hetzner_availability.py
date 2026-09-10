"""Avvisa su Telegram quando una macchina Cost-Optimized torna disponibile.

Perche' esiste: le CX/CAX di Hetzner costano un quarto delle CPX, ma
vanno esaurite di continuo. Con 50 euro di credito la differenza e' fra
due mesi e un anno di server — e l'unico modo di prenderle e' esserci nel
momento in cui si liberano. Questo controlla al posto nostro.

Gira su GitHub Actions ogni ora: nessun server da tenere acceso, nessuna
memoria sottratta a quello che manda gli avvisi di trading.

Serve un token Hetzner di **sola lettura**: puo' guardare la
disponibilita' e nient'altro — non puo' creare, spegnere o cancellare
niente.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

# I modelli che vogliamo davvero: due core e 4 GB, a un quarto del prezzo
# di una CPX. cax11 e' ARM, e va bene lo stesso — le librerie del progetto
# hanno tutte i pacchetti aarch64 (verificato).
WANTED = ("cx22", "cax11")

# Le location europee. Singapore e gli Stati Uniti sono fuori: la latenza
# verso gli exchange e verso di noi non avrebbe senso.
WANTED_LOCATIONS = ("fsn1", "nbg1", "hel1")

API = "https://api.hetzner.cloud/v1"


def api_get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{API}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def find_available(token: str) -> list[tuple[str, str]]:
    """Coppie (modello, datacenter) disponibili adesso."""
    types = api_get("/server_types?per_page=100", token)["server_types"]
    wanted_ids = {t["id"]: t["name"] for t in types if t["name"] in WANTED}
    if not wanted_ids:
        return []

    found: list[tuple[str, str]] = []
    for dc in api_get("/datacenters?per_page=100", token)["datacenters"]:
        location = (dc.get("location") or {}).get("name", "")
        if location not in WANTED_LOCATIONS:
            continue
        # "available" e' cio' che si puo' creare adesso. C'e' anche
        # "available_for_migration", che riguarda le macchine gia' esistenti
        # e qui non ci serve: noi dobbiamo crearne una nuova.
        for type_id in (dc.get("server_types") or {}).get("available", []):
            if type_id in wanted_ids:
                found.append((wanted_ids[type_id], dc["name"]))
    return sorted(set(found))


def telegram(token: str, chat_ids: str, text: str) -> None:
    for chat_id in [c.strip() for c in chat_ids.split(",") if c.strip()]:
        data = urllib.parse.urlencode({
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data
        )
        try:
            urllib.request.urlopen(req, timeout=20).read()
        except Exception as exc:   # un chat id sbagliato non deve fermare gli altri
            print(f"Telegram, chat {chat_id}: {exc}", file=sys.stderr)


def main() -> int:
    hetzner = os.environ.get("HETZNER_API_TOKEN", "").strip()
    if not hetzner:
        print("HETZNER_API_TOKEN mancante.", file=sys.stderr)
        return 1

    try:
        available = find_available(hetzner)
    except Exception as exc:
        # Un errore dell'API non deve far fallire il workflow ogni ora e
        # riempire la casella di notifiche di GitHub: si riprova dopo.
        print(f"Hetzner non risponde: {exc}", file=sys.stderr)
        return 0

    # Lo stato serve a non ripetere lo stesso avviso ventiquattro volte al
    # giorno: si avvisa quando qualcosa passa da non disponibile a
    # disponibile, non finche' resta disponibile.
    state_file = os.environ.get("STATE_FILE", "hetzner-state.json")
    try:
        with open(state_file, encoding="utf-8") as fh:
            already = set(tuple(x) for x in json.load(fh))
    except (OSError, ValueError):
        already = set()

    nuovi = [x for x in available if x not in already]

    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump([list(x) for x in available], fh)

    if not available:
        print("Nessuna Cost-Optimized disponibile.")
        return 0
    print("Disponibili:", ", ".join(f"{t}@{dc}" for t, dc in available))

    if not nuovi:
        print("Gia' segnalate: nessun avviso nuovo.")
        return 0

    righe = "\n".join(f"  • <b>{t}</b> a {dc}" for t, dc in nuovi)
    telegram(
        os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        os.environ.get("TELEGRAM_CHAT_IDS", ""),
        "🟢 <b>Hetzner: macchina economica disponibile</b>\n\n"
        f"{righe}\n\n"
        "Costa circa un quarto di una CPX22, e con i 50 € di credito dura "
        "quasi un anno invece di due mesi.\n\n"
        "Vanno via in fretta: se la vuoi, creala adesso su "
        "console.hetzner.cloud → Servers → Add Server.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
