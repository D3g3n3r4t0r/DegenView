"""Linking a user's own wallet by signature (wallet_link.py)."""
import base58
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from solders.keypair import Keypair

from app import profiles, wallet_link


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "_STORE_FILE", tmp_path / "p.json")
    profiles.reset_for_tests()
    wallet_link.reset_for_tests()
    yield


def test_evm_wallet_links_with_personal_sign():
    acct = Account.create()
    msg = wallet_link.challenge("u1", "evm", acct.address)
    sig = Account.sign_message(encode_defunct(text=msg), acct.key).signature.hex()
    p = wallet_link.confirm("u1", "0x" + sig if not sig.startswith("0x") else sig)
    assert p["wallets"][0]["address"] == acct.address
    # the same wallet cannot be linked to a second account
    msg = wallet_link.challenge("u2", "evm", acct.address)
    sig = Account.sign_message(encode_defunct(text=msg), acct.key).signature.hex()
    with pytest.raises(ValueError, match="another account"):
        wallet_link.confirm("u2", sig)


def test_wrong_signer_and_expiry_are_refused():
    acct, other = Account.create(), Account.create()
    msg = wallet_link.challenge("u1", "evm", acct.address)
    with pytest.raises(ValueError, match="doesn't match"):
        wallet_link.confirm("u1", Account.sign_message(encode_defunct(text=msg), other.key).signature.hex())
    wallet_link.challenge("u1", "evm", acct.address, now=1000.0)
    with pytest.raises(ValueError, match="expired"):
        wallet_link.confirm("u1", "00", now=1000.0 + wallet_link.NONCE_TTL_S + 1)
    with pytest.raises(ValueError):
        wallet_link.challenge("u1", "evm", "not-an-address")


def test_solana_wallet_links_with_ed25519():
    kp = Keypair()
    addr = str(kp.pubkey())
    msg = wallet_link.challenge("u1", "solana", addr)
    sig = kp.sign_message(msg.encode())
    p = wallet_link.confirm("u1", base58.b58encode(bytes(sig)).decode())
    assert p["wallets"][0] == {**p["wallets"][0], "kind": "solana", "address": addr}
    profiles.remove_wallet("u1", "solana", addr)
    assert profiles.wallets("u1") == []
