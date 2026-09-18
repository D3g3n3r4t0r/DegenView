"""Costruzione e firma di uno swap — verificato dal vivo fino alla firma
compresa (quote e transazione grezza vere da Jupiter), MAI l'invio: nessun
test qui chiama sendTransaction/eth_sendRawTransaction contro la rete vera."""

from __future__ import annotations

import asyncio

from eth_account import Account
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from app.trading.onchain import execution, quotes

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _run(coro):
    return asyncio.run(coro)


def test_build_signed_solana_swap_real_network_roundtrip():
    """Genera un wallet usa-e-getta (senza un centesimo sopra), chiede un
    quote vero, chiede la transazione vera a Jupiter per QUEL wallet, la
    firma con la stessa chiave — e verifica che il risultato sia una
    transazione Solana valida con una firma verificabile. Nessun invio."""
    key = Keypair()
    private_key_hex = bytes(key).hex()

    quote = _run(quotes.jupiter_quote(SOL_MINT, USDC_MINT, 10_000_000, slippage_bps=50))
    signed_bytes = _run(execution.build_signed_solana_swap(private_key_hex, quote))

    tx = VersionedTransaction.from_bytes(signed_bytes)
    assert len(tx.signatures) == 1
    # from_bytes non lancia se la firma e' malformata nella forma, ma il
    # vero controllo e' che verify_and_hash_message non rifiuti la firma
    # per quella chiave — se la chiave sbagliata avesse firmato, questo
    # solleverebbe.
    tx.verify_and_hash_message()


def test_sign_evm_transaction_produces_a_valid_signed_tx():
    acct = Account.create()
    tx = {
        "nonce": 0,
        "to": "0x000000000000000000000000000000000000dEaD",
        "value": 0,
        "gas": 21000,
        "gasPrice": 1_000_000_000,
        "chainId": 4663,  # Robinhood Chain
    }
    raw = execution.sign_evm_transaction(acct.key.hex(), tx)
    assert isinstance(raw, bytes)
    assert len(raw) > 0

    recovered = Account.recover_transaction(raw)
    assert recovered.lower() == acct.address.lower()
