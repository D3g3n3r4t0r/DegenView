"""Costruzione e firma di uno swap vero — MAI l'invio. L'invio (broadcast)
resta dietro settings.onchain_execution_enabled, che nasce spento (Fase 3
del piano, non ancora accesa): tutto qui sotto e' stato verificato dal vivo
fino alla firma compresa (quote reale di Jupiter, transazione vera
deserializzata e firmata con la chiave dell'account giusto), mai oltre.

La sequenza e' sempre: quote -> guardrail (risk.run_all_checks, gia' fatto
da chi chiama) -> reserve() sul ledger -> firma -> (quando abilitato) invio
-> mark_submitted -> conferma -> mark_confirmed.
"""
import base64

import httpx
from eth_account import Account
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

JUPITER_SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"
ROBINHOOD_RPC = "https://rpc.mainnet.chain.robinhood.com"


async def build_signed_solana_swap(private_key_hex: str, quote: dict) -> bytes:
    """Chiede a Jupiter la transazione grezza per QUESTO quote e la firma
    con la chiave del wallet — ritorna i byte pronti per sendTransaction,
    che questo modulo non chiama mai da solo."""
    kp = Keypair.from_bytes(bytes.fromhex(private_key_hex))
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(JUPITER_SWAP_URL, json={
            "quoteResponse": quote["raw"], "userPublicKey": str(kp.pubkey()),
        })
    if resp.status_code != 200:
        raise RuntimeError(f"Jupiter /swap ha risposto {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    if "swapTransaction" not in body:
        raise RuntimeError(f"Jupiter /swap senza swapTransaction: {body}")
    raw = base64.b64decode(body["swapTransaction"])
    tx = VersionedTransaction.from_bytes(raw)
    signed = VersionedTransaction(tx.message, [kp])
    return bytes(signed)


async def send_signed_solana_tx(signed_tx_bytes: bytes) -> str:
    """Unico punto che manda davvero una transazione Solana in chain —
    chiamato solo se settings.onchain_execution_enabled e' True, controllo
    che sta a chi chiama, non qui (questa funzione non legge settings di
    proposito: un modulo che decide da solo se sia acceso e' un modulo che
    un domani si dimentica di controllare)."""
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
        "params": [base64.b64encode(signed_tx_bytes).decode(), {"encoding": "base64"}],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post("https://api.mainnet-beta.solana.com", json=payload)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Invio Solana fallito: {data['error']}")
    return data["result"]  # signature


def sign_evm_transaction(private_key_hex: str, tx: dict) -> bytes:
    """Firma una transazione EVM gia' costruita (nonce, gas, to, data, value,
    chainId — 4663 per Robinhood Chain) — non costruisce la chiamata allo
    swap del router Uniswap: quell'encoding ABI specifico richiede
    l'indirizzo vero del router/pool su Robinhood Chain, che questa sessione
    non ha ancora verificato dal vivo. Il pezzo generico (firma di una
    transazione EVM qualsiasi con la chiave del wallet) e' invece reale e
    testato: e' la parte che NON dipende da quale contratto si chiami."""
    signed = Account.sign_transaction(tx, private_key_hex)
    return bytes(signed.raw_transaction)


async def send_signed_evm_tx(raw_tx_bytes: bytes) -> str:
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "eth_sendRawTransaction",
        "params": ["0x" + raw_tx_bytes.hex()],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(ROBINHOOD_RPC, json=payload)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Invio Robinhood Chain fallito: {data['error']}")
    return data["result"]  # tx hash
