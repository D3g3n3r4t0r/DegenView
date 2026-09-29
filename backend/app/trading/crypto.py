import base64
import hashlib
import hmac
import os


def encrypt(plaintext: str, secret: bytes) -> str:
    """Encrypt a string with secret, returns base64-encoded ciphertext (16-byte nonce + ciphertext)."""
    data = plaintext.encode()
    nonce = os.urandom(16)
    stream = _keystream(secret, nonce, len(data))
    return base64.b64encode(nonce + bytes(a ^ b for a, b in zip(data, stream))).decode()


def decrypt(ciphertext_b64: str, secret: bytes) -> str:
    """Decrypt. Returns empty string if ciphertext is empty or malformed."""
    if not ciphertext_b64:
        return ""
    try:
        raw = base64.b64decode(ciphertext_b64)
        nonce, data = raw[:16], raw[16:]
        stream = _keystream(secret, nonce, len(data))
        return bytes(a ^ b for a, b in zip(data, stream)).decode()
    except Exception:  # noqa: BLE001
        return ""


def _keystream(secret: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(secret, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


# --- v2: authenticated encryption (audit 29/09, S07) ------------------------
# The stream cipher above has no tag: a changed byte changes the plaintext
# without any error. v2 is AES-256-GCM with associated data (who and what the
# secret belongs to), so tampering, truncation, a wrong key or a ciphertext
# moved to another user fail loudly. Format: "v2:<key id>:<base64(nonce|ct)>".
# The key id says which key sealed it, so the key can change later without
# making older records unreadable. decrypt() above stays for old records.

V2_PREFIX = "v2:"


class SealError(Exception):
    """A v2 ciphertext that does not open: tampered, wrong key or wrong owner."""


def seal(plaintext: str, key: bytes, key_id: str, aad: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), aad)
    return f"{V2_PREFIX}{key_id}:{base64.b64encode(nonce + ct).decode()}"


def is_sealed(token: str) -> bool:
    return bool(token) and token.startswith(V2_PREFIX)


def key_id_of(token: str) -> str | None:
    return token.split(":", 2)[1] if is_sealed(token) and token.count(":") >= 2 else None


def unseal(token: str, keys: dict[str, bytes], aad: bytes) -> str:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        _, key_id, body = token.split(":", 2)
        raw = base64.b64decode(body, validate=True)
    except ValueError as exc:
        raise SealError("malformed ciphertext") from exc
    key = keys.get(key_id)
    if key is None:
        raise SealError(f"no key '{key_id}' on this server")
    if len(raw) < 12 + 16:
        raise SealError("truncated ciphertext")
    try:
        return AESGCM(key).decrypt(raw[:12], raw[12:], aad).decode()
    except InvalidTag as exc:
        raise SealError("ciphertext does not authenticate") from exc


def derive_key(secret: bytes, label: bytes) -> bytes:
    """32 bytes for one purpose, HMAC-SHA256 as PRF (the HKDF-expand step)."""
    return hmac.new(secret, label, hashlib.sha256).digest()
