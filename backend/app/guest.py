"""Link ospite: chi lo apre usa il sito in sola lettura, senza account.

Lorenzo voleva mandare il sito a un amico "che lo possa utilizzare senza
ovviamente poter modificare niente". La registrazione e' chiusa a due email
(settings.registration_allowed_emails) e deve restarlo: un account da' accesso
all'ottimizzatore e alla parte che conserva chiavi. Quindi non un account, ma
un link con un token, creato da un amministratore, con scadenza e revocabile.

Chi apre il link riceve un cookie `guest` firmato e diventa un utente
sintetico senza wallet, chiavi, watchlist ne' preferenze: vede grafici, analisi,
radar e scanner, non i dati di nessuno. Il blocco e' nel middleware di
main.py, lato server — nascondere i tasti non basterebbe:

- ogni metodo diverso da GET/HEAD/OPTIONS e' rifiutato (403), salvo le poche
  POST di solo calcolo in GUEST_WRITE_ALLOWED;
- alcune GET sono comunque chiuse (GUEST_BLOCKED_PREFIXES): pagine admin,
  traceback, e l'ottimizzatore che occupa un core per minuti.

Il cookie porta l'id del link, e ogni richiesta rilegge il link: revocarlo
chiude subito tutti i browser che l'hanno aperto, senza aspettare la scadenza.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from pydantic import BaseModel

from app import auth
from app.models import User
from app.atomic_write import write_text_atomic

GUEST_COOKIE = "guest"
DEFAULT_DAYS = 7
MAX_DAYS = 90

_LINKS_FILE: Path = auth._DATA_DIR / "guest_links.json"
# Derivato, come _ONCHAIN_SECRET: un cookie ospite non deve valere come
# cookie di sessione, anche se il formato fosse lo stesso.
_GUEST_SECRET = hmac.new(auth._SECRET, b"guest-link-v1", hashlib.sha256).digest()

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Scritture permesse all'ospite: entrare/uscire, e calcoli che non salvano nulla.
GUEST_WRITE_ALLOWED = frozenset({
    "/api/auth/login",
    "/api/auth/logout",
    "/api/indicators/compute",
})

GUEST_BLOCKED_PREFIXES = (
    "/admin",
    "/api/errors",       # traceback del server
    "/api/optimize",     # un core per minuti
    "/api/jobs",
    "/api/guest-links",
    "/api/onchain/wallets",
    "/api/export",
    "/api/agent/log",
    "/api/agent/calls",
    "/api/perf",
)


class GuestLink(BaseModel):
    id: str
    token: str
    label: str = ""
    created_by: str = ""
    created_at: int
    expires_at: int
    revoked: bool = False

    def active(self, now: float | None = None) -> bool:
        return not self.revoked and self.expires_at > (now or time.time())


_links: dict[str, GuestLink] = {}


def _load() -> None:
    _links.clear()
    if not _LINKS_FILE.exists():
        return
    try:
        raw = json.loads(_LINKS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for item in raw:
        try:
            link = GuestLink(**item)
        except (TypeError, ValueError):
            continue
        _links[link.id] = link


def _save() -> None:
    write_text_atomic(_LINKS_FILE, json.dumps([lk.model_dump() for lk in _links.values()]), encoding="utf-8")


_load()


def create_link(created_by: str, label: str = "", days: int = DEFAULT_DAYS) -> GuestLink:
    days = max(1, min(int(days), MAX_DAYS))
    now = int(time.time())
    link = GuestLink(
        id=secrets.token_hex(6),
        token=secrets.token_urlsafe(24),
        label=label.strip()[:60],
        created_by=created_by,
        created_at=now,
        expires_at=now + days * 86400,
    )
    _links[link.id] = link
    _save()
    return link


def list_links() -> list[GuestLink]:
    return sorted(_links.values(), key=lambda lk: lk.created_at, reverse=True)


def revoke_link(link_id: str) -> GuestLink | None:
    link = _links.get(link_id)
    if link is None:
        return None
    link = link.model_copy(update={"revoked": True})
    _links[link_id] = link
    _save()
    return link


def find_by_token(token: str) -> GuestLink | None:
    for link in _links.values():
        if hmac.compare_digest(link.token, token):
            return link if link.active() else None
    return None


def make_cookie(link: GuestLink) -> str:
    payload = f"{link.id}:{link.expires_at}"
    sig = hmac.new(_GUEST_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_cookie(cookie: str | None) -> GuestLink | None:
    if not cookie:
        return None
    try:
        link_id, expires_s, sig = cookie.split(":", 2)
    except ValueError:
        return None
    expected = hmac.new(_GUEST_SECRET, f"{link_id}:{expires_s}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    link = _links.get(link_id)
    return link if link is not None and link.active() else None


def guest_user(link: GuestLink) -> User:
    return User(id=f"guest-{link.id}", email="ospite", password_hash="")


def is_guest(user: User | None) -> bool:
    return user is not None and user.id.startswith("guest-") and user.password_hash == ""


def allows(method: str, path: str) -> bool:
    if path.startswith(GUEST_BLOCKED_PREFIXES):
        return False
    return method in SAFE_METHODS or path in GUEST_WRITE_ALLOWED
