"""The account's public face: name, handle, bio, picture.

Lorenzo, with a screenshot of a trading app's profile: "uno deve vedere cosa
detiene, l'andamento del wallet nel tempo con un grafico, e ovviamente
l'account con cui uno si e' loggato deve rimanere tutto nel database, uno
deve poter scegliere anche l'immagine profilo".

Kept beside the users file, not inside User: the login record stays what it
is, and this can grow without touching it. The picture is re-encoded here
(square, 256 px, WebP) whatever was uploaded, so what is served is always a
small, plain image, never the original file.
"""
from __future__ import annotations

import base64
import io
import json
import re
import threading
import time

from app.trading.onchain.storage import data_file
from app.atomic_write import write_text_atomic

_STORE_FILE = data_file("profiles.json")
_AVATARS = data_file("avatars")
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
AVATAR_PX = 256
HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
NAME_MAX = 40
BIO_MAX = 160
HIDDEN_MAX = 1000
_HIDDEN_KEY = re.compile(r"^[a-z]{2,12}:[A-Za-z0-9]{8,64}$")

_lock = threading.Lock()
_profiles: dict[str, dict] = {}


def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        _profiles.update({k: v for k, v in raw.items() if isinstance(v, dict)})


def _save() -> None:
    try:
        write_text_atomic(_STORE_FILE, json.dumps(_profiles, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def reset_for_tests() -> None:
    _profiles.clear()


def get(uid: str, email: str = "", joined_hint: float | None = None) -> dict:
    """The profile, created on first sight with defaults from the email."""
    with _lock:
        p = _profiles.get(uid)
        if p is None:
            local = (email.split("@")[0] if email else "trader")
            base = re.sub(r"[^A-Za-z0-9_]", "", local)[:16] or "trader"
            handle = base if len(base) >= 3 else f"{base}_{uid[:4]}"
            taken = {x.get("handle", "").lower() for x in _profiles.values()}
            n = 2
            while handle.lower() in taken:
                handle = f"{base[:14]}{n}"
                n += 1
            p = {"display_name": local[:NAME_MAX] or "Trader", "handle": handle, "bio": "", "avatar_rev": 0,
                 "created_at": min(t for t in (joined_hint, time.time()) if t)}
            _profiles[uid] = p
            _save()
        return dict(p)


def update(uid: str, *, display_name: str | None = None, handle: str | None = None, bio: str | None = None) -> dict:
    with _lock:
        p = _profiles.setdefault(uid, {"display_name": "Trader", "handle": f"trader_{uid[:4]}", "bio": "",
                                       "avatar_rev": 0, "created_at": time.time()})
        if display_name is not None:
            name = " ".join(display_name.split())[:NAME_MAX]
            if not name:
                raise ValueError("The name can't be empty.")
            p["display_name"] = name
        if handle is not None:
            h = handle.strip().lstrip("@")
            if not HANDLE_RE.match(h):
                raise ValueError("Handle: 3 to 20 letters, digits or _.")
            if any(k != uid and v.get("handle", "").lower() == h.lower() for k, v in _profiles.items()):
                raise ValueError("That handle is taken.")
            p["handle"] = h
        if bio is not None:
            p["bio"] = " ".join(bio.split())[:BIO_MAX]
        _save()
        return dict(p)


def add_wallet(uid: str, kind: str, address: str, now: float | None = None) -> dict:
    """A wallet the user proved is theirs (wallet_link.py). One account per
    address: a wallet linked elsewhere must be unlinked there first."""
    key = address.lower() if kind == "evm" else address
    with _lock:
        for other, q in _profiles.items():
            if other != uid and any((w["address"].lower() if w["kind"] == "evm" else w["address"]) == key
                                    for w in q.get("wallets") or []):
                raise ValueError("This wallet is linked to another account.")
        p = _profiles.setdefault(uid, {"display_name": "Trader", "handle": f"trader_{uid[:4]}", "bio": "",
                                       "avatar_rev": 0, "created_at": time.time()})
        wallets = [w for w in p.get("wallets") or [] if not (w["kind"] == kind and
                   (w["address"].lower() if kind == "evm" else w["address"]) == key)]
        if len(wallets) >= 6:
            raise ValueError("Six wallets at most.")
        wallets.append({"kind": kind, "address": address, "linked_at": now or time.time()})
        p["wallets"] = wallets
        _save()
        return dict(p)


def remove_wallet(uid: str, kind: str, address: str) -> dict:
    with _lock:
        p = _profiles.get(uid) or {}
        p["wallets"] = [w for w in p.get("wallets") or []
                        if not (w["kind"] == kind and w["address"].lower() == address.lower())]
        _save()
        return dict(p)


def wallets(uid: str) -> list[dict]:
    return list((_profiles.get(uid) or {}).get("wallets") or [])


def hidden(uid: str) -> list[str]:
    """The tokens this account asked not to see in its lists."""
    with _lock:
        return list((_profiles.get(uid) or {}).get("hidden") or [])


NARRATIVES_MAX = 40


def narratives(uid: str) -> list[str]:
    """The narratives this account asked the Gem Finder to hunt first."""
    with _lock:
        return list((_profiles.get(uid) or {}).get("narratives") or [])


def set_narratives(uid: str, keys: list[str]) -> list[str]:
    from app.trading.onchain import narratives as _narr
    known = {n["key"] for n in _narr.catalog()}
    seen, out = set(), []
    for k in keys or []:
        if k in known and k not in seen:
            seen.add(k)
            out.append(k)
    out = out[:NARRATIVES_MAX]
    get(uid)  # creates the profile if needed — get() takes _lock itself
    with _lock:
        p = _profiles[uid]
        p["narratives"] = out
        _save()
        return list(out)


def wanted_narratives() -> list[str]:
    """Union over all accounts, most-chosen first."""
    counts: dict[str, int] = {}
    with _lock:
        for p in _profiles.values():
            for k in p.get("narratives") or []:
                counts[k] = counts.get(k, 0) + 1
    return sorted(counts, key=lambda k: (-counts[k], k))


def set_hidden(uid: str, chain: str, token: str, hide: bool = True) -> list[str]:
    key = f"{chain}:{token}"
    if not _HIDDEN_KEY.match(key):
        raise ValueError("bad token")
    get(uid)  # creates the profile if needed — get() takes _lock itself
    with _lock:
        p = _profiles[uid]
        lst = [k for k in (p.get("hidden") or []) if k != key]
        if hide:
            lst.append(key)
        p["hidden"] = lst[-HIDDEN_MAX:]
        _save()
        return list(p["hidden"])


def avatar_path(uid: str):
    return _AVATARS / f"{re.sub(r'[^A-Za-z0-9_-]', '', uid)}.webp"


def set_avatar(uid: str, data_url: str) -> dict:
    """A data: URL (what a file input gives the browser) -> 256 px WebP."""
    from PIL import Image, ImageOps

    m = re.match(r"^data:image/(png|jpe?g|webp|gif|heic|heif);base64,(.+)$", data_url or "", re.S)
    if not m:
        raise ValueError("Pick a PNG, JPEG or WebP image.")
    raw = base64.b64decode(m.group(2), validate=False)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("The picture is over 4 MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:
        raise ValueError("That file is not an image we can read.") from exc
    img = ImageOps.fit(img, (AVATAR_PX, AVATAR_PX), method=Image.Resampling.LANCZOS)
    _AVATARS.mkdir(parents=True, exist_ok=True)
    img.save(avatar_path(uid), "WEBP", quality=86)
    with _lock:
        p = _profiles.setdefault(uid, {"display_name": "Trader", "handle": f"trader_{uid[:4]}", "bio": "",
                                       "created_at": time.time()})
        p["avatar_rev"] = int(p.get("avatar_rev") or 0) + 1
        _save()
        return dict(p)


def public(uid: str, p: dict) -> dict:
    rev = p.get("avatar_rev") or 0
    return {"display_name": p["display_name"], "handle": p["handle"], "bio": p.get("bio") or "",
            "avatar_url": f"/api/profile/avatar/{uid}?v={rev}" if rev else None, "joined": p.get("created_at"),
            "wallets": p.get("wallets") or []}


_load()
