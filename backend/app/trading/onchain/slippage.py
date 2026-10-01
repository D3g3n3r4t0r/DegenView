"""The largest entry a pool takes without moving its price.

Lorenzo, 30/09: "il 10% [...] adesso che il portafoglio e' 30.000 [...] e'
3.000 su queste cripto che hanno liquidita' scarsa [...] dobbiamo far si' che
ci sia un tetto massimo di size [...] un'anteprima di quanto sarebbe lo
slippage [...] fare un check con i vari dex [...] calcolare velocemente quanto
potrebbe essere il size massimo [...] in termini di dollari".

The pool is read as a constant-product pool holding half its liquidity on the
stablecoin side (R = liquidity / 2). Buying x dollars fills at R / (R + x) of
the spot price, so the slippage is x / (R + x), and the largest buy under a
slippage s is s * R / (1 - s). Concentrated pools (Uniswap v3) are usually
deeper than that around the price: the estimate errs on the safe side.

A live quote is better than the pool's reported liquidity when there is one
(Jupiter on Solana, QuoterV2 on Robinhood Chain): its impact on the planned
size gives the depth the pool really has at this price, R = x (1 - i) / i.
BSC, Ethereum and Base have no quoter here: the pool depth is the estimate.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time

from app.config import settings

logger = logging.getLogger(__name__)

USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDG_ROBINHOOD = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
STABLE_DECIMALS = 6
_CACHE_S = 120
_cache: dict[tuple, tuple[float, dict]] = {}


def max_pct() -> float:
    return float(getattr(settings, "onchain_max_slippage_pct", 1.0) or 1.0)


def _ok(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v) and v > 0


def depth_of(liquidity_usd: float | None) -> float | None:
    """Dollars on the stablecoin side of a pool with this total liquidity."""
    return liquidity_usd / 2 if _ok(liquidity_usd) else None


def impact_pct(usd: float, depth: float | None) -> float | None:
    """Slippage of a buy of `usd` against `depth` dollars, in percent."""
    if not _ok(depth) or not isinstance(usd, (int, float)) or usd <= 0:
        return None
    return 100.0 * usd / (depth + usd)


def max_usd(depth: float | None, pct: float | None = None) -> float | None:
    """The largest buy whose slippage stays under `pct` percent."""
    s = (pct if pct is not None else max_pct()) / 100.0
    if not _ok(depth) or not 0 < s < 1:
        return None
    return s * depth / (1 - s)


def depth_from_quote(usd: float, impact: float | None) -> float | None:
    """The depth a quote's impact on `usd` implies (impact in percent)."""
    if not _ok(usd) or not isinstance(impact, (int, float)) or not math.isfinite(impact):
        return None
    i = impact / 100.0
    if i <= 1e-6:
        return None          # too small to read: the pool is far deeper than the order
    if i >= 1:
        return 0.0
    return usd * (1 - i) / i


def cap(stake: float, liquidity_usd: float | None, pct: float | None = None) -> tuple[float, dict]:
    """(stake under the cap, what was estimated). Unknown liquidity: no cap."""
    depth = depth_of(liquidity_usd)
    top = max_usd(depth, pct)
    if top is None:
        return stake, {}
    out = min(stake, top)
    return out, {"wanted": round(stake, 2), "max_usd": round(top, 2), "capped": out < stake,
                 "slip_pct": round(impact_pct(out, depth) or 0.0, 3)}


async def _live_impact(chain: str, token: str, usd: float) -> float | None:
    """A DEX's own price impact on buying `usd` of the token, or None."""
    from app.trading.onchain import quotes
    amount = int(usd * 10 ** STABLE_DECIMALS)
    if amount <= 0:
        return None
    if chain == "solana":
        q = await quotes.jupiter_quote(USDC_SOLANA, token, amount)
        return float(q["price_impact_pct"])
    if chain == "robinhood":
        found = await quotes.find_pool_and_fee(USDG_ROBINHOOD, token)
        if found is None:
            return None
        q = await quotes.uniswap_v3_quote(USDG_ROBINHOOD, token, found[1], amount)
        return float(q["price_impact_pct"])
    return None


async def preview(chain: str, token: str, usd: float, liquidity_usd: float | None = None,
                  pct: float | None = None, live: bool = True) -> dict:
    """What a buy of `usd` would cost in slippage, and the largest buy under
    the limit, from a DEX quote when there is one, else from the pool depth."""
    pct = pct if pct is not None else max_pct()
    key = (chain, token.lower(), round(usd, 2), round(liquidity_usd or 0), pct, live)
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < _CACHE_S:
        return hit[1]
    depth, source = None, None
    if live and _ok(usd):
        try:
            imp = await asyncio.wait_for(_live_impact(chain, token, usd), 8)
        except Exception as exc:
            logger.info("slippage: quote %s:%s failed: %s", chain, token, exc)
            imp = None
        if imp is not None:
            depth = depth_from_quote(usd, imp)
            source = "quote"
            if depth is None and _ok(liquidity_usd):
                depth = max(depth_of(liquidity_usd), usd * 1e4)   # below the quote's resolution
    if depth is None and _ok(liquidity_usd):
        depth, source = depth_of(liquidity_usd), "pool"
    top = max_usd(depth, pct)
    out = {"chain": chain, "token": token, "usd": round(usd, 2), "max_slippage_pct": pct, "source": source,
           "liquidity_usd": liquidity_usd, "slip_pct": None, "max_usd": None, "capped": False, "size_usd": round(usd, 2)}
    if top is not None:
        size = min(usd, top)
        out.update(slip_pct=round(impact_pct(usd, depth) or 0.0, 3), max_usd=round(top, 2), capped=size < usd,
                   size_usd=round(size, 2), size_slip_pct=round(impact_pct(size, depth) or 0.0, 3))
    if len(_cache) > 2000:
        _cache.clear()
    _cache[key] = (now, out)
    return out


def _it(v: float, dec: int = 0) -> str:
    return f"{v:,.{dec}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def text_it(p: dict) -> str:
    """One Italian line for the Telegram entry message."""
    if not p or p.get("max_usd") is None:
        return "Slippage: liquidita' sconosciuta, nessuna stima"
    src = "quote DEX" if p.get("source") == "quote" else "profondita' del pool"
    line = (f"Slippage stimato su ${_it(p['usd'])}: {_it(p['slip_pct'], 2)}% ({src}) · "
            f"size massima all'{_it(p['max_slippage_pct'], 1).rstrip('0').rstrip(',')}%: ${_it(p['max_usd'])}")
    if p.get("capped"):
        line += f" · ingresso ridotto a ${_it(p['size_usd'])}"
    return line
