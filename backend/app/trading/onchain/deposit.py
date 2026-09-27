"""Where to send money in: one address per network, with its QR.

Lorenzo, 27/09 (screenshots of a "Deposit with" sheet: Crypto / Debit /
Exchanges and apps): "aggiungiamo queste possibilita' per i depositi".

The account's own wallets receive: the site's Solana wallet on Solana, the
site's EVM wallet on every EVM chain (one key, one address everywhere).
With no site wallet of that kind, a connected one stands in. Cash is USDC
(autotrader.py), so each network names its USDC contract: the one token to
send. Card purchases go through an on-ramp whose link the operator
configures (ONRAMP_URL); without it the option says so instead of pretending.
"""
from __future__ import annotations

import base64
import io
from urllib.parse import quote

import qrcode

from app.config import settings

NETWORKS = [
    # id, label, kind, USDC contract, what the balance/trading does with it
    ("solana", "Solana", "solana", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "trades"),
    ("base", "Base", "evm", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "balance"),
    ("bsc", "BNB Chain", "evm", "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", "balance"),
    ("robinhood", "Robinhood Chain", "evm", None, "trades"),
    ("ethereum", "Ethereum", "evm", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "balance"),
]

# Exchanges: the networks each one withdraws USDC on that we read, cheapest first.
EXCHANGES = [
    {"id": "coinbase", "label": "Coinbase", "networks": ["base", "solana", "ethereum"],
     "url": "https://www.coinbase.com/"},
    {"id": "binance", "label": "Binance", "networks": ["bsc", "solana", "base", "ethereum"],
     "url": "https://www.binance.com/en/my/wallet/account/main/withdrawal/crypto/USDC"},
]


def _qr(text: str) -> str:
    buf = io.BytesIO()
    qrcode.make(text, border=2).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def options(addresses: list[tuple[str, str, str]], robinhood_usdc: str | None = None) -> dict:
    """addresses: (kind, address, source) as main._all_addresses gives them,
    site wallets first."""
    by_kind: dict[str, tuple[str, str]] = {}
    for kind, addr, source in addresses:
        if kind not in by_kind or (source == "site" and by_kind[kind][1] != "site"):
            by_kind[kind] = (addr, source)
    nets = []
    for nid, label, kind, usdc, use in NETWORKS:
        if nid == "robinhood":
            usdc = robinhood_usdc or settings.robinhood_usdc_address or None
        hit = by_kind.get(kind)
        nets.append({"id": nid, "label": label, "kind": kind, "usdc": usdc, "use": use,
                     "address": hit[0] if hit else None, "source": hit[1] if hit else None,
                     "qr": _qr(hit[0]) if hit else None})
    onramp = None
    tpl = settings.onramp_url
    if tpl:
        sol = by_kind.get("solana")
        onramp = tpl.replace("{address}", quote(sol[0] if sol else "")) if "{address}" in tpl else tpl
    return {"networks": nets, "exchanges": EXCHANGES, "onramp": onramp}
