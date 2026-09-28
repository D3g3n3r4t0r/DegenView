"""Backtest H24 dei token della schermata Strategie (Top 50).

Lorenzo, 28/09: "voglio che quando il server e' online [...] scansioni
costantemente tutte le strategie e backtest [...] tutti quei token che sono
finiti nella schermata delle strategie [...] deve essere attivo costantemente
H24". Il laboratorio (backtest_lab.py) prova solo i token del diario vecchi
di 48 ore e solo quando GeckoTerminal e' libero: i token della Top non li
vedeva mai, e una Top senza alert non aveva nessun backtest.

Qui un giro al minuto: il token della Top con il backtest piu' vecchio (o
senza) prende le ultime candele da 5 minuti, passa da tutte le strategie
(system.backtest_all, lo stesso motore degli alert) e il risultato resta su
disco. Ogni token si rifa' ogni `REFRESH_S`. Ogni backtest finisce nel
registro dell'agente, cosi' la pagina Agent mostra il lavoro vero.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable

import httpx

from app.notify import deepseek_desk
from app.sniper.scanner import GECKO_NETWORKS
from app.trading.onchain import alert_track, system
from app.trading.onchain.storage import data_file

logger = logging.getLogger(__name__)

_STORE_FILE = data_file("onchain_strategy_lab.json")
DEX_TOKENS = "https://api.dexscreener.com/tokens/v1/{chain}/{token}"
TICK_S = 60
FIRST_TICK_DELAY_S = 60
REFRESH_S = 3600
BARS = 1000                      # 5 minuti: circa tre giorni e mezzo
DAILY_MIN_BARS = 60              # sotto questa soglia il daily non basta: si passa a 8h
KEEP = 300

_results: dict[str, dict] = {}   # chain:token -> {at, pair, symbol, backtests | error}
_state = {"last_tick": 0.0, "last_key": "", "error": ""}


def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        _results.update({k: v for k, v in raw.items() if isinstance(v, dict)})


def _save() -> None:
    try:
        _STORE_FILE.write_text(json.dumps(_results, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass


def reset_for_tests() -> None:
    _results.clear()
    _state.update(last_tick=0.0, last_key="", error="")


def key_of(chain: str, token: str) -> str:
    return f"{chain}:{token}"


def get(chain: str, token: str) -> dict | None:
    """I backtest di un token, nella forma di system.backtest_all."""
    r = _results.get(key_of(chain, token))
    return r.get("backtests") if r else None


def next_due(entries: list[dict], now: float) -> dict | None:
    """Il token da provare adesso: mai provato prima, poi il piu' vecchio
    oltre REFRESH_S. Solo reti che GeckoTerminal conosce."""
    due = []
    for e in entries:
        if not e.get("token_address") or not GECKO_NETWORKS.get(e.get("chain")):
            continue
        r = _results.get(key_of(e["chain"], e["token_address"]))
        at = (r or {}).get("at") or 0
        if now - at >= REFRESH_S:
            due.append((at, e))
    return min(due, key=lambda x: x[0])[1] if due else None


def status(entries: list[dict], now: float | None = None) -> dict:
    now = now or time.time()
    keys = [key_of(e["chain"], e["token_address"]) for e in entries if e.get("token_address")]
    ready = [k for k in keys if (_results.get(k) or {}).get("backtests")]
    fresh = [k for k in ready if now - (_results[k].get("at") or 0) < REFRESH_S]
    return {"total": len(keys), "ready": len(ready), "fresh": len(fresh), "refresh_s": REFRESH_S,
            "last_tick": _state["last_tick"], "error": _state["error"]}


async def _pair_of(client: httpx.AsyncClient, e: dict) -> str | None:
    """Il pool su cui provare: quello della Top, o il piu' liquido del token."""
    if e.get("pair_address"):
        return e["pair_address"]
    try:
        r = await client.get(DEX_TOKENS.format(chain=e["chain"], token=e["token_address"]))
        pairs = r.json() if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return None
    pairs = [p for p in pairs if isinstance(p, dict) and p.get("chainId") == e["chain"] and p.get("pairAddress")]
    if not pairs:
        return None
    return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)["pairAddress"]


def _best(bt: dict) -> dict | None:
    traded = [r for r in bt.get("rows") or [] if r.get("trades") and r.get("return_pct") is not None]
    return max(traded, key=lambda r: r["return_pct"]) if traded else None


