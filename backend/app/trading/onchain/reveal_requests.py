"""Approvazione da un secondo dispositivo per rivelare una chiave privata
on-chain — un QR sul browser, la passphrase (email+password dell'account)
inserita sul telefono. Il trading resta automatico e non passa mai di qui:
questo token approva SOLO la lettura della chiave, mai un'operazione.

In memoria, non su disco: un riavvio del server invalida ogni richiesta
pendente, ed e' quello che si vuole — un token da rivelare non deve
sopravvivere piu' di qualche minuto in nessun caso.
"""
import secrets
import time
from dataclasses import dataclass, field

from app.models import OnchainChain

_TTL_SECONDS = 120


@dataclass
class _RevealRequest:
    user_id: str
    chain: OnchainChain
    created_at: float = field(default_factory=time.time)
    approved_at: float | None = None


_requests: dict[str, _RevealRequest] = {}


def _purge_expired() -> None:
    now = time.time()
    expired = [t for t, r in _requests.items() if now - r.created_at > _TTL_SECONDS]
    for t in expired:
        del _requests[t]


def create(user_id: str, chain: OnchainChain) -> str:
    _purge_expired()
    token = secrets.token_urlsafe(24)
    _requests[token] = _RevealRequest(user_id=user_id, chain=chain)
    return token


def status(token: str, user_id: str) -> str:
    """'pending' | 'approved' | 'expired' — mai un dettaglio su un token che
    non appartiene a chi chiede, solo 'expired' come per uno scaduto vero:
    non deve trapelare se un token esiste ma e' di un altro utente."""
    _purge_expired()
    req = _requests.get(token)
    if req is None or req.user_id != user_id:
        return "expired"
    return "approved" if req.approved_at else "pending"


def approve(token: str, user_id: str) -> bool:
    """Chiamata dalla pagina sul telefono, DOPO che la password e' gia'
    stata verificata (auth.verify_login) — questo modulo non tocca mai le
    credenziali, solo lo stato del token."""
    _purge_expired()
    req = _requests.get(token)
    if req is None or req.user_id != user_id:
        return False
    req.approved_at = time.time()
    return True


def consume(token: str, user_id: str, chain: OnchainChain) -> bool:
    """Usa il token una sola volta: approvato, non scaduto, stessa chain
    per cui e' stato creato. Rimosso solo quando l'uso riesce — il browser
    puo' chiamare questo endpoint in polling PRIMA che il telefono approvi
    (e' proprio come funziona il flusso), e un tentativo prematuro non deve
    bruciare il token per quello vero che arriva un secondo dopo."""
    _purge_expired()
    req = _requests.get(token)
    ok = bool(req and req.user_id == user_id and req.chain == chain and req.approved_at)
    if ok:
        del _requests[token]
    return ok
