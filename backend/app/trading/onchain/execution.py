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
from eth_abi import encode as _abi_encode
from eth_account import Account
from eth_utils import to_checksum_address
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction, VersionedTransaction

JUPITER_SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"
ROBINHOOD_RPC = "https://rpc.mainnet.chain.robinhood.com"

# Verificato il 19/09/2026 su due fonti indipendenti e coerenti fra loro:
# developers.uniswap.org/docs/protocols/v3/deployments/v3-robinhood-chain-deployments
# (che riporta anche il Permit2 singleton universale 0x000000...78BA3, identico
# su ogni chain — un controllo di autenticita' in piu') e docs.robinhood.com/chain.
# SwapRouter02 (Uniswap v3), non v2: piu' semplice da incapsulare senza una
# libreria ABI completa, un solo metodo (exactInputSingle) da codificare.
ROBINHOOD_SWAP_ROUTER02 = to_checksum_address("0xcaf681a66d020601342297493863e78c959e5cb2")
# keccak256("exactInputSingle((address,address,uint24,address,uint256,uint256,uint160))")[:4]
# — calcolato con eth_utils.keccak in questa sessione, non a memoria.
_SELECTOR_EXACT_INPUT_SINGLE = bytes.fromhex("04e45aaf")


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


async def build_signed_solana_tip_tx(private_key_hex: str, tip_account: str, tip_lamports: int) -> bytes:
    """Costruisce e firma la SECONDA transazione di un bundle Jito: un
    trasferimento SOL nativo (System Program, nessun programma custom) dal
    wallet a uno degli 8 tip account ufficiali (vedi jito.py). Serve un
    blockhash recente vero, letto dallo stesso RPC pubblico usato da
    send_signed_solana_tx — non uno fittizio, altrimenti il bundle verrebbe
    scartato per blockhash scaduto."""
    kp = Keypair.from_bytes(bytes.fromhex(private_key_hex))
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash", "params": []}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post("https://api.mainnet-beta.solana.com", json=payload)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"getLatestBlockhash fallito: {data['error']}")
    blockhash = Hash.from_string(data["result"]["value"]["blockhash"])
    ix = transfer(TransferParams(
        from_pubkey=kp.pubkey(), to_pubkey=Pubkey.from_string(tip_account), lamports=tip_lamports,
    ))
    msg = Message.new_with_blockhash([ix], kp.pubkey(), blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.sign([kp], blockhash)
    return bytes(tx)


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


def build_swap_router02_calldata(
    token_in: str, token_out: str, fee: int, recipient: str,
    amount_in: int, amount_out_minimum: int, sqrt_price_limit_x96: int = 0,
) -> bytes:
    """Codifica ABI di SwapRouter02.exactInputSingle — selettore verificato
    sopra + eth_abi (la libreria standard dell'ecosistema, non una
    reimplementazione fatta a mano dello spec ABI). NON ancora verificata
    contro una chiamata reale a un pool vero su Robinhood Chain: nessun
    indirizzo di pool/fee tier noto in questa sessione per farlo. Chi
    chiama non deve firmare una transazione costruita qui senza aver prima
    controllato fee/amount_out_minimum contro un quote fresco."""
    encoded = _abi_encode(
        ["(address,address,uint24,address,uint256,uint256,uint160)"],
        [(
            to_checksum_address(token_in), to_checksum_address(token_out), fee,
            to_checksum_address(recipient), amount_in, amount_out_minimum, sqrt_price_limit_x96,
        )],
    )
    return _SELECTOR_EXACT_INPUT_SINGLE + encoded


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


async def _robinhood_rpc(method: str, params: list) -> str:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(ROBINHOOD_RPC, json=payload)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC Robinhood Chain ({method}): {data['error']}")
    return data["result"]


async def build_signed_robinhood_swap(
    private_key_hex: str, token_in: str, token_out: str, fee: int,
    amount_in: int, amount_out_minimum: int, gas_limit: int = 300_000,
) -> bytes:
    """Costruisce ed firma una vera exactInputSingle su SwapRouter02 —
    nonce e gas price letti dal vivo via RPC (mai inventati), gas_limit
    fisso e prudente (uno swap Uniswap v3 a un solo hop ne usa tipicamente
    150-220k: 300k lascia margine senza essere assurdo). MAI l'invio, per
    lo stesso motivo di build_signed_solana_swap: quello resta dietro
    settings.onchain_execution_enabled, controllato da chi chiama."""
    account = Account.from_key(private_key_hex)
    nonce_hex = await _robinhood_rpc("eth_getTransactionCount", [account.address, "pending"])
    gas_price_hex = await _robinhood_rpc("eth_gasPrice", [])
    calldata = build_swap_router02_calldata(
        token_in, token_out, fee, account.address, amount_in, amount_out_minimum,
    )
    tx = {
        "nonce": int(nonce_hex, 16),
        "to": ROBINHOOD_SWAP_ROUTER02,
        "value": 0,
        "gas": gas_limit,
        "gasPrice": int(gas_price_hex, 16),
        "chainId": 4663,
        "data": "0x" + calldata.hex(),
    }
    return sign_evm_transaction(private_key_hex, tx)