def _merge_8h(bars: list[list]) -> list[list]:
    """Ogni due barre da 4 ore diventano una da 8: apertura della prima,
    massimo, minimo, chiusura della seconda, volume sommato. Le barre sono
    [ts, o, h, l, c, v] e si allineano sui bucket ts % 28800 == 0."""
    out: dict[int, list] = {}
    for b in sorted(bars):
        bucket = int(b[0]) // 28800 * 28800
        cur = out.get(bucket)
        if cur is None:
            out[bucket] = [bucket, b[1], b[2], b[3], b[4], b[5]]
        else:
            cur[2] = max(cur[2], b[2])
            cur[3] = min(cur[3], b[3])
            cur[4] = b[4]
            cur[5] = cur[5] + b[5]
    return [out[k] for k in sorted(out)]


async def run_daily(client: httpx.AsyncClient, net: str, pair: str, token: str, now: float) -> dict | None:
    """Il trend-follower del sito sul grafico giornaliero (o a 8 ore se il
    daily ha meno di DAILY_MIN_BARS barre). None = GeckoTerminal non risponde."""
    bars = await alert_track._candles(client, net, pair, "day", 1, now, 1000, token)
    if bars is None:
        return None
    iv = "1d"
    if len(bars) < DAILY_MIN_BARS:
        h4 = await alert_track._candles(client, net, pair, "hour", 4, now, 1000, token)
        if h4 is None:
            return None
        bars = _merge_8h(h4)
        iv = "8h"
    if len(bars) < system.BACKTEST_MIN_BARS:
        return {"interval": iv, "bars": len(bars), "error": "too few candles"}
    return {"interval": iv, **await asyncio.to_thread(system.backtest_one, sorted(bars))}


async def run_one(client: httpx.AsyncClient, e: dict, now: float) -> dict | None:
    """Un backtest. None = GeckoTerminal non risponde ora: si riprova al giro dopo."""
    key = key_of(e["chain"], e["token_address"])
    symbol = e.get("symbol") or "?"
    pair = await _pair_of(client, e)
    if not pair:
        _results[key] = {"at": now, "symbol": symbol, "pair": None, "error": "no pool"}
        return _results[key]
    bars = await alert_track._candles(client, GECKO_NETWORKS[e["chain"]], pair, "minute", 5, now, BARS,
                                      e["token_address"])
    if bars is None:
        return None
    if not bars:
        _results[key] = {"at": now, "symbol": symbol, "pair": pair, "error": "no candles"}
        return _results[key]
    bt = await asyncio.to_thread(system.backtest_all, sorted(bars))
    _results[key] = {"at": now, "symbol": symbol, "pair": pair, "backtests": bt}
    # Il daily e' un di piu': se fallisce il 5 minuti resta.
    try:
        daily = await run_daily(client, GECKO_NETWORKS[e["chain"]], pair, e["token_address"], now)
    except Exception:
        logger.exception("strategy lab: daily di %s fallito", symbol)
        daily = None
    if daily is not None:
        _results[key]["daily"] = daily
    best = _best(bt)
    hold = bt.get("hold_pct")
    outcome = (f"best {best['label']} {best['return_pct']:+.0f}% in {best['trades']} trades"
               if best else "no strategy entered")
    if hold is not None:
        outcome += f", holding {hold:+.0f}%"
    deepseek_desk.note("backtest", f"Backtested {symbol} on every strategy", now=now,
                       steps=[f"{len(bars)} 5-minute candles", f"{len(bt.get('rows') or [])} strategies"],
                       outcome=outcome, chain=e["chain"], token=e["token_address"])
    return _results[key]


async def tick(entries: list[dict], now: float | None = None) -> dict | None:
    now = now or time.time()
    _state["last_tick"] = now
    if priority.backtests_first():
        return None
    e = next_due(entries, now)
    if e is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            out = await run_one(client, e, now)
        _state.update(last_key=key_of(e["chain"], e["token_address"]), error="")
    except Exception as exc:
        logger.exception("strategy lab: backtest di %s fallito", e.get("symbol"))
        _state["error"] = str(exc)[:200]
        return None
    if len(_results) > KEEP:
        for k in sorted(_results, key=lambda k: _results[k].get("at") or 0)[:len(_results) - KEEP]:
            _results.pop(k, None)
    _save()
    return out


async def lab_loop(entries: Callable[[], list[dict]]) -> None:
    _load()
    await asyncio.sleep(FIRST_TICK_DELAY_S)
    while True:
        try:
            await tick(entries())
        except Exception:
            logger.exception("strategy lab: giro fallito")
        await asyncio.sleep(TICK_S)
