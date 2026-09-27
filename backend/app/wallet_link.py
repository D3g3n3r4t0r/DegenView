"""Link anyone's own wallet to their account, without ever holding its keys.

Lorenzo: "dobbiamo dare la possibilita' di far collegare il wallet a
qualsiasi persona al nostro sito per usufruire dei nostri servizi".
First step of the plan agreed with him (connect and read; automatic trading
on a connected wallet comes later, through a contract the user signs):

- the site asks the wallet to sign a plain message (free, no transaction,
  cannot move funds): a one-off nonce, the address, the chain;
- the server checks the signature: EIP-191 personal_sign for EVM wallets
  (MetaMask, Rabby: Robinhood Chain), ed25519 for Solana (Phantom);
- a verified address is stored with the profile (profiles.py) and its
  holdings show up in the profile, read-only.
"""
from __future__ import annotations

import base64
import re
import secrets
import time

import base58

from app import profiles

KINDS = ("evm", "solana")
NONCE_TTL_S = 600
MAX_WALLETS = 6
_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

_pending: dict[str, dict] = {}     # uid -> {kind, address, message, at}


def valid_address(kind: str, address: str) -> bool:
    return bool((_EVM_RE if kind == "evm" else _SOL_RE).match(address or "")) if kind in KINDS else False


def challenge(uid: str, kind: str, address: str, host: str = "liquidityengine.app", now: float | None = None) -> str:
    if not valid_address(kind, address):
        raise ValueError("That is not a wallet address.")
    now = now or time.time()
    nonce = secrets.token_hex(12)
    message = (f"{host} wants you to link this wallet to your Liquidity Engine account.\n\n"
               f"Address: {address}\nChain: {'EVM (Robinhood Chain)' if kind == 'evm' else 'Solana'}\n"
               f"Nonce: {nonce}\nIssued: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}\n\n"
               "Signing is free: it is not a transaction and cannot move funds.")
    _pending[uid] = {"kind": kind, "address": address, "message": message, "at": now}
    return message


def _verify_evm(address: str, message: str, signature: str) -> bool:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    try:
        signer = Account.recover_message(encode_defunct(text=message), signature=signature)
    except Exception:
        return False
    return signer.lower() == address.lower()


def _decode_sig(signature: str) -> bytes:
    s = signature.strip()
    if re.fullmatch(r"[0-9a-fA-F]{128}", s):
        return bytes.fromhex(s)
    try:
        raw = base58.b58decode(s)
        if len(raw) == 64:
            return raw
    except ValueError:
        pass
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _verify_solana(address: str, message: str, signature: str) -> bool:
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    try:
        return Signature.from_bytes(_decode_sig(signature)).verify(Pubkey.from_string(address), message.encode())
    except Exception:
        return False


def confirm(uid: str, signature: str, now: float | None = None) -> dict:
    """Check the signature on the pending message; store the wallet."""
    now = now or time.time()
    p = _pending.pop(uid, None)
    if p is None or now - p["at"] > NONCE_TTL_S:
        raise ValueError("The request expired: connect again.")
    ok = _verify_evm(p["address"], p["message"], signature) if p["kind"] == "evm" \
        else _verify_solana(p["address"], p["message"], signature)
    if not ok:
        raise ValueError("The signature doesn't match this wallet.")
    return profiles.add_wallet(uid, p["kind"], p["address"], now)


def reset_for_tests() -> None:
    _pending.clear()
