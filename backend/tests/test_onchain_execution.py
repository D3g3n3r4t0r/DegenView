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


def test_build_swap_router02_calldata_matches_the_verified_selector():
    """04e45aaf e' keccak256("exactInputSingle((address,address,uint24,address,
    uint256,uint256,uint160))")[:4] — ricalcolato qui, non copiato a memoria.
    Il resto del test controlla solo che l'ABI encoding sia quello atteso
    per lo standard exactInputSingle di SwapRouter02: NON verifica una
    chiamata reale a un pool su Robinhood Chain, che questa sessione non ha."""
    from eth_utils import keccak

    selector = keccak(text="exactInputSingle((address,address,uint24,address,uint256,uint256,uint160))")[:4]
    assert selector == execution._SELECTOR_EXACT_INPUT_SINGLE

    token_in = "0x" + "11" * 20
    token_out = "0x" + "22" * 20
    recipient = "0x" + "33" * 20
    calldata = execution.build_swap_router02_calldata(
        token_in, token_out, fee=3000, recipient=recipient,
        amount_in=1_000_000, amount_out_minimum=990_000,
    )
    assert calldata[:4] == selector
    assert len(calldata) == 4 + 7 * 32  # 7 campi statici, nessuno dinamico
    # I due indirizzi e il recipient devono comparire, allineati a 32 byte,
    # esattamente come li ha passati la chiamata.
    body = calldata[4:]
    assert body[12:32].hex() == "11" * 20
    assert body[32 + 12:64].hex() == "22" * 20
    assert int.from_bytes(body[64:96], "big") == 3000
    assert body[96 + 12:128].hex() == "33" * 20
    assert int.from_bytes(body[128:160], "big") == 1_000_000
    assert int.from_bytes(body[160:192], "big") == 990_000


def test_robinhood_swap_router02_address_is_checksummed():
    from eth_utils import to_checksum_address

    assert execution.ROBINHOOD_SWAP_ROUTER02 == to_checksum_address(execution.ROBINHOOD_SWAP_ROUTER02)


ROBINHOOD_WETH = "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"
ROBINHOOD_USDG = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"


def test_build_signed_robinhood_swap_real_nonce_and_gas_price():
    """Genera un wallet usa-e-getta (0 ETH sopra, mai in grado di finire
    davvero in chain), legge nonce e gas price VERI da Robinhood Chain, e
    firma una vera exactInputSingle sul pool WETH/USDG. Nessun invio: come
    per Solana, questo test verifica la firma, mai il broadcast."""
    acct = Account.create()
    signed = _run(execution.build_signed_robinhood_swap(
        acct.key.hex(), ROBINHOOD_WETH, ROBINHOOD_USDG, 3000, 10**16, 1,
    ))
    assert isinstance(signed, bytes)
    assert len(signed) > 0
    recovered = Account.recover_transaction(signed)
    assert recovered.lower() == acct.address.lower()
