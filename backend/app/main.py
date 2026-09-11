import asyncio
import hashlib
import io
import httpx
import itertools
import json
import logging
import sys
import time as _time
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# smartmoneyconcepts prints a unicode banner on import; Windows consoles using
# a non-UTF8 codepage would otherwise crash the app at startup. In a frozen
# sidecar spawned with redirected/null stdio, stdout/stderr may not support
# (or even have) .encoding — never let this startup nicety crash the app.
try:
    if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from app import auth
from app import issues as issues_store
from app import rate_limit
from app.trading.executor import place_futures_order_for_signal, place_order_for_signal
from app.trading.futures import registry as futures_registry
from app.trading.futures.base import FuturesCreds, FuturesExecutionError
from app.models import MAX_FUTURES_LEVERAGE
from app import archive as archive_store
from app import jobs as jobs_store
from app import trading_log
from app import favorites as favorites_store
from app import watchlist as watchlist_store
from app.analysis.backtest import run_backtest
from app.analysis.futures_math import DEFAULT_MAINTENANCE_MARGIN_RATE, liquidation_price
from app.analysis.cancel import SearchCancelled
from app.export import build_backtest_workbook
from app.analysis.confluence import compute_confluence
from app.analysis.indicators import compute_indicators
from app.analysis.fibonacci import compute_fib_zones
from app.analysis.optimize import (
    Constraints,
    NoCandidateMeetsConstraints,
    is_optimizable,
    optimize_strategy,
)
from app.analysis.pipeline import run_pipeline
from app.analysis.smc_engine import compute_dealing_range, compute_levels, compute_swings
from app.analysis.strategies import AVAILABLE_STRATEGIES, DEFAULT_STRATEGY, build_strategy_state
from app.analysis.summary import build_summary, determine_bias
from app.cache import get_or_fetch
from app.config import settings
from app.live.mexc_stream import mexc_stream_manager
from app.models import (
    AnalysisResponse,
    AssetType,
    BacktestResult,
    Candle,
    CryptoExchange,
    FavoriteEntry,
    StrategyState,
    SymbolSuggestion,
    TimeframeAnalysis,
    TimeframeKey,
    User,
    WatchlistEntry,
)
from app.exchange_balances import BalanceFetchError, fetch_kucoin_balances, fetch_mexc_balances
from app.notify import telegram
from app.notify import alert_log
from app.notify import alerts
from app.notify.alerts import find_new_signals, format_signal_message, record_alert_sent, get_all_stats_for_entry
import app.price_alerts as price_alerts_store
from app.models import PriceAlert, PriceAlertCondition, StrategySignal
from app.pine import PineError, PineInterpreter, is_strategy_style, parse_program, scan_inputs
from app.pine import storage as pine_storage
from app.providers.base import (
    DataProvider,
    ProviderError,
    ProviderUnreachable,
    QuotaExceeded,
)
from app.providers.binance import BinanceProvider
from app.providers.binance import format_symbol as format_binance_symbol
from app.providers.kraken import KrakenProvider
from app.providers.kraken import format_symbol as format_kraken_symbol
from app.providers.kucoin import KucoinProvider
from app.providers.kucoin import format_symbol as format_kucoin_symbol
from app.providers.mexc import MexcProvider
from app.providers.mexc import format_symbol as format_mexc_symbol
from app.providers.twelvedata import TwelveDataProvider
from app.resample import resample_by_count
from app.timeframes import (
    CANONICAL_INTERVALS,
    DEFAULT_INTERVALS,
    SYNTHETIC_DAY_INTERVALS,
    IntervalChoice,
    drop_unclosed_candle,
)
from starlette.middleware.gzip import GZipMiddleware

logger = logging.getLogger(__name__)
if getattr(sys, "frozen", False):
    FRONTEND_DIR = Path(sys._MEIPASS) / "frontend"  # type: ignore[attr-defined]
else:
    FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
WATCHLIST_POLL_SECONDS = 60

# L'elenco degli exchange futures vive nel registro degli adattatori: qui
# c'e' solo il nome vecchio, perche' non ci sia una seconda lista che possa
# essere in disaccordo con la prima. Il perimetro (leva accessibile
# dall'Europa) e' spiegato in app/trading/futures/registry.py.
SUPPORTED_FUTURES_EXCHANGES_ORDERED = futures_registry.SUPPORTED_FUTURES_EXCHANGES

twelvedata_provider = TwelveDataProvider()
mexc_provider = MexcProvider()
binance_provider = BinanceProvider()
kucoin_provider = KucoinProvider()
kraken_provider = KrakenProvider()


def _telegram_allowed(user: User) -> bool:
    allowed = {e.strip().lower() for e in settings.telegram_allowed_emails.split(",") if e.strip()}
    return not allowed or user.email.lower() in allowed


def _balance_visible(user: User) -> bool:
    allowed = {e.strip().lower() for e in settings.balance_visible_emails.split(",") if e.strip()}
    return not allowed or user.email.lower() in allowed


_BACKTEST_MIN_INTERVAL = "1d"


def backtest_interval_for(ltf_interval: str) -> str:
    """The backtest deliberately runs on a coarser feed than whatever the
    chart happens to be set to — a fixed candle budget covers years at "1d"
    but only hours at "1m", and the user is after the deepest history the
    exchange has, not a simulation tied to the chart's own granularity.
    Never goes coarser than the chart itself, though: if ltf is already
    "1w"/"1M" there's nothing to gain by stepping back down to daily."""
    if CANONICAL_INTERVALS.index(ltf_interval) >= CANONICAL_INTERVALS.index(_BACKTEST_MIN_INTERVAL):
        return ltf_interval
    return _BACKTEST_MIN_INTERVAL


async def _no_results() -> list:
    """Segnaposto per la ricerca quando le azioni sono spente: la gather
    vuole comunque qualcosa da attendere."""
    return []


def get_provider(asset_type: AssetType, exchange: CryptoExchange = "mexc") -> DataProvider:
    if asset_type != "crypto":
        if not settings.stocks_enabled:
            # Meglio dirlo qui, una volta, che lasciare che fallisca piu'
            # avanti con "chiave TwelveData mancante" — un errore che parla
            # di una chiave quando il problema e' che le azioni sono spente.
            raise HTTPException(
                status_code=400,
                detail="Le azioni sono disattivate: questo sistema opera solo su crypto (USDT/USDC).",
            )
        return twelvedata_provider
    if exchange == "binance":
        return binance_provider
    if exchange == "kucoin":
        return kucoin_provider
    if exchange == "kraken":
        return kraken_provider
    return mexc_provider


def canonical_symbol(symbol: str, asset_type: AssetType, exchange: CryptoExchange = "mexc") -> str:
    """The exact trading-pair string a provider actually resolves a query
    to (e.g. "BTC" -> "BTCUSDT" on MEXC) — echoed back in API responses
    instead of the raw query so the same instrument always identifies
    itself the same way regardless of how it was searched for. The
    frontend keys client-side drawing persistence off this value; without
    it, typing "BTC" versus clicking the "BTCUSDT" suggestion produced two
    different symbols for the same chart, and drawings saved under one
    never showed up under the other."""
    if asset_type != "crypto":
        return symbol.strip().upper()
    if exchange == "binance":
        return format_binance_symbol(symbol)
    if exchange == "kucoin":
        return format_kucoin_symbol(symbol)
    if exchange == "kraken":
        return format_kraken_symbol(symbol)
    return format_mexc_symbol(symbol)


async def fetch_ohlcv_canonical(provider: DataProvider, symbol: str, interval: str, outputsize: int):
    """Like provider.fetch_ohlcv, but transparently synthesizes intervals no
    provider natively supports (2D/3D/5D) by fetching extra 1D candles and
    folding them down — every call site gets these for free."""
    multiple = SYNTHETIC_DAY_INTERVALS.get(interval)
    if multiple is None:
        return await provider.fetch_ohlcv(symbol, interval, outputsize)
    raw = await provider.fetch_ohlcv(symbol, "1d", outputsize * multiple)
    return resample_by_count(raw, multiple).tail(outputsize)


async def _fetch_cached(key: tuple, provider: DataProvider, symbol: str, interval: str, outputsize: int):
    """Shared helper: wraps fetch_ohlcv_canonical + get_or_fetch so each
    route doesn't need to declare its own inner do_fetch closure."""
    async def _do():
        return await fetch_ohlcv_canonical(provider, symbol, interval, outputsize)
    return await get_or_fetch(key, _do)



async def _watchlist_alert_loop() -> None:
    """Background loop, independent of any browser tab: evaluates every
    watchlist ticker against each of its enabled strategies and fires
    Telegram alerts — never for whatever symbol happens to be open on
    screen. One fetch per (ticker, timeframe), reused across every strategy
    enabled on that ticker rather than refetching per strategy."""
    while True:
        await asyncio.sleep(WATCHLIST_POLL_SECONDS)
        if not settings.telegram_bot_token:
            continue
        for entry in watchlist_store.list_entries():
            if not entry.strategies:
                continue
            owner = auth.get_user(entry.owner_id)
            if owner is None or not owner.telegram_chat_id or not _telegram_allowed(owner):
                continue  # no chat_id yet, or this account isn't on the Telegram delivery allowlist
            if _quota_paused(entry.asset_type, entry.exchange):
                continue
            provider = get_provider(entry.asset_type, entry.exchange)
            try:
                df = await fetch_ohlcv_canonical(
                    provider, entry.symbol, entry.interval, settings.candles_per_timeframe
                )
                _provider_recovered(entry.asset_type, entry.exchange)
                if entry.on_close:
                    df = drop_unclosed_candle(df, entry.interval)
                if df.empty:
                    continue
                # Price-level alerts (checked once per entry poll regardless of strategies)
                if df is not None and not df.empty:
                    current_price = float(df["close"].iloc[-1])
                    triggered_pa = price_alerts_store.check_alerts(owner.id, entry.symbol, current_price)
                    for pa in triggered_pa:
                        direction = "sopra" if pa.condition == PriceAlertCondition.crosses_above else "sotto"
                        msg = (
                            f"🎯 <b>{pa.symbol}</b> [{entry.interval}] — Alert prezzo\n"
                            f"Prezzo {direction} <b>{pa.price:g}</b>\n"
                            f"Prezzo attuale: {current_price:g}"
                            + (f"\n{pa.note}" if pa.note else "")
                        )
                        asyncio.create_task(telegram.send_to(owner.telegram_chat_id, msg))
                        alert_log.append_entry(
                            owner_id=owner.id,
                            symbol=pa.symbol,
                            interval=entry.interval,
                            strategy_name="Alert prezzo",
                            signal_type=pa.condition.value,
                            price=current_price,
                            label=f"Prezzo {direction} {pa.price:g}",
                            chat_id=owner.telegram_chat_id,
                        )

                for strategy_name in entry.strategies:
                    strategy_interval = entry.strategy_intervals.get(strategy_name, entry.interval)
                    # Refetch if the strategy uses a different interval than the entry default
                    if strategy_interval != entry.interval:
                        try:
                            strat_df = await fetch_ohlcv_canonical(
                                provider, entry.symbol, strategy_interval, settings.candles_per_timeframe
                            )
                            if entry.on_close:
                                strat_df = drop_unclosed_candle(strat_df, strategy_interval)
                        except Exception:
                            strat_df = df
                    else:
                        strat_df = df
                    params = entry.strategy_params.get(strategy_name) or None
                    strategy = build_strategy_state(strategy_name, strat_df, params=params)
                    frequency = entry.alert_frequency.get(strategy_name, "every")
                    fresh = _dispatch_telegram_alerts(
                        owner.telegram_chat_id,
                        entry.symbol,
                        strategy_interval,
                        strategy,
                        frequency=frequency,
                        entry_id=entry.id,
                        owner_id=owner.id,
                    )
                    # Esecuzione automatica degli ordini, se l'exchange e'
                    # configurato. Ogni esito finisce nel diario: e' un percorso
                    # che, funzionando, non diceva nulla — ed e' esattamente cosi'
                    # che e' rimasto morto per mesi senza che nessuno potesse
                    # accorgersene.
                    cred = owner.trading_credentials.get(entry.exchange)
                    # Opt-in per singola strategia/ticker (dalla watchlist): un
                    # exchange abilitato non basta piu' da solo a far partire
                    # ordini su OGNI strategia che ci gira sopra.
                    if cred and fresh and entry.auto_trade.get(strategy_name):
                        api_key, api_secret, passphrase = auth.get_decrypted_credential(owner, entry.exchange)
                        skip = ""
                        if not cred.enabled:
                            skip = "esecuzione automatica disattivata per questo exchange"
                        elif not (api_key and api_secret):
                            skip = "chiavi API mancanti o non leggibili"
                        if skip:
                            # Registrato solo per chi l'exchange l'ha configurato:
                            # per tutti gli altri non c'e' nulla da segnalare, e
                            # riempire il diario di "non configurato" lo
                            # renderebbe illeggibile proprio a chi lo consulta.
                            for signal in fresh:
                                trading_log.record(
                                    owner.id, symbol=entry.symbol, exchange=entry.exchange,
                                    strategy_name=strategy_name, signal_type=signal.type,
                                    outcome="saltato", detail=skip, price=signal.price,
                                )
                        else:
                            # I segnali arrivano dalla chiamata sopra. Richiederli
                            # qui tornava sempre vuoto — find_new_signals li aveva
                            # gia' marcati come visti — quindi nessun ordine e'
                            # mai partito, in silenzio.
                            for signal in fresh:
                                try:
                                    result = await place_order_for_signal(
                                        entry.exchange, entry.symbol, signal,
                                        cred.size_mode, cred.size_value,
                                        api_key, api_secret, passphrase,
                                    )
                                    logger.info("Order placed for %s %s: %s", entry.symbol, signal.type, result)
                                    trading_log.record(
                                        owner.id, symbol=entry.symbol, exchange=entry.exchange,
                                        strategy_name=strategy_name, signal_type=signal.type,
                                        outcome="eseguito", detail=str(result)[:400], price=signal.price,
                                    )
                                    if owner.telegram_chat_id and _telegram_allowed(owner):
                                        # Un ordine partito va detto quanto uno
                                        # fallito: era l'unico dei due casi che
                                        # restava muto.
                                        asyncio.create_task(telegram.send_to(
                                            owner.telegram_chat_id,
                                            f"💱 Ordine ESEGUITO <b>{entry.symbol}</b> [{signal.type}] "
                                            f"su {entry.exchange} a {signal.price:g}",
                                        ))
                                except Exception as exc:
                                    logger.error("Order failed for %s %s: %s", entry.symbol, signal.type, exc)
                                    trading_log.record(
                                        owner.id, symbol=entry.symbol, exchange=entry.exchange,
                                        strategy_name=strategy_name, signal_type=signal.type,
                                        outcome="fallito", detail=str(exc), price=signal.price,
                                    )
                                    if owner.telegram_chat_id and _telegram_allowed(owner):
                                        asyncio.create_task(telegram.send_to(
                                            owner.telegram_chat_id,
                                            f"⚠️ Ordine FALLITO <b>{entry.symbol}</b> [{signal.type}]: {exc}",
                                        ))
            except ProviderUnreachable as exc:
                # Rete, TLS, proxy: quasi sempre passeggero. Si mette in pausa
                # quel provider con attesa crescente e si parla solo se il buco
                # dura — un errore che al giro dopo non si ripresenta non vale
                # un messaggio d'allarme.
                streak = _pause_for_unreachable(entry.asset_type, entry.exchange)
                if _notify_unreachable_once(entry.asset_type, entry.exchange, streak):
                    asyncio.create_task(telegram.send_to(
                        owner.telegram_chat_id,
                        f"📡 <b>{entry.exchange}</b> non risponde da qualche minuto.\n"
                        f"Il monitoraggio riprende da solo appena torna raggiungibile.\n\n"
                        f"<i>{exc}</i>",
                    ))
                continue
            except QuotaExceeded as exc:
                # I crediti del piano sono finiti: non c'e' niente da riprovare
                # fra un minuto. Senza questa pausa arrivava un messaggio di
                # "errore monitoraggio" per ticker per minuto — un guasto
                # apparente al posto di un limite di piano.
                _pause_for_quota(entry.asset_type, entry.exchange, exc)
                if _notify_quota_once(owner.id, entry.asset_type, entry.exchange):
                    asyncio.create_task(telegram.send_to(
                        owner.telegram_chat_id,
                        f"⏸️ <b>Crediti dati esauriti</b> ({entry.exchange if entry.asset_type == 'crypto' else 'Twelve Data'})\n"
                        f"Il monitoraggio dei titoli riprende automaticamente quando la quota si azzera. "
                        f"Le crypto non sono toccate.\n\n<i>{exc}</i>",
                    ))
                continue
            except Exception as exc:  # noqa: BLE001
                logger.error("Alert loop error for %s: %s", entry.symbol, exc, exc_info=True)
                if settings.telegram_bot_token and owner.telegram_chat_id and _telegram_allowed(owner):
                    asyncio.create_task(
                        telegram.send_to(
                            owner.telegram_chat_id,
                            f"⚠️ Errore monitoraggio <b>{entry.symbol}</b> [{entry.interval}]: {exc}",
                        )
                    )


# --- pausa per quota esaurita ------------------------------------------------
# Chiave = (asset_type, exchange) e non l'utente: la quota e' del piano, quindi
# e' condivisa; fermare solo chi ha incontrato l'errore lascerebbe gli altri a
# consumarne altri e a ricevere lo stesso messaggio a turno.
_quota_pause_until: dict[tuple[str, str], float] = {}
_quota_notified: dict[tuple[str, str, str], float] = {}


def _quota_key(asset_type: str, exchange: str) -> tuple[str, str]:
    return (asset_type, exchange if asset_type == "crypto" else "twelvedata")


def _quota_paused(asset_type: str, exchange: str) -> bool:
    return _quota_pause_until.get(_quota_key(asset_type, exchange), 0.0) > _time.time()


def _pause_for_quota(asset_type: str, exchange: str, exc: QuotaExceeded) -> None:
    wait = exc.retry_after_s or 3600
    _quota_pause_until[_quota_key(asset_type, exchange)] = _time.time() + wait
    logger.warning("quota esaurita su %s/%s: pausa di %ss", asset_type, exchange, wait)


# Irraggiungibilita': quasi sempre passeggera. Si conta quante volte di fila
# succede, invece di reagire alla prima — un errore TLS che al giro dopo non si
# ripresenta non merita un messaggio, e mandarlo comunque e' come e' arrivata
# la segnalazione su MEXC.
_UNREACHABLE_BACKOFF_S = (300, 600, 1200, 3600)
_UNREACHABLE_SPEAK_AFTER = 3        # ~15 minuti di buco prima di dire qualcosa
_unreachable_streak: dict[tuple[str, str], int] = {}


def _pause_for_unreachable(asset_type: str, exchange: str) -> int:
    """Mette in pausa quel provider e restituisce da quante volte di fila fallisce."""
    key = _quota_key(asset_type, exchange)
    streak = _unreachable_streak.get(key, 0) + 1
    _unreachable_streak[key] = streak
    wait = _UNREACHABLE_BACKOFF_S[min(streak - 1, len(_UNREACHABLE_BACKOFF_S) - 1)]
    _quota_pause_until[key] = _time.time() + wait
    logger.warning("provider %s/%s non raggiungibile (%d di fila): pausa di %ss",
                   asset_type, exchange, streak, wait)
    return streak


def _provider_recovered(asset_type: str, exchange: str) -> None:
    """Una lettura riuscita azzera il conteggio: altrimenti un guasto di ieri
    farebbe scattare l'allarme al primo inciampo di domani."""
    key = _quota_key(asset_type, exchange)
    if _unreachable_streak.pop(key, 0):
        _quota_notified.pop((None,) + key, None)


def _notify_unreachable_once(asset_type: str, exchange: str, streak: int) -> bool:
    """Si parla solo se il buco dura, e una volta sola finche' dura."""
    if streak < _UNREACHABLE_SPEAK_AFTER:
        return False
    key = (None,) + _quota_key(asset_type, exchange)
    if _quota_notified.get(key):
        return False
    _quota_notified[key] = _time.time()
    return True


def _notify_quota_once(owner_id: str, asset_type: str, exchange: str) -> bool:
    """Un messaggio per utente e per pausa, non uno per ticker per minuto."""
    k = (owner_id,) + _quota_key(asset_type, exchange)
    until = _quota_pause_until.get(_quota_key(asset_type, exchange), 0.0)
    if _quota_notified.get(k, 0.0) >= until:
        return False
    _quota_notified[k] = until
    return True


_LAST_SHA_FILE = Path(__file__).resolve().parent.parent / "data" / "last_deploy_sha.txt"
_GITHUB_REPO = "lorenzocorazzi-wq/liquidity-analysis-engine"


async def _notify_deploy() -> None:
    # Nessuna delle uscite qui sotto era loggata: un token mancante o
    # scaduto spegneva l'avviso di deploy senza lasciare traccia da nessuna
    # parte, ne' nei log del container ne' altrove — lo stesso tipo di
    # silenzio che il progetto ha gia' imparato a non tollerare (seed-0025).
    if not settings.telegram_bot_token:
        logger.warning("Notifica deploy saltata: TELEGRAM_BOT_TOKEN non configurato")
        return
    if not settings.github_api_token:
        logger.warning("Notifica deploy saltata: GITHUB_API_TOKEN non configurato")
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"https://api.github.com/repos/{_GITHUB_REPO}/commits",
                headers={"Authorization": f"Bearer {settings.github_api_token}",
                         "Accept": "application/vnd.github+json"},
                params={"per_page": 10},
            )
            r.raise_for_status()
            commits = r.json()
    except Exception as exc:
        logger.warning("Notifica deploy saltata: richiesta a GitHub fallita — %s", exc)
        return
    if not commits:
        return
    current_sha = commits[0]["sha"]
    last_sha = _LAST_SHA_FILE.read_text(encoding="utf-8").strip() if _LAST_SHA_FILE.exists() else ""
    _LAST_SHA_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAST_SHA_FILE.write_text(current_sha, encoding="utf-8")
    if last_sha == current_sha:
        return  # restart, not a new deploy
    new_commits = [c for c in commits if c["sha"] != last_sha]
    if last_sha:
        try:
            idx = next(i for i, c in enumerate(commits) if c["sha"] == last_sha)
            new_commits = commits[:idx]
        except StopIteration:
            new_commits = commits[:5]
    lines = []
    for c in new_commits:
        msg = c["commit"]["message"].splitlines()[0][:80]
        sha_short = c["sha"][:7]
        lines.append(f"• <code>{sha_short}</code> {msg}")
    changelog = "\n".join(lines) if lines else "• (nessun commit trovato)"
    text = f"🚀 <b>Nuovo deploy completato</b>\n\n<b>Modifiche:</b>\n{changelog}"
    await telegram.send_message(text)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.sniper import cache as sniper_cache
    from app.sniper import agents as sniper_agents
    from app.sniper.cex_check import enrichment_loop
    asyncio.create_task(_notify_deploy())
    t1 = asyncio.create_task(_watchlist_alert_loop())
    t2 = asyncio.create_task(sniper_cache.polling_loop())
    t3 = asyncio.create_task(enrichment_loop())
    agent_tasks = await sniper_agents.start_all()
    yield
    t1.cancel()
    t2.cancel()
    t3.cancel()
    for t in agent_tasks:
        t.cancel()


app = FastAPI(title="Liquidity Analysis Engine", lifespan=lifespan)

# ── Cancello di autenticazione ────────────────────────────────────────────
#
# Il sito e' su internet, e per mesi 33 endpoint hanno risposto a chiunque
# senza credenziali. Fra questi:
#
#   - /api/optimize e /api/analyze, che occupano un core per minuti. Su una
#     macchina a due core, due richieste anonime bastavano a rendere il sito
#     inutilizzabile e ad affamare il ciclo che manda gli avvisi.
#   - DELETE /api/pinescript/{id}, che cancellava gli script di chiunque
#     senza chiedere chi fosse.
#   - POST /api/sniper/scan, che faceva partire scansioni esterne a comando.
#
# La difesa e' un cancello unico invece di 33 firme da correggere a mano: un
# endpoint nuovo nasce protetto, e dimenticarsi di proteggerlo non e' piu'
# possibile. Chi vuole aprire una porta deve scriverlo qui, dove si legge
# tutto insieme.
#
# Le pagine restano pubbliche: servono a mostrare il modulo di accesso.
_PUBLIC_PATHS = frozenset({
    "/",                    # la pagina, che poi chiede di accedere
    "/sniper",
    "/favicon.ico",
    "/robots.txt",
    "/api/health",          # per il controllo di salute del container
    "/api/version",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/logout",
    "/api/auth/me",         # il frontend chiede "chi sono" prima di sapere se e' entrato
    "/api/issues",          # la bacheca: CLAUDE.md dice di leggerla con un curl senza
                            # login a inizio sessione — il gate globale (seed-0031) la
                            # bloccava da quando e' stato introdotto, senza che nessuna
                            # sessione se ne accorgesse perche' il fallimento e' silenzioso
                            # (un 401 che sembra "nessuna segnalazione nuova"). GET soltanto
                            # nei fatti: POST /api/issues resta protetto dalla sua stessa
                            # dependency (auth.get_current_user), non da questa lista.
})

_PUBLIC_PREFIXES = ("/static/",)


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.url.path
    if (
        request.method == "OPTIONS"
        or path in _PUBLIC_PATHS
        or path.startswith(_PUBLIC_PREFIXES)
    ):
        return await call_next(request)

    # Un test che ha iniettato un utente con dependency_overrides ha gia'
    # dichiarato chi e': il cancello girerebbe prima delle dipendenze e lo
    # rifiuterebbe comunque. In produzione quel dizionario resta vuoto, quindi
    # questa riga non apre niente a nessuno.
    if app.dependency_overrides:
        return await call_next(request)

    if auth._verify_session_cookie(request.cookies.get(auth.SESSION_COOKIE) or ""):
        return await call_next(request)

    return JSONResponse(
        status_code=401,
        content={"detail": "Accesso richiesto: questa funzione e' riservata agli utenti registrati."},
    )

app.add_middleware(GZipMiddleware, minimum_size=500)


# Un 422 e' l'unica risposta d'errore che l'app non scrive da se': la genera
# FastAPI prima di entrare nell'endpoint, e il suo `detail` e' una lista di
# oggetti pensata per un client che la sappia leggere. In pagina diventava
# "Errore 422", cioe' un numero che non dice ne' quale campo ne' cosa ci
# voleva — la segnalazione di Lorenzo. Qui la lista diventa una frase, con il
# nome del parametro e il valore ricevuto: sbagliare resta possibile, non
# capire cosa si e' sbagliato no.

_VALIDATION_WORDING = {
    "int_parsing": "serve un numero intero",
    "int_from_float": "serve un numero intero, senza decimali",
    "int_type": "serve un numero intero",
    "float_parsing": "serve un numero",
    "float_type": "serve un numero",
    "bool_parsing": "serve vero o falso",
    "literal_error": "valore non ammesso",
    "enum": "valore non ammesso",
    "missing": "parametro obbligatorio mancante",
    "string_too_short": "troppo corto",
    "string_too_long": "troppo lungo",
    "greater_than_equal": "troppo piccolo",
    "less_than_equal": "troppo grande",
    "string_pattern_mismatch": "valore non ammesso",
}


def _validation_message(errors: list[dict]) -> str:
    parts: list[str] = []
    for err in errors[:4]:
        loc = [str(x) for x in err.get("loc", ()) if x not in ("query", "body", "path")]
        field = ".".join(loc) or "richiesta"
        wording = _VALIDATION_WORDING.get(err.get("type", ""), err.get("msg", "valore non valido"))
        got = err.get("input", None)
        # Il valore ricevuto e' meta' della diagnosi: "serve un numero intero"
        # senza il "ricevuto ''" non fa capire che il campo era rimasto vuoto.
        if isinstance(got, str):
            shown = f' (ricevuto "{got[:40]}")' if got != "" else " (campo vuoto)"
        elif got is None:
            shown = ""
        else:
            shown = f" (ricevuto {str(got)[:40]})"
        parts.append(f"{field}: {wording}{shown}")
    if len(errors) > 4:
        parts.append(f"e altri {len(errors) - 4}")
    return "Parametri non validi — " + " · ".join(parts)


@app.exception_handler(RequestValidationError)
async def _readable_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": _validation_message(exc.errors())})


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception):
    """Un 500 vero — quello che prima si vedeva solo nei log del container,
    irraggiungibili da qui senza SSH. Registrato su file (server_errors.json,
    sul volume) e letto da GET /api/errors, cosi' una sessione futura puo'
    consultarlo con una richiesta HTTP invece di aspettare che qualcuno lo
    segnali. Un avviso Telegram parte nello stesso istante, con un raffreddamento
    di 5 minuti per lo stesso errore ripetuto — un bug che rifiorisce a ogni
    retry non deve mandare un messaggio al secondo.

    Non intercetta gli HTTPException (hanno gia' un handler piu' specifico
    prima di questo): qui arrivano solo le eccezioni che nessun endpoint si
    aspettava.
    """
    from app import error_log
    from app.notify import telegram

    user_id = None
    try:
        user = await auth.get_current_user_optional(
            request.cookies.get(auth.SESSION_COOKIE)
        )
        user_id = user.id if user else None
    except Exception:  # noqa: BLE001 — non deve mai impedire di registrare l'errore vero
        pass

    logger.exception("Errore non gestito su %s %s", request.method, request.url.path)
    entry, should_alert = error_log.record(
        method=request.method, path=request.url.path, exc=exc, user_id=user_id,
    )
    if should_alert:
        asyncio.create_task(telegram.send_message(
            f"🔴 Errore 500 su {entry['method']} {entry['path']}\n"
            f"{entry['exc_type']}: {entry['message']}"
        ))
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/api/errors")
async def list_server_errors(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(auth.get_current_user),
) -> dict:
    """Gli ultimi errori 500 veri, con traceback — protetto dallo stesso
    cancello di seed-0031 (non e' in _PUBLIC_PATHS), non serve altro controllo."""
    from app import error_log
    return {"errors": error_log.recent(limit)}


_app_start = _time.time()

@app.get("/api/health")
async def health():
    from app.cache import _intraday_cache, _daily_cache
    return {
        "status": "ok",
        "uptime_s": round(_time.time() - _app_start),
        "cache_size": len(_intraday_cache) + len(_daily_cache),
    }


class StrategyParamsQuery(BaseModel):
    # Every strategy's own params live on this one shared query model — each
    # compute_*_signals() only ever reads its own keys (merged over that
    # strategy's DEFAULT_PARAMS) and ignores the rest, so there's no
    # cross-strategy collision in practice: the frontend only ever renders
    # (and sends) one strategy's field set at a time (see
    # STRATEGY_PARAM_FIELDS in app.js), even though a couple of names below
    # are shared between two strategies (rsi_length, rsi_oversold,
    # rsi_overbought — both Gabriele's and Exhaustion's own versions of
    # those, never sent together). A field missing here is a field silently
    # dropped by FastAPI's query parsing regardless of what the frontend
    # sends, so keep this in sync with STRATEGY_PARAM_FIELDS in app.js and
    # each strategy's own *_DEFAULT_PARAMS in app.analysis.strategies.

    # Lorenzo (trend-follower)
    average: Literal["EMA", "SMA"] = "EMA"
    len: int = 130
    slopeFlen: int = 7
    slopeSlen: int = 27
    trendfilter: bool = True
    trendfilterperiod: int = 268
    trendfiltertype: Literal["EMA", "SMA"] = "EMA"
    volatilityfilter: bool = True
    volatilitystdevlength: int = 16
    volatilitystdevmalength: int = 44
    # Zero = spenta, cioe' il comportamento storico. Vedi la nota nel modulo
    # delle strategie: e' in unita' di sigma perche' deve valere uguale su
    # qualsiasi coppia.
    slope_threshold_sigma: float = 0.0
    slope_sigma_length: int = 100

    # Accumulo/Distribuzione (long-term) — exposed as independent toggles
    # rather than baked into a silent OR: each condition was added reactively
    # against a single chart, so a user who trusts only the divergence
    # condition can turn the other two off instead of trusting all three.
    enable_divergence: bool = True
    enable_contraction: bool = True
    enable_range_bounce: bool = True
    swing_length: int = 8
    rsi_min_gap: float = 3.0
    low_tolerance_pct: float = 1.0
    divergence_lookback: int = 3
    volume_ma_length: int = 20
    volume_multiplier: float = 1.3
    trend_filter: bool = True
    trend_ema_length: int = 50
    confirmation_lookahead: int = 10
    contraction_lookback: int = 10
    contraction_prior_lookback: int = 30
    contraction_ratio: float = 0.55
    range_lookback: int = 40
    range_zone_pct: float = 0.25

    # Shared between Exhaustion and Gabriele (RSI+BB reversal) — never sent
    # together, see the class docstring above.
    rsi_length: int = 14
    rsi_oversold: int = 28
    rsi_overbought: int = 72

    # Gabriele (RSI+BB reversal)
    bb_length: int = 20
    bb_mult: float = 2.0


class BacktestParamsQuery(BaseModel):
    initial_capital: float = 10000.0
    qty_pct_of_equity: float = 30.0
    commission_pct: float = 0.06
    slippage_pct: float = 0.02
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    # Quando si considera eseguito il segnale: alla chiusura della candela
    # che lo genera (storico, ottimista) oppure all'apertura della candela
    # dopo (realizzabile). Vedi DEFAULT_BACKTEST_PARAMS in backtest.py.
    fill_at: Literal["signal_close", "next_open"] = "signal_close"


class TradingCredentialRequest(BaseModel):
    exchange: str
    api_key: str = ""        # empty = keep existing
    api_secret: str = ""     # empty = keep existing
    passphrase: str = ""     # empty = keep existing
    enabled: bool = False
    size_mode: Literal["fixed_usdt", "pct_balance"] = "fixed_usdt"
    size_value: float = 50.0


class TradingCredentialOut(BaseModel):
    exchange: str
    api_key_set: bool        # True if an encrypted key exists
    api_secret_set: bool
    passphrase_set: bool
    enabled: bool
    size_mode: str
    size_value: float


class FuturesCredentialRequest(BaseModel):
    exchange: str
    api_key: str = ""     # empty = keep existing
    api_secret: str = ""  # empty = keep existing
    passphrase: str = ""  # empty = keep existing — serve su OKX e Bitget
    enabled: bool = False  # kill switch — spegnibile senza toccare le chiavi
    size_mode: Literal["fixed_usdt", "pct_balance"] = "fixed_usdt"
    size_value: float = 50.0
    leverage: int = 1


class FuturesCredentialOut(BaseModel):
    exchange: str
    name: str
    api_key_set: bool
    api_secret_set: bool
    passphrase_set: bool
    needs_passphrase: bool
    # Il tetto e' del singolo exchange, non piu' uno solo per tutti: la
    # schermata deve poter fermare il cursore dove lo ferma il server.
    max_leverage: int
    isolated_margin: bool
    key_hint: str
    enabled: bool
    size_mode: str
    size_value: float
    leverage: int


async def _safe_search(
    provider: DataProvider, query: str, asset_type: AssetType, provider_id: str
) -> list[SymbolSuggestion]:
    try:
        results = await provider.search_symbols(query)
    except Exception:  # noqa: BLE001 — any provider failure must not sink combined search
        return []
    return [SymbolSuggestion(**r, asset_type=asset_type, provider=provider_id) for r in results]


def _interleave(*lists: list) -> list:
    """Round-robin merge so one source's larger result count (typically
    stocks) doesn't crowd the others out of a capped combined list."""
    out = []
    for group in itertools.zip_longest(*lists):
        out.extend(item for item in group if item is not None)
    return out


def _rank_suggestions(items: list[SymbolSuggestion], query: str) -> list[SymbolSuggestion]:
    """Sort by match quality: exact symbol first, then prefix, then rest."""
    q = query.upper()
    def _score(s: SymbolSuggestion) -> int:
        sym = s.symbol.upper()
        if sym == q:
            return 0
        if sym.startswith(q):
            return 1
        return 2
    return sorted(items, key=_score)


@app.get("/api/symbols", response_model=list[SymbolSuggestion])
async def search_symbols(query: str = Query(..., min_length=1, max_length=20)) -> list[SymbolSuggestion]:
    # Single unified search across stocks and both crypto exchanges — no
    # upfront "stock vs crypto" toggle. The user picks the asset from results
    # that already say which market/exchange it's on.
    stock_res, mexc_res, kucoin_res, binance_res, kraken_res = await asyncio.gather(
        _safe_search(twelvedata_provider, query, "stock", "stock")
        if settings.stocks_enabled else _no_results(),
        _safe_search(mexc_provider, query, "crypto", "mexc"),
        _safe_search(kucoin_provider, query, "crypto", "kucoin"),
        _safe_search(binance_provider, query, "crypto", "binance"),
        _safe_search(kraken_provider, query, "crypto", "kraken"),
    )
    merged = _interleave(stock_res, mexc_res, kucoin_res, binance_res, kraken_res)
    return _rank_suggestions(merged, query)[:25]


def _dispatch_telegram_alerts(
    chat_id: str,
    symbol: str,
    interval: str,
    strategy: StrategyState,
    frequency: str = "every",
    entry_id: str = "",
    owner_id: str = "",
) -> list[StrategySignal]:
    """Manda le notifiche e RESTITUISCE i segnali che le hanno generate.

    Restituirli non e' una comodita': find_new_signals consuma lo stato di
    deduplica, quindi una seconda chiamata sugli stessi segnali torna vuota.
    Chi deve agire su quei segnali — l'esecuzione automatica degli ordini —
    deve ricevere questi, non richiederli.
    """
    fresh = find_new_signals(symbol, interval, strategy, frequency=frequency, entry_id=entry_id)
    for signal in fresh:
        message = format_signal_message(symbol, interval, strategy.name, signal)
        asyncio.create_task(telegram.send_to(chat_id, message))
        if owner_id:
            alert_log.append_entry(
                owner_id=owner_id,
                symbol=symbol,
                interval=interval,
                strategy_name=strategy.name,
                signal_type=signal.type,
                price=signal.price,
                label=signal.label,
                chat_id=chat_id,
            )
        if entry_id:
            record_alert_sent(entry_id, strategy.name)
    return fresh


@app.get("/api/strategies", response_model=list[str])
async def list_strategies() -> list[str]:
    return AVAILABLE_STRATEGIES


class PineParamOut(BaseModel):
    var_name: str
    kind: str
    default: object
    title: str
    minval: float | None = None
    maxval: float | None = None


class PineUploadRequest(BaseModel):
    name: str
    source: str


class PineScriptOut(BaseModel):
    id: str
    name: str
    created_at: int
    params: list[PineParamOut]
    is_strategy_style: bool


def _parse_pine_or_400(source: str) -> tuple[list, list[PineParamOut], bool]:
    try:
        stmts = parse_program(source)
        params = scan_inputs(stmts)
        strategy_style = is_strategy_style(stmts)
    except PineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    params_out = [
        PineParamOut(var_name=p.var_name, kind=p.kind, default=p.default, title=p.title, minval=p.minval, maxval=p.maxval)
        for p in params
    ]
    return stmts, params_out, strategy_style


@app.post("/api/pinescript", response_model=PineScriptOut)
async def upload_pinescript(req: PineUploadRequest) -> PineScriptOut:
    name = req.name.strip() or "Script senza nome"
    _stmts, params_out, strategy_style = _parse_pine_or_400(req.source)
    default_params = {p.var_name: p.default for p in params_out}
    meta = pine_storage.save_script(name, req.source, default_params)
    return PineScriptOut(
        id=meta["id"], name=meta["name"], created_at=meta["created_at"], params=params_out, is_strategy_style=strategy_style
    )


@app.get("/api/pinescript", response_model=list[PineScriptOut])
async def list_pinescripts() -> list[PineScriptOut]:
    out = []
    for meta in pine_storage.list_scripts():
        loaded = pine_storage.load_script(meta["id"])
        if loaded is None:
            continue
        _, source = loaded
        try:
            _stmts, params_out, strategy_style = _parse_pine_or_400(source)
        except HTTPException:
            continue
        out.append(
            PineScriptOut(
                id=meta["id"], name=meta["name"], created_at=meta["created_at"], params=params_out, is_strategy_style=strategy_style
            )
        )
    return out


@app.get("/api/pinescript/{script_id}")
async def get_pinescript(script_id: str) -> dict:
    loaded = pine_storage.load_script(script_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="Script non trovato")
    meta, source = loaded
    _stmts, params_out, strategy_style = _parse_pine_or_400(source)
    return {
        "id": meta["id"],
        "name": meta["name"],
        "created_at": meta["created_at"],
        "source": source,
        "params": [p.model_dump() for p in params_out],
        "is_strategy_style": strategy_style,
    }


@app.delete("/api/pinescript/{script_id}")
async def delete_pinescript(script_id: str) -> dict:
    if not pine_storage.delete_script(script_id):
        raise HTTPException(status_code=404, detail="Script non trovato")
    return {"ok": True}


class PineRunRequest(BaseModel):
    symbol: str
    asset_type: AssetType
    exchange: CryptoExchange = "mexc"
    timeframe: TimeframeKey = "mtf"
    interval: IntervalChoice | None = None
    params: dict = {}
    signal_map: dict[str, str] | None = None
    backtest_params: BacktestParamsQuery = BacktestParamsQuery()


@app.post("/api/pinescript/{script_id}/run")
async def run_pinescript(script_id: str, req: PineRunRequest) -> dict:
    loaded = pine_storage.load_script(script_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="Script non trovato")
    _meta, source = loaded
    stmts, params_out, strategy_style = _parse_pine_or_400(source)

    symbol = req.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    interval = req.interval or DEFAULT_INTERVALS[req.timeframe]
    provider = get_provider(req.asset_type, req.exchange)

    try:
        df = await _fetch_cached(
            (f"pine:{req.asset_type}:{req.exchange}:{symbol.upper()}", interval, settings.ltf_candles),
            provider, symbol, interval, settings.ltf_candles,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if df.empty:
        raise HTTPException(status_code=502, detail=f"Nessun dato per {symbol} su {interval}")

    merged_params = {p.var_name: p.default for p in params_out}
    merged_params.update(req.params or {})

    try:
        interp = PineInterpreter(df, params=merged_params, signal_map=req.signal_map)
        signals = interp.run(stmts)
    except PineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not strategy_style:
        # Only entry_long/entry_short are mandatory — plenty of indicator
        # scripts (RSI/BB reversal setups included) only ever define entry
        # conditions and rely on the opposite signal to flip the position,
        # exactly like our own built-in strategies. Requiring an explicit
        # exit mapping that doesn't exist in the script would leave a
        # perfectly usable script stuck asking for mapping forever.
        required_roles = {"entry_long", "entry_short"}
        mapped = set((req.signal_map or {}).keys())
        if not required_roles.issubset(mapped):
            return {
                "needs_mapping": True,
                "candidates": interp.boolean_candidates(),
                "warning": (
                    "Questo script non usa strategy.entry/close: seleziona quali variabili booleane "
                    "corrispondono a entry_long / entry_short (exit_long / exit_short sono opzionali — "
                    "se non li mappi, la posizione resta aperta fino al segnale opposto)."
                ),
            }

    strategy = build_strategy_state(f"Script: {_meta['name']}", df, signals=signals)
    backtest = run_backtest(df, None, req.backtest_params.model_dump(), signals=signals)
    return {"needs_mapping": False, "strategy": strategy.model_dump(), "backtest": backtest.model_dump()}


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TelegramChatIdRequest(BaseModel):
    telegram_chat_id: str


def _user_out(user: User) -> dict:
    return {"id": user.id, "email": user.email, "telegram_chat_id": user.telegram_chat_id}


def _client_ip(request: Request) -> str:
    # Fly's edge proxy sets this; request.client.host would otherwise be
    # the internal proxy address, not the real caller.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_https(request: Request) -> bool:
    # Read the header directly rather than trusting uvicorn's own
    # proxy-header handling (which needs explicit --forwarded-allow-ips
    # config to kick in) — Fly's proxy always sets this correctly.
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    return forwarded_proto == "https" if forwarded_proto else request.url.scheme == "https"


def _set_session_cookie(response: Response, user_id: str, request: Request) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.make_session_cookie(user_id),
        max_age=auth.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )


@app.post("/api/auth/register")
async def register(req: RegisterRequest, request: Request, response: Response) -> dict:
    ip_key = f"register:{_client_ip(request)}"
    if rate_limit.is_locked(ip_key):
        raise HTTPException(status_code=429, detail="Troppi tentativi. Riprova tra qualche minuto.")

    email = req.email.strip().lower()
    if "@" not in email or len(email) < 5:
        rate_limit.register_failure(ip_key)
        raise HTTPException(status_code=400, detail="Email non valida")

    consentite = {e.strip().lower() for e in settings.registration_allowed_emails.split(",") if e.strip()}
    if consentite and email not in consentite:
        rate_limit.register_failure(ip_key)
        # Stesso messaggio che si da' a un'email gia' presente: due risposte
        # diverse direbbero a un estraneo quali indirizzi esistono.
        raise HTTPException(status_code=403, detail="Registrazione non consentita per questo indirizzo")
    if not auth.is_strong_password(req.password):
        rate_limit.register_failure(ip_key)
        raise HTTPException(
            status_code=400,
            detail="La password deve avere almeno 8 caratteri, con lettere e numeri, e non essere troppo comune",
        )
    if auth.find_by_email(email):
        rate_limit.register_failure(ip_key)
        raise HTTPException(status_code=400, detail="Email già registrata")

    user = auth.create_user(email, req.password)
    rate_limit.register_success(ip_key)
    _set_session_cookie(response, user.id, request)
    return _user_out(user)


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request, response: Response) -> dict:
    email = req.email.strip().lower()
    ip_key = f"ip:{_client_ip(request)}"
    email_key = f"email:{email}"
    if rate_limit.is_locked(ip_key) or rate_limit.is_locked(email_key):
        raise HTTPException(status_code=429, detail="Troppi tentativi falliti. Riprova tra qualche minuto.")

    user = auth.verify_login(email, req.password)
    if user is None:
        rate_limit.register_failure(ip_key)
        rate_limit.register_failure(email_key)
        raise HTTPException(status_code=401, detail="Email o password errati")

    rate_limit.register_success(ip_key)
    rate_limit.register_success(email_key)
    _set_session_cookie(response, user.id, request)
    return _user_out(user)


@app.post("/api/auth/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
async def me(user: User | None = Depends(auth.get_current_user_optional)) -> dict:
    return {"user": _user_out(user) if user else None}


@app.patch("/api/auth/telegram")
async def update_telegram_chat_id(
    req: TelegramChatIdRequest, user: User = Depends(auth.get_current_user)
) -> dict:
    updated = auth.set_telegram_chat_id(user.id, req.telegram_chat_id)
    if updated.telegram_chat_id and _telegram_allowed(updated):
        # Confirms the chat_id was actually saved and is reachable — sent
        # immediately on save, not the first real alert, so a typo'd id
        # shows up right away instead of silently going nowhere.
        asyncio.create_task(
            telegram.send_to(
                updated.telegram_chat_id,
                "✅ Chat ID collegato correttamente a Liquidity Analysis Engine.\n"
                "Da qui in poi riceverai qui gli avvisi delle strategie che attivi.",
            )
        )
    return _user_out(updated)


@app.get("/api/auth/trading", response_model=list[TradingCredentialOut])
async def get_trading_credentials(user: User = Depends(auth.get_current_user)) -> list[TradingCredentialOut]:
    out = []
    for exchange in ("binance", "mexc", "kucoin", "kraken", "coinbase", "bitstamp"):
        cred = user.trading_credentials.get(exchange)
        if cred is None:
            out.append(TradingCredentialOut(exchange=exchange, api_key_set=False, api_secret_set=False, passphrase_set=False, enabled=False, size_mode="fixed_usdt", size_value=50.0))
        else:
            out.append(TradingCredentialOut(
                exchange=exchange,
                api_key_set=bool(cred.api_key_enc),
                api_secret_set=bool(cred.api_secret_enc),
                passphrase_set=bool(cred.passphrase_enc),
                enabled=cred.enabled,
                size_mode=cred.size_mode,
                size_value=cred.size_value,
            ))
    return out


@app.patch("/api/auth/trading")
async def set_trading_credential(body: TradingCredentialRequest, user: User = Depends(auth.get_current_user)):
    supported = {"binance", "mexc", "kucoin", "kraken", "coinbase", "bitstamp"}
    if body.exchange not in supported:
        raise HTTPException(status_code=400, detail=f"Exchange non supportato: {body.exchange}")
    auth.set_trading_credential(
        user.id, body.exchange, body.api_key, body.api_secret, body.passphrase,
        body.enabled, body.size_mode, body.size_value,
    )
    return {"ok": True}


class ManualOrderRequest(BaseModel):
    exchange: str
    symbol: str
    side: Literal["BUY", "SELL"]
    size_mode: Literal["fixed_usdt", "pct_balance"] = "fixed_usdt"
    size_value: float


@app.post("/api/trading/order")
async def place_manual_order(body: ManualOrderRequest, user: User = Depends(auth.get_current_user)):
    supported = {"binance", "mexc", "kucoin", "kraken", "coinbase", "bitstamp"}
    if body.exchange not in supported:
        raise HTTPException(status_code=400, detail=f"Exchange non supportato: {body.exchange}")
    cred = user.trading_credentials.get(body.exchange)
    if not cred:
        raise HTTPException(status_code=400, detail="Credenziali non configurate per questo exchange")
    api_key, api_secret, passphrase = auth.get_decrypted_credential(user, body.exchange)
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="API key o secret mancanti — configurali prima nella sezione Trading automatico")

    # Il pair si verifica prima di mandare l'ordine, dove abbiamo un provider
    # per quell'exchange. Scriverlo a mano e' l'unico modo che c'e' di
    # indicarlo, e un pair inesistente o quotato altrove tornava indietro come
    # errore dell'exchange — cioe' dopo aver provato a comprare qualcosa. Un
    # controllo qui costa una chiamata e dice il nome esatto atteso.
    symbol = body.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Pair mancante")
    if body.exchange in ("mexc", "binance", "kucoin"):
        symbol = canonical_symbol(symbol, "crypto", body.exchange)
        provider = get_provider("crypto", body.exchange)
        try:
            probe = await provider.fetch_ohlcv(symbol, "1d", 2)
        except ProviderError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Pair {symbol} non trovato su {body.exchange}: {exc}",
            ) from exc
        if probe.empty:
            raise HTTPException(
                status_code=400,
                detail=f"Pair {symbol} non trovato su {body.exchange}. Controlla il nome esatto "
                       "(es. BTCUSDT) e che sia quotato su questo exchange.",
            )

    from app.models import StrategySignal
    signal_type = "entry_long" if body.side == "BUY" else "entry_short"
    fake_signal = StrategySignal(time=int(_time.time()), type=signal_type, price=0.0, label="manual")
    try:
        result = await place_order_for_signal(
            body.exchange, symbol, fake_signal,
            body.size_mode, body.size_value,
            api_key, api_secret, passphrase,
        )
    except RuntimeError as exc:
        # Anche un ordine manuale va nel diario. Era l'unico percorso che non
        # ci finiva, ed e' esattamente quello su cui e' arrivata la
        # segnalazione: il fallimento viveva solo nel riquadro di stato, che
        # sparisce ricaricando la pagina.
        trading_log.record(
            user.id, symbol=symbol, exchange=body.exchange,
            strategy_name="manuale", signal_type=signal_type,
            outcome="fallito", detail=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    trading_log.record(
        user.id, symbol=symbol, exchange=body.exchange,
        strategy_name="manuale", signal_type=signal_type,
        outcome="eseguito", detail=str(result)[:400],
    )
    return {"ok": True, "result": result, "symbol": symbol}


@app.get("/api/auth/futures", response_model=list[FuturesCredentialOut])
async def get_futures_credentials(user: User = Depends(auth.get_current_user)) -> list[FuturesCredentialOut]:
    out = []
    for exchange in SUPPORTED_FUTURES_EXCHANGES_ORDERED:
        adapter = futures_registry.get(exchange)
        cred = user.futures_credentials.get(exchange)
        common = dict(
            exchange=exchange, name=adapter.name, needs_passphrase=adapter.needs_passphrase,
            # Il tetto vero e' il piu' basso fra i due: il frontend non deve
            # mai mostrare uno slider che arriva piu' in alto di quanto il
            # server accetterebbe davvero (vedi i controlli su MAX_FUTURES_LEVERAGE
            # in questo stesso file e in auth.set_futures_credential).
            max_leverage=min(MAX_FUTURES_LEVERAGE, adapter.max_leverage),
            isolated_margin=adapter.isolated_margin,
            key_hint=adapter.key_hint,
        )
        if cred is None:
            out.append(FuturesCredentialOut(
                **common, api_key_set=False, api_secret_set=False, passphrase_set=False,
                enabled=False, size_mode="fixed_usdt", size_value=50.0, leverage=1,
            ))
        else:
            out.append(FuturesCredentialOut(
                **common, api_key_set=bool(cred.api_key_enc), api_secret_set=bool(cred.api_secret_enc),
                passphrase_set=bool(cred.passphrase_enc),
                enabled=cred.enabled, size_mode=cred.size_mode, size_value=cred.size_value, leverage=cred.leverage,
            ))
    return out


@app.patch("/api/auth/futures")
async def set_futures_credential_endpoint(body: FuturesCredentialRequest, user: User = Depends(auth.get_current_user)):
    if body.exchange not in SUPPORTED_FUTURES_EXCHANGES_ORDERED:
        raise HTTPException(status_code=400, detail=f"Futures non ancora supportati per questo exchange: {body.exchange}")
    adapter = futures_registry.get(body.exchange)
    existing_cred = user.futures_credentials.get(body.exchange)
    has_passphrase = bool(body.passphrase) or bool(existing_cred and existing_cred.passphrase_enc)
    if adapter.needs_passphrase and not has_passphrase:
        raise HTTPException(status_code=400, detail=f"{adapter.name} richiede una passphrase oltre a chiave e secret")
    # Il tetto e' quello di questo exchange, non il massimo globale: un
    # cursore che arriva a 10x su un adattatore che ne sopporta solo 5 deve
    # fermarsi prima di raggiungere il server, ma il server e' l'ultima
    # parola in ogni caso.
    max_lev = min(MAX_FUTURES_LEVERAGE, adapter.max_leverage)
    if not (1 <= body.leverage <= max_lev):
        raise HTTPException(status_code=400, detail=f"Leva {body.leverage}x fuori dal limite di {adapter.name} (1-{max_lev}x)")
    try:
        auth.set_futures_credential(
            user.id, body.exchange, body.api_key, body.api_secret,
            body.enabled, body.size_mode, body.size_value, body.leverage,
            passphrase=body.passphrase,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


class FuturesQuoteRequest(BaseModel):
    exchange: str
    symbol: str
    side: Literal["BUY", "SELL"]
    size_mode: Literal["fixed_usdt", "pct_balance"] = "fixed_usdt"
    size_value: float
    leverage: int = 1


@app.get("/api/trading/futures/positions")
async def list_futures_positions(user: User = Depends(auth.get_current_user)):
    """Sola lettura: le posizioni a leva aperte, con la distanza dalla
    liquidazione gia' calcolata. Non puo' in nessun caso inviare un ordine —
    per questo non chiede conferma e non tocca l'executor."""
    out: list[dict] = []
    for exchange in SUPPORTED_FUTURES_EXCHANGES_ORDERED:
        cred = user.futures_credentials.get(exchange)
        if not cred:
            continue
        api_key, api_secret, passphrase = auth.get_decrypted_futures_credential(user, exchange)
        if not api_key or not api_secret:
            continue
        adapter = futures_registry.get(exchange)
        creds = FuturesCreds(api_key=api_key, api_secret=api_secret, passphrase=passphrase)
        try:
            positions = await adapter.open_positions(creds)
        except FuturesExecutionError:
            # Un exchange che non risponde non deve nascondere gli altri.
            continue
        out.extend(p.as_dict() for p in positions)
    return out


@app.post("/api/trading/futures/quote")
async def quote_futures_order(body: FuturesQuoteRequest, user: User = Depends(auth.get_current_user)):
    """Anteprima obbligatoria prima di un ordine futures manuale: leva,
    margine impegnato e prezzo di liquidazione stimato — mai un click
    singolo come per lo spot (vedi il piano "Operazioni futures", Fase 4)."""
    if body.exchange not in SUPPORTED_FUTURES_EXCHANGES_ORDERED:
        raise HTTPException(status_code=400, detail=f"Futures non ancora supportati per questo exchange: {body.exchange}")
    cred = user.futures_credentials.get(body.exchange)
    if not cred:
        raise HTTPException(status_code=400, detail="Credenziali futures non configurate per questo exchange")
    api_key, api_secret, passphrase = auth.get_decrypted_futures_credential(user, body.exchange)
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="API key o secret mancanti")
    adapter = futures_registry.get(body.exchange)
    if adapter.needs_passphrase and not passphrase:
        raise HTTPException(status_code=400, detail=f"{adapter.name} richiede una passphrase, non ancora salvata")
    max_lev = min(MAX_FUTURES_LEVERAGE, adapter.max_leverage)
    if not (1 <= body.leverage <= max_lev):
        raise HTTPException(status_code=400, detail=f"Leva {body.leverage}x fuori dal limite di {adapter.name} (1-{max_lev}x)")

    symbol = body.symbol.strip().upper()
    creds = FuturesCreds(api_key=api_key, api_secret=api_secret, passphrase=passphrase)
    try:
        mark = await adapter.mark_price(symbol, creds)
        available = await adapter.available_margin(creds)
    except FuturesExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    margin_used = body.size_value if body.size_mode == "fixed_usdt" else available * body.size_value / 100
    direction = "long" if body.side == "BUY" else "short"
    # Kraken non ha isolated margin: la liquidazione qui e' comunque
    # calcolata come se lo fosse, perche' e' il numero che dice quanto puo'
    # muoversi il prezzo, ma senza isolated la perdita puo' non fermarsi li'
    # — per questo l'anteprima porta anche `isolated_margin`.
    liq_price = liquidation_price(mark, direction, body.leverage, DEFAULT_MAINTENANCE_MARGIN_RATE)
    sufficient = margin_used <= available
    return {
        "symbol": symbol, "mark_price": mark, "leverage": body.leverage,
        "margin_used": margin_used, "notional": margin_used * body.leverage,
        "liquidation_price": liq_price, "available_margin": available,
        "margin_sufficient": sufficient, "isolated_margin": adapter.isolated_margin,
    }


class FuturesOrderRequest(BaseModel):
    exchange: str
    symbol: str
    side: Literal["BUY", "SELL"]
    size_mode: Literal["fixed_usdt", "pct_balance"] = "fixed_usdt"
    size_value: float
    leverage: int = 1
    confirm: bool = False  # deve essere vero: nessun ordine futures parte senza conferma esplicita


@app.post("/api/trading/futures/order")
async def place_manual_futures_order(body: FuturesOrderRequest, user: User = Depends(auth.get_current_user)):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma richiesta: mostra prima l'anteprima (/api/trading/futures/quote)")
    if body.exchange not in SUPPORTED_FUTURES_EXCHANGES_ORDERED:
        raise HTTPException(status_code=400, detail=f"Futures non ancora supportati per questo exchange: {body.exchange}")
    cred = user.futures_credentials.get(body.exchange)
    if not cred:
        raise HTTPException(status_code=400, detail="Credenziali futures non configurate per questo exchange")
    if not cred.enabled:
        # Kill switch: spegnibile senza toccare le chiavi — vale anche per
        # l'ordine manuale, non solo per l'esecuzione automatica.
        raise HTTPException(status_code=400, detail="Esecuzione futures disattivata per questo exchange")
    api_key, api_secret, passphrase = auth.get_decrypted_futures_credential(user, body.exchange)
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="API key o secret mancanti")
    adapter = futures_registry.get(body.exchange)
    if adapter.needs_passphrase and not passphrase:
        raise HTTPException(status_code=400, detail=f"{adapter.name} richiede una passphrase, non ancora salvata")
    max_lev = min(MAX_FUTURES_LEVERAGE, adapter.max_leverage)
    if not (1 <= body.leverage <= max_lev):
        raise HTTPException(status_code=400, detail=f"Leva {body.leverage}x fuori dal limite di {adapter.name} (1-{max_lev}x)")

    symbol = body.symbol.strip().upper()
    creds = FuturesCreds(api_key=api_key, api_secret=api_secret, passphrase=passphrase)

    # Controllo pre-trade del margine disponibile: letto per davvero
    # dall'exchange, non dalla cache.
    try:
        available = await adapter.available_margin(creds)
    except FuturesExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    margin_needed = body.size_value if body.size_mode == "fixed_usdt" else available * body.size_value / 100
    if margin_needed > available:
        raise HTTPException(
            status_code=400,
            detail=f"Margine insufficiente: servono {margin_needed:.2f} USDT, disponibili {available:.2f} USDT",
        )

    from app.models import StrategySignal
    signal_type = "entry_long" if body.side == "BUY" else "entry_short"
    fake_signal = StrategySignal(time=int(_time.time()), type=signal_type, price=0.0, label="manual")
    detail_prefix = f"leva {body.leverage}x — "
    try:
        result = await place_futures_order_for_signal(
            body.exchange, symbol, fake_signal,
            body.size_mode, body.size_value, body.leverage,
            api_key, api_secret, passphrase=passphrase,
        )
    except RuntimeError as exc:
        trading_log.record(
            user.id, symbol=symbol, exchange=body.exchange,
            strategy_name="manuale futures", signal_type=signal_type,
            outcome="fallito", detail=detail_prefix + str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    trading_log.record(
        user.id, symbol=symbol, exchange=body.exchange,
        strategy_name="manuale futures", signal_type=signal_type,
        outcome="eseguito", detail=(detail_prefix + str(result))[:400],
    )
    return {"ok": True, "result": result, "symbol": symbol}


@app.get("/api/balances")
async def get_balances(user: User = Depends(auth.get_current_user)) -> dict:
    if not _balance_visible(user):
        raise HTTPException(status_code=403, detail="Non disponibile per questo account")

    async def _safe(fetch_fn, configured: bool):
        if not configured:
            return {"configured": False, "balances": [], "error": None}
        try:
            balances = await fetch_fn()
            return {"configured": True, "balances": balances, "error": None}
        except BalanceFetchError as exc:
            return {"configured": True, "balances": [], "error": str(exc)}

    mexc, kucoin = await asyncio.gather(
        _safe(fetch_mexc_balances, bool(settings.mexc_api_key and settings.mexc_api_secret)),
        _safe(
            fetch_kucoin_balances,
            bool(settings.kucoin_api_key and settings.kucoin_api_secret and settings.kucoin_api_passphrase),
        ),
    )
    return {"mexc": mexc, "kucoin": kucoin}


def _owned_entry_or_404(entry_id: str, user: User) -> WatchlistEntry:
    entry = watchlist_store.get_entry(entry_id)
    if entry is None or entry.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Voce non trovata")
    return entry


@app.get("/api/preferences")
async def get_preferences(user: User = Depends(auth.get_current_user)) -> dict:
    return user.preferences or {}


@app.put("/api/preferences")
async def put_preferences(
    body: dict,
    user: User = Depends(auth.get_current_user),
) -> dict:
    # Allowlist the keys we actually care about — ignore anything unknown
    allowed = {"ticker", "asset_type", "exchange", "interval", "strategy", "strategy_params",
               "layers", "log_scale", "lab_ticker", "lab_asset_type", "lab_exchange", "lab_interval",
               "theme"}
    filtered = {k: v for k, v in body.items() if k in allowed}
    auth.set_preferences(user.id, filtered)
    return filtered


@app.get("/api/watchlist", response_model=list[WatchlistEntry])
async def get_watchlist(user: User = Depends(auth.get_current_user)) -> list[WatchlistEntry]:
    return watchlist_store.list_entries(owner_id=user.id)


class WatchlistAddRequest(BaseModel):
    symbol: str
    asset_type: AssetType
    exchange: CryptoExchange = "mexc"
    interval: IntervalChoice = "1d"
    on_close: bool = True


@app.post("/api/watchlist", response_model=WatchlistEntry)
async def add_watchlist_entry(
    req: WatchlistAddRequest, user: User = Depends(auth.get_current_user)
) -> WatchlistEntry:
    symbol = req.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")

    # Re-verify the pair actually resolves on this exchange before storing
    # it — the frontend already confirms this via the suggestions list, but
    # a symbol could still be typed/submitted without going through it, or
    # get delisted between being suggested and being added.
    provider = get_provider(req.asset_type, req.exchange)
    try:
        probe = await provider.fetch_ohlcv(symbol, "1d", 2)
    except ProviderError as exc:
        raise HTTPException(
            status_code=400, detail=f"Ticker non trovato su questo exchange: {exc}"
        ) from exc
    if probe.empty:
        raise HTTPException(status_code=400, detail="Ticker non trovato su questo exchange.")

    return watchlist_store.add_entry(
        user.id, symbol, req.asset_type, exchange=req.exchange, interval=req.interval, on_close=req.on_close
    )


class WatchlistIntervalRequest(BaseModel):
    interval: IntervalChoice


@app.patch("/api/watchlist/{entry_id}/interval", response_model=WatchlistEntry)
async def set_watchlist_interval(
    entry_id: str, req: WatchlistIntervalRequest, user: User = Depends(auth.get_current_user)
) -> WatchlistEntry:
    _owned_entry_or_404(entry_id, user)
    return watchlist_store.set_interval(entry_id, req.interval)


@app.delete("/api/watchlist/{entry_id}")
async def delete_watchlist_entry(entry_id: str, user: User = Depends(auth.get_current_user)) -> dict:
    _owned_entry_or_404(entry_id, user)
    watchlist_store.remove_entry(entry_id)
    return {"ok": True}


class WatchlistStrategyToggleRequest(BaseModel):
    strategy_name: str
    enabled: bool


@app.patch("/api/watchlist/{entry_id}/strategy", response_model=WatchlistEntry)
async def toggle_watchlist_strategy(
    entry_id: str, req: WatchlistStrategyToggleRequest, user: User = Depends(auth.get_current_user)
) -> WatchlistEntry:
    if req.strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {req.strategy_name}")
    before = _owned_entry_or_404(entry_id, user)
    was_enabled = req.strategy_name in before.strategies
    entry = watchlist_store.set_strategy_enabled(entry_id, req.strategy_name, req.enabled)
    if was_enabled and not req.enabled:
        # Spegnendo l'alert si dimentica da quando era armato: riaccendendolo
        # deve ripartire da adesso, non dalla prima attivazione — altrimenti
        # tutto quello che e' successo nel frattempo arriverebbe in blocco.
        alerts.disarm(entry_id, req.strategy_name)
    if req.enabled and not was_enabled:
        # Fotografia della configurazione con cui l'alert parte. E' il momento
        # in cui smette di essere un esperimento: da qui lavora per settimane,
        # e il risultato dell'ottimizzazione che l'ha prodotta vive quanto la
        # scheda del browser. Spegnere e riaccendere non duplica la voce; una
        # riattivazione con parametri diversi si', perche' e' un'altra strategia.
        params = entry.strategy_params.get(req.strategy_name, {}) or {}
        if not archive_store.already_archived(user.id, entry_id, req.strategy_name, params):
            snapshot = archive_store.create(
                owner_id=user.id, symbol=entry.symbol, asset_type=entry.asset_type,
                exchange=entry.exchange,
                interval=entry.strategy_intervals.get(req.strategy_name, entry.interval),
                strategy_name=req.strategy_name, params=params,
                backtest_params={}, source="alert", watchlist_entry_id=entry_id,
            )
            asyncio.create_task(_run_archive_backtest(
                snapshot["id"], entry.symbol, entry.asset_type, entry.exchange,
                snapshot["interval"], req.strategy_name, params, {},
            ))

    if req.enabled and not was_enabled and user.telegram_chat_id and _telegram_allowed(user):
        # Confirms the watch is actually active — sent immediately on
        # activation, before any real signal, so silence afterward reads as
        # "no condition yet" rather than "is this even running?".
        asyncio.create_task(
            telegram.send_to(
                user.telegram_chat_id,
                f"✅ <b>{entry.symbol}</b> — {req.strategy_name}\n"
                f"Timeframe: {entry.interval}\n"
                "Monitoraggio attivato. Riceverai un messaggio quando viene rilevata una condizione.",
            )
        )
    return entry


class WatchlistOnCloseRequest(BaseModel):
    on_close: bool


@app.patch("/api/watchlist/{entry_id}/on_close", response_model=WatchlistEntry)
async def set_watchlist_on_close(
    entry_id: str, req: WatchlistOnCloseRequest, user: User = Depends(auth.get_current_user)
) -> WatchlistEntry:
    _owned_entry_or_404(entry_id, user)
    return watchlist_store.set_on_close(entry_id, req.on_close)


class WatchlistStrategyParamsRequest(BaseModel):
    strategy_name: str
    params: dict = {}  # {} resets this strategy back to its global defaults


@app.patch("/api/watchlist/{entry_id}/strategy_params", response_model=WatchlistEntry)
async def set_watchlist_strategy_params(
    entry_id: str, req: WatchlistStrategyParamsRequest, user: User = Depends(auth.get_current_user)
) -> WatchlistEntry:
    if req.strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {req.strategy_name}")
    _owned_entry_or_404(entry_id, user)
    return watchlist_store.set_strategy_params(entry_id, req.strategy_name, req.params)


class WatchlistFrequencyRequest(BaseModel):
    strategy_name: str
    frequency: Literal["once", "every"]


@app.patch("/api/watchlist/{entry_id}/alert_frequency", response_model=WatchlistEntry)
async def set_watchlist_alert_frequency(
    entry_id: str, req: WatchlistFrequencyRequest, user: User = Depends(auth.get_current_user)
) -> WatchlistEntry:
    _owned_entry_or_404(entry_id, user)
    return watchlist_store.set_alert_frequency(entry_id, req.strategy_name, req.frequency)


class WatchlistAutoTradeRequest(BaseModel):
    strategy_name: str
    enabled: bool


@app.patch("/api/watchlist/{entry_id}/auto_trade", response_model=WatchlistEntry)
async def set_watchlist_auto_trade(
    entry_id: str, req: WatchlistAutoTradeRequest, user: User = Depends(auth.get_current_user)
) -> WatchlistEntry:
    if req.strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {req.strategy_name}")
    _owned_entry_or_404(entry_id, user)
    return watchlist_store.set_auto_trade(entry_id, req.strategy_name, req.enabled)


class WatchlistStrategyIntervalRequest(BaseModel):
    strategy_name: str
    interval: str | None = None  # None resets to entry default


@app.patch("/api/watchlist/{entry_id}/strategy_interval", response_model=WatchlistEntry)
async def set_watchlist_strategy_interval(
    entry_id: str, req: WatchlistStrategyIntervalRequest, user: User = Depends(auth.get_current_user)
) -> WatchlistEntry:
    _owned_entry_or_404(entry_id, user)
    return watchlist_store.set_strategy_interval(entry_id, req.strategy_name, req.interval)


@app.get("/api/watchlist/{entry_id}/stats")
async def get_watchlist_entry_stats(
    entry_id: str, user: User = Depends(auth.get_current_user)
) -> dict:
    _owned_entry_or_404(entry_id, user)
    return get_all_stats_for_entry(entry_id)


@app.post("/api/watchlist/{entry_id}/test-alert")
async def test_watchlist_alert(
    entry_id: str,
    body: dict,
    user: User = Depends(auth.get_current_user),
) -> dict:
    """Fetch current candles, run the strategy, send the most recent signal as a test."""
    strategy_name = body.get("strategy_name", "")
    if strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {strategy_name}")
    entry = _owned_entry_or_404(entry_id, user)
    if not user.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Nessun Telegram chat_id configurato")
    provider = get_provider(entry.asset_type, entry.exchange)
    interval = entry.strategy_intervals.get(strategy_name, entry.interval)
    try:
        df = await fetch_ohlcv_canonical(provider, entry.symbol, interval, settings.candles_per_timeframe)
        if entry.on_close:
            df = drop_unclosed_candle(df, interval)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if df.empty:
        raise HTTPException(status_code=502, detail="Nessun dato disponibile")
    params = entry.strategy_params.get(strategy_name) or None
    strategy = build_strategy_state(strategy_name, df, params=params)
    if not strategy.signals:
        return {"sent": False, "signal": None}
    signal = strategy.signals[-1]
    msg = f"🧪 TEST — {format_signal_message(entry.symbol, interval, strategy_name, signal)}"
    asyncio.create_task(telegram.send_to(user.telegram_chat_id, msg))
    return {"sent": True, "signal": signal.type}


# ── Alert log ──────────────────────────────────────────────────────────────────

@app.get("/api/alerts/log")
async def get_alert_log(
    limit: int = 100,
    since: int = 0,
    user: User = Depends(auth.get_current_user),
) -> list:
    return alert_log.list_entries(user.id, limit=limit, since=since)


@app.delete("/api/alerts/log")
async def clear_alert_log(user: User = Depends(auth.get_current_user)) -> dict:
    alert_log.clear(user.id)
    return {"ok": True}


# ── Price alerts ───────────────────────────────────────────────────────────────

class PriceAlertCreateRequest(BaseModel):
    symbol: str
    asset_type: AssetType
    exchange: CryptoExchange = "mexc"
    condition: PriceAlertCondition
    price: float
    note: str = ""
    once_only: bool = True


@app.get("/api/price-alerts", response_model=list[PriceAlert])
async def list_price_alerts(user: User = Depends(auth.get_current_user)) -> list[PriceAlert]:
    return price_alerts_store.list_alerts(user.id)


@app.post("/api/price-alerts", response_model=PriceAlert)
async def create_price_alert(
    req: PriceAlertCreateRequest, user: User = Depends(auth.get_current_user)
) -> PriceAlert:
    symbol = req.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    return price_alerts_store.add_alert(
        user.id, symbol, req.asset_type, req.exchange,
        req.condition, req.price, req.note, req.once_only,
    )


@app.delete("/api/price-alerts/{alert_id}")
async def delete_price_alert(alert_id: str, user: User = Depends(auth.get_current_user)) -> dict:
    a = price_alerts_store.get_alert(alert_id)
    if a is None or a.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Alert non trovato")
    price_alerts_store.remove_alert(alert_id)
    return {"ok": True}


class PriceAlertActiveRequest(BaseModel):
    active: bool


@app.patch("/api/price-alerts/{alert_id}/active", response_model=PriceAlert)
async def set_price_alert_active(
    alert_id: str, req: PriceAlertActiveRequest, user: User = Depends(auth.get_current_user)
) -> PriceAlert:
    a = price_alerts_store.get_alert(alert_id)
    if a is None or a.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Alert non trovato")
    return price_alerts_store.set_active(alert_id, req.active)


def _owned_favorite_or_404(entry_id: str, user: User) -> FavoriteEntry:
    entry = favorites_store.get_entry(entry_id)
    if entry is None or entry.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Voce non trovata")
    return entry


@app.get("/api/favorites", response_model=list[FavoriteEntry])
async def get_favorites(user: User = Depends(auth.get_current_user)) -> list[FavoriteEntry]:
    return favorites_store.list_entries(owner_id=user.id)


class FavoriteAddRequest(BaseModel):
    symbol: str
    asset_type: AssetType
    exchange: CryptoExchange = "mexc"


@app.post("/api/favorites", response_model=FavoriteEntry)
async def add_favorite_entry(
    req: FavoriteAddRequest, user: User = Depends(auth.get_current_user)
) -> FavoriteEntry:
    symbol = req.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")

    provider = get_provider(req.asset_type, req.exchange)
    try:
        probe = await provider.fetch_ohlcv(symbol, "1d", 2)
    except ProviderError as exc:
        raise HTTPException(
            status_code=400, detail=f"Ticker non trovato su questo exchange: {exc}"
        ) from exc
    if probe.empty:
        raise HTTPException(status_code=400, detail="Ticker non trovato su questo exchange.")

    return favorites_store.add_entry(user.id, symbol, req.asset_type, exchange=req.exchange)


@app.delete("/api/favorites/{entry_id}")
async def delete_favorite_entry(entry_id: str, user: User = Depends(auth.get_current_user)) -> dict:
    _owned_favorite_or_404(entry_id, user)
    favorites_store.remove_entry(entry_id)
    return {"ok": True}


class FavoriteQuote(BaseModel):
    id: str
    price: float | None = None
    change_pct: float | None = None


@app.get("/api/favorites/quotes", response_model=list[FavoriteQuote])
async def get_favorite_quotes(user: User = Depends(auth.get_current_user)) -> list[FavoriteQuote]:
    """Last price + day-over-day change for every favorite, fetched
    concurrently. A quote that fails to resolve (delisted ticker, provider
    hiccup) comes back with null price/change rather than failing the
    whole batch — the frontend just shows a dash for that row."""
    entries = favorites_store.list_entries(owner_id=user.id)

    async def quote_for(entry: FavoriteEntry) -> FavoriteQuote:
        provider = get_provider(entry.asset_type, entry.exchange)

        try:
            df = await _fetch_cached(
                (f"favquote:{entry.asset_type}:{entry.exchange}:{entry.symbol}", "1d", 2),
                provider, entry.symbol, "1d", 2,
            )
        except ProviderError:
            return FavoriteQuote(id=entry.id)
        if df.empty:
            return FavoriteQuote(id=entry.id)
        closes = df["close"].tolist()
        price = closes[-1]
        change_pct = ((closes[-1] - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 and closes[-2] else None
        return FavoriteQuote(id=entry.id, price=price, change_pct=change_pct)

    return list(await asyncio.gather(*(quote_for(e) for e in entries)))


@app.get("/api/analyze", response_model=AnalysisResponse)
async def analyze(
    symbol: str = Query(..., min_length=1, max_length=20),
    asset_type: AssetType = Query("stock"),
    exchange: CryptoExchange = Query("mexc"),
    htf_interval: IntervalChoice = Query(DEFAULT_INTERVALS["htf"]),
    mtf_interval: IntervalChoice = Query(DEFAULT_INTERVALS["mtf"]),
    ltf_interval: IntervalChoice = Query(DEFAULT_INTERVALS["ltf"]),
    strategy_name: str = Query(DEFAULT_STRATEGY),
    strategy_params: StrategyParamsQuery = Depends(),
    backtest_params: BacktestParamsQuery = Depends(),
) -> AnalysisResponse:
    symbol = symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    if strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {strategy_name}")

    strategy_params_dict = strategy_params.model_dump()
    backtest_params_dict = backtest_params.model_dump()

    provider = get_provider(asset_type, exchange)
    intervals: dict[TimeframeKey, str] = {"htf": htf_interval, "mtf": mtf_interval, "ltf": ltf_interval}

    async def fetch_timeframe(tf_key: TimeframeKey):
        interval = intervals[tf_key]
        outputsize = settings.ltf_candles if tf_key == "ltf" else settings.candles_per_timeframe
        cache_key = (f"{asset_type}:{exchange}:{symbol.upper()}", interval, outputsize)

        try:
            df = await _fetch_cached(cache_key, provider, symbol, interval, outputsize)
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return tf_key, df

    fetched = await asyncio.gather(*(fetch_timeframe(tf_key) for tf_key in settings.timeframe_keys))

    timeframes: dict[str, TimeframeAnalysis] = {}
    strategies: dict[str, list[StrategyState]] = {}
    backtests: dict[str, object] = {}
    for tf_key, df in fetched:
        if df.empty:
            raise HTTPException(status_code=502, detail=f"Nessun dato per {symbol} su timeframe {tf_key}")

        swings = compute_swings(df, tf_key)
        levels = compute_levels(df, swings)
        indicators = compute_indicators(df)
        bias = determine_bias(levels)
        dealing_range = compute_dealing_range(df, swings)
        fib_zones = compute_fib_zones(df, tf_key, intervals[tf_key])
        strategy = build_strategy_state(strategy_name, df, strategy_params_dict)
        strategies[tf_key] = [strategy]
        # The frontend only ever charts the ltf timeframe (state.activeTimeframe
        # is a hardcoded "ltf", never reassigned) — htf/mtf backtests are never
        # read (only strategies[htf|mtf] is, for cross-timeframe signal markers).
        # Running the bar-by-bar backtest simulation twice for data nothing
        # displays was pure wasted latency on every single analyze call.
        if tf_key == "ltf":
            # This is the fast pass, on whatever the chart already fetched —
            # instant, but only as deep as ltf_candles. The frontend follows
            # up with a separate /api/backtest/deep call (see that endpoint)
            # that swaps this out for a backtest over each exchange's full
            # history once that slower, paginated fetch resolves — without
            # that split, every timeframe change would block on it too.
            result = run_backtest(df, strategy_params_dict, backtest_params_dict, strategy_name=strategy_name)
            backtests[tf_key] = result.model_copy(update={"interval": intervals[tf_key]})
        else:
            backtests[tf_key] = BacktestResult(
                interval=intervals[tf_key],
                initial_capital=backtest_params_dict.get("initial_capital", 10000.0),
                final_equity=backtest_params_dict.get("initial_capital", 10000.0),
                total_return_pct=0.0,
                num_trades=0,
                win_rate_pct=None,
                max_drawdown_pct=0.0,
                profit_factor=None,
                equity_curve=[],
                trades=[],
            )
        candles = [
            Candle(
                time=int(ts.timestamp()),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for ts, row in df.iterrows()
        ]
        # Same story for the raw candle/indicator time series: the chart only
        # ever plots ltf, and build_summary's per-timeframe indicator readout
        # (below) only reads each series' *last* value. htf/mtf keep full
        # levels/dealing_range/fib_zones (compute_confluence and the summary
        # both need those) but only their tail candle/indicator points, not
        # the full 500-bar history — that history was ~2/3 of this endpoint's
        # response size for two timeframes nothing ever renders.
        if tf_key != "ltf":
            candles = candles[-2:]
            indicators = [ind.model_copy(update={"values": ind.values[-2:]}) for ind in indicators]
        timeframes[tf_key] = TimeframeAnalysis(
            interval=intervals[tf_key],
            candles=candles,
            levels=levels,
            indicators=indicators,
            bias=bias,
            dealing_range=dealing_range,
            fib_zones=fib_zones,
        )

    confluence_zones = compute_confluence(timeframes)
    current_price = timeframes["ltf"].candles[-1].close
    summary = build_summary(current_price, timeframes, confluence_zones)

    return AnalysisResponse(
        symbol=canonical_symbol(symbol, asset_type, exchange),
        asset_type=asset_type,
        current_price=current_price,
        timeframes=timeframes,
        confluence_zones=confluence_zones,
        summary=summary,
        strategies=strategies,
        backtests=backtests,
    )


@app.get("/api/backtest/deep", response_model=BacktestResult)
async def deep_backtest(
    symbol: str = Query(..., min_length=1, max_length=20),
    asset_type: AssetType = Query("stock"),
    exchange: CryptoExchange = Query("mexc"),
    ltf_interval: IntervalChoice = Query(DEFAULT_INTERVALS["ltf"]),
    strategy_name: str = Query(DEFAULT_STRATEGY),
    strategy_params: StrategyParamsQuery = Depends(),
    backtest_params: BacktestParamsQuery = Depends(),
) -> BacktestResult:
    """The backtest's own, deliberately coarser fetch (see
    backtest_interval_for) instead of the ltf df the chart uses — reaches
    each exchange's actual listing date instead of stopping wherever
    ltf_candles does. Split out of /api/analyze on purpose: this can take
    several seconds on a cold cache (a multi-page fetch), and gating the
    whole chart response on it made every timeframe switch pay that cost
    too. The frontend calls this right after /api/analyze already rendered
    the chart with the fast pass, and swaps the backtest panel over once
    this resolves."""
    symbol = symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    if strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {strategy_name}")

    provider = get_provider(asset_type, exchange)
    backtest_interval = backtest_interval_for(ltf_interval)
    cache_key = (f"{asset_type}:{exchange}:{symbol.upper()}:backtest", backtest_interval, settings.backtest_candles)

    try:
        df = await _fetch_cached(cache_key, provider, symbol, backtest_interval, settings.backtest_candles)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if df.empty:
        raise HTTPException(status_code=502, detail=f"Nessun dato per {symbol}")

    result = run_backtest(df, strategy_params.model_dump(), backtest_params.model_dump(), strategy_name=strategy_name)
    return result.model_copy(update={"interval": backtest_interval})


class OptimizeCandidate(BaseModel):
    """One entry of the optimizer's ranked shortlist.

    Exposing the whole shortlist — rather than only the winner — lets the UI
    show the dispersion between the top candidates. A shortlist whose members
    disagree wildly is itself the signal that the winner is a lucky draw
    rather than a stable optimum."""

    rank: int
    params: dict
    score: float
    total_return_pct: float
    max_drawdown_pct: float
    num_trades: int
    win_rate_pct: float | None = None
    profit_factor: float | None = None
    out_of_sample_return_pct: float | None = None
    overfitted: bool = False


class Overfitting(BaseModel):
    """Quanto spesso, fra i candidati considerati, il migliore in campione
    finisce sotto la mediana fuori campione.

    Non e' un doppione dello Sharpe deflazionato: quello corregge un numero,
    questo giudica la selezione. Un risultato puo' superare l'uno e fallire
    l'altro, e i due casi vanno letti diversamente."""

    pbo: float | None = None
    acceptable: bool = False
    n_candidates: int = 0
    n_splits: int = 0
    note: str = ""


class RegimeInfo(BaseModel):
    """Whether the strategy had an edge to find on this series at all.

    Surfaced rather than enforced: a result produced under a failed gate is
    fitted to a series where the strategy has no measurable edge, and the
    caller needs to be able to see that instead of reading the return figure
    as if it meant the same thing."""

    passed: bool
    family: str | None = None
    reason: str = ""
    variance_ratio: float | None = None
    vr_z: float | None = None
    vr_p_one_sided: float | None = None
    hurst: float | None = None
    verdict: str = ""


class BranchInfo(BaseModel):
    """One branch of the parameter space, with the result it reached.

    Shown side by side because that comparison is the finding: on the series
    measured, branches with more free parameters scored higher in-sample and
    worse out-of-sample. A single returned number hides exactly that."""

    label: str
    dims: int
    enumerated: bool
    chosen: bool
    total_return_pct: float
    max_drawdown_pct: float
    num_trades: int
    validation_return_pct: float | None = None
    validation_trades: int | None = None
    params: dict = {}


class DeflatedSharpe(BaseModel):
    """The winner's Sharpe, corrected for how many configurations were tried.

    The expected maximum Sharpe under no skill grows with the number of
    attempts, so a figure produced by searching thousands of candidates is not
    comparable to one from a single hypothesis. `deflated` is the probability
    the result survives that correction; below 0.95 it is not distinguishable
    from the best of that many attempts on noise."""

    sharpe: float | None = None
    deflated: float | None = None
    sharpe_threshold: float | None = None
    n_trials: int = 0
    acceptable: bool = False


class DataUsed(BaseModel):
    """Su quali dati e' realmente girata l'ottimizzazione.

    Senza questi campi il risultato non e' riproducibile a mano nemmeno in
    linea di principio: l'ottimizzazione non usa il timeframe del grafico ma
    quello derivato da backtest_interval_for(), con un minimo di 1d, e un
    numero di candele diverso. Stessi parametri su feed diversi danno lo stesso
    ordine di rendimento e un numero di trade completamente diverso — misurato
    su KASUSDT: 27 trade a 1d contro 186 a 4h."""

    interval: str
    candles: int
    chart_interval: str
    differs_from_chart: bool
    note: str = ""


class OptimizeResult(BaseModel):
    params: dict
    backtest: BacktestResult
    trials_evaluated: int
    data_used: DataUsed | None = None
    out_of_sample_return_pct: float | None = None
    overfitted: bool = False
    mode: str = "random"
    top_candidates: list[OptimizeCandidate] = []
    # Populated by mode="plateau" only.
    deterministic: bool | None = None
    regime: RegimeInfo | None = None
    branches: list[BranchInfo] = []
    chosen_branch: str | None = None
    pipeline_notes: list[str] = []
    deflated_sharpe: DeflatedSharpe | None = None
    overfitting: Overfitting | None = None


async def _optimize_payload(
    strategy_name: str,
    df,
    backtest_params: "BacktestParamsQuery",
    mode: str,
    ltf_interval: str,
    backtest_interval: str,
    constraints: "Constraints",
    say=None,
    should_stop=None,
) -> "OptimizeResult":
    """Costruisce la risposta dell'ottimizzazione, una volta sola.

    La usano sia la GET diretta sia il lavoro seguito in diretta: due copie di
    questa costruzione divergerebbero al primo campo aggiunto, e il campo
    mancherebbe proprio nel percorso che non si guarda mai a mano.

    `say` riceve le righe di avanzamento; senza, la ricerca gira muta come
    prima.
    """
    say = say or (lambda _m: None)
    data_used = DataUsed(
        interval=backtest_interval,
        candles=len(df),
        chart_interval=ltf_interval,
        differs_from_chart=backtest_interval != ltf_interval,
        note=(
            f"Ottimizzato su {len(df)} candele a {backtest_interval}, non sul "
            f"timeframe {ltf_interval} del grafico. Per riprodurre a mano questo "
            f"risultato imposta il grafico su {backtest_interval}."
            if backtest_interval != ltf_interval
            else f"Ottimizzato su {len(df)} candele a {backtest_interval}, "
                 f"lo stesso timeframe del grafico."
        ),
    )

    if mode == "plateau":
        # Deterministic path: same inputs give the same answer, because the
        # cell grid is enumerated rather than sampled wherever it fits the
        # budget. Measured against random search on identical data with only
        # the seed varying, cv of the out-of-sample return went from 66.5% to
        # 0% (Gabriele) and from 225.1% to 0% (Lorenzo).
        try:
            pr = await asyncio.to_thread(
                partial(
                    run_pipeline, strategy_name, df, backtest_params.model_dump(),
                    accept=(constraints.accepts if constraints.active else None),
                    progress=say, should_stop=should_stop,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422 if constraints.active else 400, detail=str(exc)
            ) from exc
        rep = pr.gate.report
        return OptimizeResult(
            params=pr.params,
            backtest=pr.backtest.model_copy(update={"interval": backtest_interval}),
            trials_evaluated=pr.evaluations,
            out_of_sample_return_pct=pr.out_of_sample_return_pct,
            overfitted=pr.overfitted,
            mode=mode,
            data_used=data_used,
            deterministic=pr.deterministic,
            chosen_branch=pr.chosen_branch,
            pipeline_notes=pr.notes,
            deflated_sharpe=(
                None if pr.dsr is None else DeflatedSharpe(
                    sharpe=pr.dsr.sharpe, deflated=pr.dsr.deflated,
                    sharpe_threshold=pr.dsr.sharpe_threshold,
                    n_trials=pr.dsr.n_trials, acceptable=pr.dsr.acceptable,
                )
            ),
            overfitting=(
                None if pr.pbo is None else Overfitting(
                    pbo=pr.pbo.pbo, acceptable=pr.pbo.acceptable,
                    n_candidates=pr.pbo.n_candidates, n_splits=pr.pbo.n_splits,
                    note=pr.pbo.note,
                )
            ),
            regime=RegimeInfo(
                passed=pr.gate.passed, family=pr.gate.family, reason=pr.gate.reason,
                variance_ratio=rep.variance_ratio, vr_z=rep.vr_z,
                vr_p_one_sided=rep.vr_p_one_sided, hurst=rep.hurst,
                verdict=rep.verdict,
            ),
            branches=[
                BranchInfo(
                    label=b.label, dims=b.dims, enumerated=b.enumerated,
                    chosen=b.label == pr.chosen_branch,
                    total_return_pct=b.best.backtest.total_return_pct,
                    max_drawdown_pct=b.best.backtest.max_drawdown_pct,
                    num_trades=b.best.backtest.num_trades,
                    validation_return_pct=b.validation_return_pct,
                    validation_trades=b.validation_trades,
                    params=b.best.params,
                )
                for b in pr.branches if b.best is not None
            ],
        )

    try:
        best_params, best_bt, trials, oos_return, overfitted, top_results = await asyncio.to_thread(
            partial(
                optimize_strategy, strategy_name, df, backtest_params.model_dump(),
                mode=mode, constraints=constraints, progress=say,
                should_stop=should_stop,
            )
        )
    except NoCandidateMeetsConstraints as exc:
        # 422 e non 500: la richiesta e' valida, e' il risultato a non esistere
        # con quei vincoli. Il messaggio dice quante configurazioni sono state
        # escluse, cosi' si capisce se allentare di poco o di molto.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    best_bt = best_bt.model_copy(update={"interval": backtest_interval})
    return OptimizeResult(
        params=best_params,
        backtest=best_bt,
        trials_evaluated=trials,
        out_of_sample_return_pct=oos_return,
        overfitted=overfitted,
        mode=mode,
        data_used=data_used,
        top_candidates=[
            OptimizeCandidate(
                rank=c["rank"],
                params=c["params"],
                score=c["score"],
                total_return_pct=c["backtest"].total_return_pct,
                max_drawdown_pct=c["backtest"].max_drawdown_pct,
                num_trades=c["backtest"].num_trades,
                win_rate_pct=c["backtest"].win_rate_pct,
                profit_factor=c["backtest"].profit_factor,
                out_of_sample_return_pct=c["out_of_sample_return_pct"],
                overfitted=c["overfitted"],
            )
            for c in top_results
        ],
    )


@app.get("/api/export/backtest.xlsx")
async def export_backtest(
    symbol: str = Query(..., min_length=1, max_length=20),
    asset_type: AssetType = Query("stock"),
    exchange: CryptoExchange = Query("mexc"),
    ltf_interval: IntervalChoice = Query(DEFAULT_INTERVALS["ltf"]),
    strategy_name: str = Query(DEFAULT_STRATEGY),
    strategy_params: StrategyParamsQuery = Depends(),
    backtest_params: BacktestParamsQuery = Depends(),
) -> StreamingResponse:
    """Il backtest come foglio di calcolo, con i grafici dentro.

    Rieseguito qui invece di ricevere i numeri dal browser: un foglio costruito
    su quello che il client afferma sarebbe un foglio di affermazioni. Costa un
    backtest, che e' la stessa cosa che l'utente ha appena guardato.
    """
    symbol = symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    if strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {strategy_name}")

    provider = get_provider(asset_type, exchange)
    backtest_interval = backtest_interval_for(ltf_interval)
    cache_key = (f"{asset_type}:{exchange}:{symbol.upper()}:backtest",
                 backtest_interval, settings.backtest_candles)
    try:
        df = await _fetch_cached(cache_key, provider, symbol, backtest_interval,
                                 settings.backtest_candles)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if df.empty:
        raise HTTPException(status_code=502, detail=f"Nessun dato per {symbol}")

    sp = strategy_params.model_dump()
    bp = backtest_params.model_dump()
    bt = await asyncio.to_thread(
        partial(run_backtest, df, sp, bp, strategy_name=strategy_name)
    )
    bt = bt.model_copy(update={"interval": backtest_interval})
    blob = await asyncio.to_thread(
        partial(build_backtest_workbook, bt, symbol=symbol, strategy_name=strategy_name,
                chart_interval=ltf_interval, params=sp, backtest_params=bp)
    )
    stamp = _time.strftime("%Y%m%d-%H%M")
    name = f"backtest-{symbol.upper()}-{backtest_interval}-{stamp}.xlsx"
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )



# ── Un lavoro pesante per volta, per utente ───────────────────────────────
#
# Una ricerca stabile su Lorenzo vale circa 5000 backtest e tiene occupato un
# core per minuti. La macchina ne ha due, e uno serve a rispondere alle
# richieste e a far girare il ciclo che manda gli avvisi.
#
# Senza questo limite, dieci richieste lanciate insieme — per errore, per
# impazienza, o apposta — mettono in coda dieci ricerche e il sito smette di
# rispondere. Il limite non impedisce di ottimizzare: impedisce di
# ottimizzare dieci cose contemporaneamente, che non serviva a nessuno.
_ricerche_in_corso: dict[str, float] = {}
_LIMITE_RICERCA_SECONDI = 30 * 60   # oltre, si presume che sia morta


def _inizia_lavoro_pesante(owner_id: str) -> None:
    """Alza la mano per questo utente, o spiega perche' non si puo'."""
    adesso = _time.time()
    # Le voci vecchie si scartano qui invece che con un compito periodico:
    # un processo riavviato non deve lasciare nessuno bloccato per sempre.
    for chiave, quando in list(_ricerche_in_corso.items()):
        if adesso - quando > _LIMITE_RICERCA_SECONDI:
            _ricerche_in_corso.pop(chiave, None)

    if owner_id in _ricerche_in_corso:
        da_quanto = int(adesso - _ricerche_in_corso[owner_id])
        raise HTTPException(
            status_code=429,
            detail=(
                f"Hai gia' una ricerca in corso da {da_quanto // 60} min {da_quanto % 60} s. "
                "Aspetta che finisca: due ricerche insieme non vanno piu' veloci, "
                "si rubano il processore a vicenda."
            ),
        )
    _ricerche_in_corso[owner_id] = adesso


def _finisci_lavoro_pesante(owner_id: str) -> None:
    _ricerche_in_corso.pop(owner_id, None)


@app.get("/api/optimize", response_model=OptimizeResult)
async def optimize_strategy_endpoint(
    symbol: str = Query(..., min_length=1, max_length=20),
    asset_type: AssetType = Query("stock"),
    exchange: CryptoExchange = Query("mexc"),
    ltf_interval: IntervalChoice = Query(DEFAULT_INTERVALS["ltf"]),
    strategy_name: str = Query(DEFAULT_STRATEGY),
    backtest_params: BacktestParamsQuery = Depends(),
    mode: str = Query("random", pattern="^(random|grid|plateau)$"),
    # Filtri opzionali sul risultato. `None` = nessun vincolo, ed e' distinto
    # da 0, che e' il vincolo piu' stringente ("nessun trade in perdita",
    # "drawdown nullo") e va potuto chiedere.
    min_losing_trades: int | None = Query(None, ge=0, le=1000),
    max_losing_trades: int | None = Query(None, ge=0, le=1000),
    max_drawdown_pct: float | None = Query(None, ge=0.0, le=100.0),
    user: User = Depends(auth.get_current_user),
) -> OptimizeResult:
    """Random-search parameter tuning for any strategy in the registry —
    same deep-history df the backtest itself uses (see
    backtest_interval_for), so results here match what re-running the
    backtest with the winning params will show. CPU-bound (~120 backtest
    simulations, ~15-25s), so it runs off the event loop via a thread —
    otherwise it would stall every other request (including other users')
    for its whole duration."""
    _inizia_lavoro_pesante(user.id)
    try:
        return await _optimize_body(
            symbol, asset_type, exchange, ltf_interval, strategy_name,
            backtest_params, mode, min_losing_trades, max_losing_trades, max_drawdown_pct,
        )
    finally:
        _finisci_lavoro_pesante(user.id)


async def _optimize_body(
    symbol: str,
    asset_type: AssetType,
    exchange: CryptoExchange,
    ltf_interval: IntervalChoice,
    strategy_name: str,
    backtest_params: "BacktestParamsQuery",
    mode: str,
    min_losing_trades: int | None,
    max_losing_trades: int | None,
    max_drawdown_pct: float | None,
) -> OptimizeResult:
    """Il lavoro vero. Sta a parte perche' il contatore delle ricerche in
    corso va riabbassato anche quando qualcosa esplode a meta', e un
    `finally` avvolto attorno a duecento righe non si legge."""
    symbol = symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    if not is_optimizable(strategy_name):
        raise HTTPException(status_code=400, detail=f"Ottimizzazione non disponibile per {strategy_name}")

    provider = get_provider(asset_type, exchange)
    backtest_interval = backtest_interval_for(ltf_interval)
    cache_key = (f"{asset_type}:{exchange}:{symbol.upper()}:backtest", backtest_interval, settings.backtest_candles)

    try:
        df = await _fetch_cached(cache_key, provider, symbol, backtest_interval, settings.backtest_candles)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if df.empty:
        raise HTTPException(status_code=502, detail=f"Nessun dato per {symbol}")

    constraints = Constraints(
        min_losing_trades=min_losing_trades,
        max_losing_trades=max_losing_trades,
        max_drawdown_pct=max_drawdown_pct,
    )
    return await _optimize_payload(
        strategy_name, df, backtest_params, mode, ltf_interval,
        backtest_interval, constraints,
    )


# --- Ottimizzazione seguita in diretta ---------------------------------------
# Una ricerca stabile puo' durare minuti, e tenerla dentro una GET significa
# tenere aperta quella richiesta per tutto il tempo: il proxy davanti all'app la
# chiude, il browser la lascia cadere, e quello che torna non e' piu' JSON ma una
# pagina d'errore. Safari prova a leggerla come JSON e risponde "The string did
# not match the expected pattern" — il messaggio finito sulla bacheca, che non
# nomina l'ottimizzazione perche' non e' l'ottimizzazione ad aver fallito.
#
# Qui la richiesta apre un lavoro e torna subito; il lavoro prosegue per conto
# suo e accumula righe di log che il client chiede quando vuole.


def _archive_optimizer_result(owner_id: str, symbol: str, asset_type: str,
                              exchange: str, ltf_interval: str, strategy_name: str,
                              mode: str, body: "OptimizeResult") -> dict:
    """Mette il risultato nell'archivio, gia' completo di numeri.

    Le metriche non vengono ricalcolate: sono quelle del backtest che la ricerca
    ha appena eseguito, quindi rieseguirlo significherebbe rifare lo stesso
    lavoro e rischiare un numero diverso per via del feed che nel frattempo si
    e' allungato.
    """
    bt = body.backtest
    entry = archive_store.create(
        owner_id=owner_id, symbol=symbol, asset_type=asset_type, exchange=exchange,
        interval=ltf_interval, strategy_name=strategy_name, params=body.params,
        backtest_params={}, source="ottimizzazione",
        note=f"Ricerca {_MODE_LABEL.get(mode, mode)}",
        optimizer={
            "mode": mode,
            "evaluations": body.trials_evaluated,
            "out_of_sample_return_pct": body.out_of_sample_return_pct,
            "overfitted": body.overfitted,
            "deterministic": body.deterministic,
            "chosen_branch": body.chosen_branch,
            "regime_passed": None if body.regime is None else body.regime.passed,
            "regime_reason": "" if body.regime is None else body.regime.reason,
            "deflated_sharpe": None if body.deflated_sharpe is None else body.deflated_sharpe.deflated,
            "pbo": None if body.overfitting is None else body.overfitting.pbo,
        },
    )
    archive_store.attach_result(entry["id"], {
        "interval": bt.interval,
        "candles": None if body.data_used is None else body.data_used.candles,
        "total_return_pct": bt.total_return_pct,
        "num_trades": bt.num_trades,
        "win_rate_pct": bt.win_rate_pct,
        "max_drawdown_pct": bt.max_drawdown_pct,
        "profit_factor": bt.profit_factor,
        "sharpe_ratio": bt.sharpe_ratio,
        "initial_capital": bt.initial_capital,
        "final_equity": bt.final_equity,
        "data_start": bt.data_start,
        "data_end": bt.data_end,
    })
    return entry


_MODE_LABEL = {"random": "rapida", "grid": "griglia", "plateau": "stabile"}


def _optimizer_summary(symbol: str, strategy_name: str, mode: str,
                       body: "OptimizeResult") -> str:
    """Il riepilogo che arriva a ricerca finita.

    Porta anche i verdetti, non solo il rendimento: un +646% con il gate non
    superato e una stabilita' dello 0% e' un numero da non usare, e mandare
    solo il primo dei tre lo farebbe sembrare un risultato.
    """
    bt = body.backtest
    lines = [
        f"🔬 <b>Ottimizzazione conclusa</b> — {symbol.upper()}",
        f"{strategy_name} · ricerca {_MODE_LABEL.get(mode, mode)} · {body.trials_evaluated} backtest",
        "",
        f"In campione: <b>{bt.total_return_pct:+.1f}%</b> su {bt.num_trades} trade "
        f"(drawdown {bt.max_drawdown_pct:.1f}%)",
    ]
    if body.out_of_sample_return_pct is not None:
        lines.append(f"Fuori campione: <b>{body.out_of_sample_return_pct:+.1f}%</b>"
                     + (" ⚠️ sovradattato" if body.overfitted else ""))
    if body.regime is not None and not body.regime.passed:
        lines.append("⚠️ Gate di regime non superato: su questa serie la strategia "
                     "non ha un edge misurabile, il risultato è adattamento al rumore.")
    if body.deflated_sharpe is not None and body.deflated_sharpe.deflated is not None \
            and not body.deflated_sharpe.acceptable:
        lines.append(f"⚠️ Affidabilità {body.deflated_sharpe.deflated * 100:.0f}% "
                     f"dopo correzione per {body.deflated_sharpe.n_trials} tentativi.")
    if body.overfitting is not None and body.overfitting.pbo is not None \
            and not body.overfitting.acceptable:
        lines.append(f"⚠️ Sovra-ottimizzazione {body.overfitting.pbo * 100:.0f}%.")
    if body.deterministic is False:
        lines.append("ℹ️ Parte della griglia è stata campionata: quel pezzo non è riproducibile.")
    lines.append("")
    lines.append("Salvata nell'archivio strategie, scheda Watchlist.")
    return "\n".join(lines)


@app.post("/api/optimize/start")
async def start_optimize(
    symbol: str = Query(..., min_length=1, max_length=20),
    asset_type: AssetType = Query("stock"),
    exchange: CryptoExchange = Query("mexc"),
    ltf_interval: IntervalChoice = Query(DEFAULT_INTERVALS["ltf"]),
    strategy_name: str = Query(DEFAULT_STRATEGY),
    backtest_params: BacktestParamsQuery = Depends(),
    mode: str = Query("random", pattern="^(random|grid|plateau)$"),
    min_losing_trades: int | None = Query(None, ge=0, le=1000),
    max_losing_trades: int | None = Query(None, ge=0, le=1000),
    max_drawdown_pct: float | None = Query(None, ge=0.0, le=100.0),
    user: User | None = Depends(auth.get_current_user_optional),
) -> dict:
    symbol = symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    if not is_optimizable(strategy_name):
        raise HTTPException(status_code=400, detail=f"Ottimizzazione non disponibile per {strategy_name}")

    owner_id = user.id if user else ""
    job_id = jobs_store.create(owner_id, "optimize", f"{symbol.upper()} · {strategy_name} · {mode}")

    constraints = Constraints(
        min_losing_trades=min_losing_trades,
        max_losing_trades=max_losing_trades,
        max_drawdown_pct=max_drawdown_pct,
    )

    async def _run() -> None:
        try:
            jobs_store.log(job_id, f"scarico i dati di {symbol.upper()}…")
            provider = get_provider(asset_type, exchange)
            backtest_interval = backtest_interval_for(ltf_interval)
            cache_key = (f"{asset_type}:{exchange}:{symbol.upper()}:backtest",
                         backtest_interval, settings.backtest_candles)
            df = await _fetch_cached(cache_key, provider, symbol, backtest_interval,
                                     settings.backtest_candles)
            if df.empty:
                jobs_store.fail(job_id, f"Nessun dato per {symbol}")
                return
            jobs_store.log(job_id, f"{len(df)} candele a {backtest_interval}")

            def say(message: str) -> None:
                jobs_store.log(job_id, message)

            body = await _optimize_payload(
                strategy_name, df, backtest_params, mode, ltf_interval,
                backtest_interval, constraints, say,
                should_stop=lambda: jobs_store.cancel_requested(job_id),
            )
            jobs_store.finish(job_id, body.model_dump(mode="json"))

            # Il lavoro e' finito anche se nessuno stava guardando: la ricerca
            # gira sul server, quindi chiudere Safari o perdere la linea non la
            # ferma. Perche' quel risultato non si perda con la scheda, viene
            # archiviato e annunciato.
            if owner_id:
                archived = _archive_optimizer_result(owner_id, symbol, asset_type,
                                                     exchange, ltf_interval, strategy_name,
                                                     mode, body)
                jobs_store.log(job_id, f"salvata in archivio ({archived['id']})")
                user_now = auth.get_user(owner_id)
                if user_now and user_now.telegram_chat_id and _telegram_allowed(user_now):
                    await telegram.send_to(user_now.telegram_chat_id,
                                           _optimizer_summary(symbol, strategy_name, mode, body))
                    jobs_store.log(job_id, "riepilogo mandato su Telegram")
            jobs_store.log(job_id, "fatto")
        except SearchCancelled:
            jobs_store.log(job_id, "fermata su richiesta")
            jobs_store.cancelled(job_id)
        except NoCandidateMeetsConstraints as exc:
            jobs_store.fail(job_id, str(exc))
        except ProviderError as exc:
            jobs_store.fail(job_id, f"Dati non disponibili: {exc}")
        except Exception as exc:  # noqa: BLE001
            # Ampio di proposito: gira staccato dalla richiesta, quindi
            # un'eccezione non intercettata qui non raggiunge nessuno e il
            # lavoro resterebbe "in corso" per sempre.
            logger.error("ottimizzazione fallita per %s: %s", symbol, exc, exc_info=True)
            jobs_store.fail(job_id, str(exc))
            if owner_id:
                user_now = auth.get_user(owner_id)
                if user_now and user_now.telegram_chat_id and _telegram_allowed(user_now):
                    await telegram.send_to(
                        user_now.telegram_chat_id,
                        f"⚠️ <b>Ottimizzazione fallita</b> — {symbol.upper()} · {strategy_name}\n{exc}",
                    )

    asyncio.create_task(_run())
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str, user: User | None = Depends(auth.get_current_user_optional)
) -> dict:
    """Ferma una ricerca in corso.

    Segna soltanto la richiesta: il lavoro se ne accorge al backtest successivo,
    quindi si ferma entro una frazione di secondo invece che a fase finita.
    """
    if not jobs_store.request_cancel(job_id, owner_id=user.id if user else None):
        raise HTTPException(status_code=404, detail="Lavoro non trovato o scaduto")
    return {"ok": True}


@app.get("/api/jobs/{job_id}")
async def job_status(
    job_id: str,
    since: int = Query(0, ge=0),
    user: User | None = Depends(auth.get_current_user_optional),
) -> dict:
    job = jobs_store.get(job_id, owner_id=user.id if user else None, since=since)
    if job is None:
        raise HTTPException(status_code=404, detail="Lavoro non trovato o scaduto")
    return job


# --- Diario degli ordini automatici ------------------------------------------


@app.get("/api/trading/journal")
async def trading_journal(user: User = Depends(auth.get_current_user)) -> dict:
    """Cosa ha fatto davvero l'esecuzione automatica.

    Distinguere "nessun segnale" da "c'era un segnale e l'ordine non e' partito"
    e' l'intera informazione utile, e prima non era da nessuna parte.
    """
    return {"items": trading_log.list_for(user.id, limit=50)}


@app.delete("/api/trading/journal")
async def clear_trading_journal(user: User = Depends(auth.get_current_user)) -> dict:
    return {"removed": trading_log.clear(user.id)}


# --- Archivio strategie ------------------------------------------------------
# Attivare un alert e' il momento in cui una configurazione smette di essere un
# esperimento e comincia a lavorare per settimane. Senza una fotografia presa
# in quel momento non resta traccia ne' di com'era fatta ne' di cosa prometteva:
# il risultato dell'ottimizzazione vive quanto la scheda del browser.


class ArchiveIn(BaseModel):
    symbol: str
    asset_type: AssetType = "crypto"
    exchange: CryptoExchange = "mexc"
    ltf_interval: IntervalChoice = DEFAULT_INTERVALS["ltf"]
    strategy_name: str
    params: dict = {}
    backtest_params: dict = {}
    note: str = ""


class ArchiveNoteIn(BaseModel):
    note: str = ""


async def _run_archive_backtest(entry_id: str, symbol: str, asset_type: str,
                                exchange: str, ltf_interval: str,
                                strategy_name: str, params: dict,
                                backtest_params: dict) -> None:
    """Riempie la voce d'archivio con le metriche misurate dal server.

    I numeri non arrivano mai dal client: un archivio che accetta le metriche
    che gli vengono passate archivia affermazioni, non misure. Gira in
    background perche' l'attivazione di un alert non deve aspettare un
    backtest, e un fallimento resta scritto sulla voce invece di cancellarla.
    """
    try:
        provider = get_provider(asset_type, exchange)
        backtest_interval = backtest_interval_for(ltf_interval)
        cache_key = (f"{asset_type}:{exchange}:{symbol.upper()}:backtest",
                     backtest_interval, settings.backtest_candles)
        df = await _fetch_cached(cache_key, provider, symbol, backtest_interval,
                                 settings.backtest_candles)
        if df.empty:
            archive_store.attach_error(entry_id, f"Nessun dato per {symbol}")
            return
        bt = await asyncio.to_thread(
            partial(run_backtest, df, params, backtest_params, strategy_name=strategy_name)
        )
        archive_store.attach_result(entry_id, {
            "interval": backtest_interval,
            "candles": len(df),
            "total_return_pct": bt.total_return_pct,
            "num_trades": bt.num_trades,
            "win_rate_pct": bt.win_rate_pct,
            "max_drawdown_pct": bt.max_drawdown_pct,
            "profit_factor": bt.profit_factor,
            "sharpe_ratio": bt.sharpe_ratio,
            "initial_capital": bt.initial_capital,
            "final_equity": bt.final_equity,
            "data_start": bt.data_start,
            "data_end": bt.data_end,
        })
    except Exception as exc:  # noqa: BLE001
        # Volutamente ampio: gira come task in background, quindi un'eccezione
        # non intercettata qui non raggiunge nessuno e la voce resterebbe "in
        # corso" per sempre — che e' il modo peggiore di fallire, perche' sembra
        # ancora in lavorazione.
        logger.warning("archivio: backtest fallito per %s (%s)", symbol, exc)
        archive_store.attach_error(entry_id, str(exc))


@app.get("/api/archive")
async def list_archive(user: User = Depends(auth.get_current_user)) -> dict:
    return {"items": archive_store.list_for(user.id)}


@app.post("/api/archive")
async def add_archive_entry(
    req: ArchiveIn, user: User = Depends(auth.get_current_user)
) -> dict:
    if req.strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {req.strategy_name}")
    symbol = req.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    entry = archive_store.create(
        owner_id=user.id, symbol=symbol, asset_type=req.asset_type,
        exchange=req.exchange, interval=req.ltf_interval,
        strategy_name=req.strategy_name, params=req.params,
        backtest_params=req.backtest_params, source="manuale", note=req.note,
    )
    asyncio.create_task(_run_archive_backtest(
        entry["id"], symbol, req.asset_type, req.exchange, req.ltf_interval,
        req.strategy_name, req.params, req.backtest_params,
    ))
    return entry


@app.get("/api/archive/{entry_id}/export")
async def export_archive_entry(entry_id: str, user: User = Depends(auth.get_current_user)) -> dict:
    """Un file scaricabile che porta 'ogni dettaglio' di una voce d'archivio,
    per ricrearla identica su un altro account (seed-0031, `1c2880d2`).

    Deliberatamente un file, non un link o un accesso condiviso: chi riceve
    decide se e quando importarlo, e non c'e' nessun permesso cross-account
    da disegnare o da poter sbagliare."""
    entry = archive_store.get(entry_id, user.id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Voce d'archivio non trovata")
    return {
        "liquidity_engine_archive_export": 1,
        "symbol": entry["symbol"], "asset_type": entry["asset_type"],
        "exchange": entry["exchange"], "interval": entry["interval"],
        "strategy_name": entry["strategy_name"], "params": entry.get("params") or {},
        "backtest_params": entry.get("backtest_params") or {},
        "metrics": entry.get("metrics"), "optimizer": entry.get("optimizer") or {},
        "note": entry.get("note", ""),
        "exported_at": int(_time.time()),
    }


class ArchiveImportIn(BaseModel):
    liquidity_engine_archive_export: int = 0
    symbol: str
    asset_type: AssetType = "crypto"
    exchange: CryptoExchange = "mexc"
    interval: IntervalChoice = DEFAULT_INTERVALS["ltf"]
    strategy_name: str
    params: dict = {}
    backtest_params: dict = {}
    metrics: dict | None = None
    optimizer: dict = {}
    note: str = ""


@app.post("/api/archive/import")
async def import_archive_entry(req: ArchiveImportIn, user: User = Depends(auth.get_current_user)) -> dict:
    """Ricrea una voce d'archivio da un file esportato da un altro account.

    Le metriche nel file non sono verificate da chi importa — sono la misura
    di chi ha esportato, su dati che nel frattempo possono essere cambiati.
    Restano nella voce (altrimenti l'importazione sarebbe inutile), ma la
    nota lo dice esplicitamente, e chi vuole un numero suo puo' sempre
    riapplicare la voce e rigirare il backtest."""
    if req.strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {req.strategy_name}")
    symbol = req.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    note = f"Importata da un altro account{': ' + req.note if req.note else ''} — metriche non verificate qui"
    entry = archive_store.create(
        owner_id=user.id, symbol=symbol, asset_type=req.asset_type,
        exchange=req.exchange, interval=req.interval,
        strategy_name=req.strategy_name, params=req.params,
        backtest_params=req.backtest_params, source="manuale", note=note[:500],
        optimizer=req.optimizer,
    )
    if req.metrics:
        archive_store.attach_result(entry["id"], req.metrics)
    else:
        archive_store.attach_error(entry["id"], "Nessuna metrica nel file importato")
    return archive_store.get(entry["id"], user.id)


@app.post("/api/archive/{entry_id}/apply-to-alert")
async def apply_archive_entry_to_alert(
    entry_id: str, user: User = Depends(auth.get_current_user)
) -> dict:
    """Accende l'alert con ESATTAMENTE la configurazione archiviata.

    Il ponte che mancava. L'archivio conserva i parametri trovati da una
    ricerca, ma restava una fotografia: per farli lavorare bisognava riscriverli
    a mano nella scheda del ticker, e chi non lo faceva si ritrovava un alert
    acceso sui valori di default della strategia — identico d'aspetto a uno
    ottimizzato, e diverso in tutto il resto. Qui i parametri li prende dalla
    voce d'archivio, non dal client: la stessa regola per cui le metriche
    l'archivio le misura invece di accettarle.
    """
    entry = archive_store.get(entry_id, user.id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Voce d'archivio non trovata")
    strategy_name = entry.get("strategy_name", "")
    if strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {strategy_name}")

    watch = watchlist_store.add_entry(
        user.id, entry["symbol"], entry["asset_type"],
        exchange=entry.get("exchange", "mexc"),
        interval=entry.get("interval", DEFAULT_INTERVALS["ltf"]),
        on_close=True,
    )
    # Prima i parametri, poi l'interruttore: accendere scatta la fotografia
    # d'archivio, e farla prima registrerebbe i default — l'archivio direbbe
    # che l'alert e' partito con una configurazione diversa da quella che sta
    # girando.
    watchlist_store.set_strategy_params(watch.id, strategy_name, entry.get("params") or {})
    watchlist_store.set_strategy_interval(watch.id, strategy_name, entry.get("interval"))
    updated = await toggle_watchlist_strategy(
        watch.id, WatchlistStrategyToggleRequest(strategy_name=strategy_name, enabled=True), user
    )
    return {
        "ok": True,
        "watchlist_entry": updated,
        "strategy_name": strategy_name,
        "params": entry.get("params") or {},
        "interval": entry.get("interval"),
    }


@app.patch("/api/archive/{entry_id}")
async def update_archive_note(
    entry_id: str, req: ArchiveNoteIn, user: User = Depends(auth.get_current_user)
) -> dict:
    entry = archive_store.set_note(entry_id, user.id, req.note)
    if entry is None:
        raise HTTPException(status_code=404, detail="Voce non trovata")
    return entry


@app.delete("/api/archive/{entry_id}")
async def delete_archive_entry(
    entry_id: str, user: User = Depends(auth.get_current_user)
) -> dict:
    if not archive_store.remove(entry_id, user.id):
        raise HTTPException(status_code=404, detail="Voce non trovata")
    return {"ok": True}


# --- Segnalazioni ------------------------------------------------------------
# Lettura pubblica di proposito: la bacheca serve anche a chi non ha ancora
# fatto login, e non contiene nulla di sensibile. La scrittura resta dietro
# autenticazione, cosi' le segnalazioni portano un autore e non chiunque passi
# di qui puo' riempirle.


class IssueIn(BaseModel):
    title: str
    detail: str = ""
    priority: str = "media"


class IssueReplyIn(BaseModel):
    text: str
    # "risolto" lo decide chi ha scritto la segnalazione, non chi ha scritto la
    # correzione: se il problema si vede ancora, la voce torna aperta.
    reopen: bool = False


class IssuePatch(BaseModel):
    status: str | None = None
    priority: str | None = None
    detail: str | None = None


@app.post("/api/issues/{issue_id}/replies")
async def reply_to_issue(
    issue_id: str, req: IssueReplyIn, user: User = Depends(auth.get_current_user)
) -> dict:
    if not any(i["id"] == issue_id for i in issues_store.list_issues()):
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    try:
        return issues_store.add_reply(issue_id, req.text, author=user.email,
                                      reopen=req.reopen)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/issues")
async def list_issues() -> dict:
    items = issues_store.list_issues()
    return {
        "items": items,
        "counts": {
            "aperto": sum(1 for i in items if i.get("status") == "aperto"),
            "in corso": sum(1 for i in items if i.get("status") == "in corso"),
            "risolto": sum(1 for i in items if i.get("status") == "risolto"),
            "riaperto": sum(1 for i in items if i.get("status") == "riaperto"),
        },
    }


@app.post("/api/issues")
async def create_issue(body: IssueIn, user: User = Depends(auth.get_current_user)) -> dict:
    try:
        return issues_store.add_issue(
            title=body.title, detail=body.detail,
            priority=body.priority, author=user.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/issues/{issue_id}")
async def patch_issue(issue_id: str, body: IssuePatch,
                      user: User = Depends(auth.get_current_user)) -> dict:
    try:
        updated = issues_store.update_issue(
            issue_id, status=body.status, priority=body.priority, detail=body.detail
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    return updated


@app.delete("/api/issues/{issue_id}")
async def remove_issue(issue_id: str, user: User = Depends(auth.get_current_user)) -> dict:
    if not issues_store.delete_issue(issue_id):
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    return {"deleted": issue_id}


@app.get("/api/sniper/candidates")
async def sniper_candidates(
    chain: str = Query("", description="Filter by chain_id"),
    min_score: int = Query(0, ge=0, description="Minimum score_total"),
    min_liq: float = Query(0.0, ge=0, description="Minimum liquidity_usd"),
    max_mc: float = Query(0.0, ge=0, description="Maximum market_cap (0 = no limit)"),
    exclude_cex: bool = Query(False, description="Exclude CEX-listed tokens"),
    serious_only: bool = Query(True, description="Solo progetti seri: esclude le meme coin"),
    limit: int = Query(0, ge=0, description="Max results (0 = all)"),
) -> dict:
    from app.sniper import cache as sniper_cache
    from app.sniper.quality import is_serious
    candidates = sniper_cache.get_candidates()
    quality: dict[str, str] = {}
    if serious_only:
        kept = []
        for c in candidates:
            ok, why = is_serious(
                symbol=c.symbol,
                name=c.name,
                liquidity_usd=c.liquidity_usd,
                market_cap=c.market_cap,
                volume_h24=c.volume_h24,
                age_hours=c.age_hours,
                website=c.website,
                cex_listed=c.cex_listed,
            )
            if ok:
                quality[c.token_address] = why
                kept.append(c)
        candidates = kept
    if chain:
        candidates = [c for c in candidates if c.chain_id == chain]
    if min_score:
        candidates = [c for c in candidates if c.score_total >= min_score]
    if min_liq:
        candidates = [c for c in candidates if c.liquidity_usd >= min_liq]
    if max_mc:
        candidates = [c for c in candidates if c.market_cap is None or c.market_cap <= max_mc]
    if exclude_cex:
        candidates = [c for c in candidates if c.cex_listed is not True]
    if limit:
        candidates = candidates[:limit]
    return {
        "candidates": [
            {
                "chain_id": c.chain_id,
                "token_address": c.token_address,
                "pair_address": c.pair_address,
                "symbol": c.symbol,
                "name": c.name,
                "dex_id": c.dex_id,
                "pair_url": c.pair_url,
                "price_usd": c.price_usd,
                "market_cap": c.market_cap,
                "liquidity_usd": c.liquidity_usd,
                "volume_h24": c.volume_h24,
                "volume_h1": c.volume_h1,
                "age_hours": round(c.age_hours, 1),
                "buy_sell_ratio": round(c.buy_sell_ratio, 2),
                "website": c.website,
                "socials": c.socials,
                "score_total": c.score_total,
                "score_max": c.score_max,
                "score_items": c.score_items,
                "first_seen": c.first_seen,
                "last_updated": c.last_updated,
                "cex_listed": c.cex_listed,
                "quality_reason": quality.get(c.token_address),
            }
            for c in candidates
        ],
        "last_scan": sniper_cache.last_scan_ts(),
        "count": len(candidates),
        "serious_only": serious_only,
    }


@app.post("/api/sniper/scan")
async def sniper_trigger_scan() -> dict:
    from app.sniper import cache as sniper_cache
    added = await sniper_cache.run_scan()
    return {"ok": True, "added": added, "total": len(sniper_cache.get_candidates())}


@app.get("/api/sniper/log")
async def sniper_log(limit: int = Query(500, ge=1, le=5000)) -> dict:
    """Persisted scan-log history — survives a page reload / redeploy, so the
    console can show what happened before this browser session connected."""
    from app.sniper import cache as sniper_cache
    return {"events": sniper_cache.get_log(limit)}


@app.get("/api/sniper/scan-stream")
async def sniper_scan_stream() -> StreamingResponse:
    """SSE feed of scan log events. Scanning itself runs continuously in the
    background (polling_loop, every 5 min) regardless of whether anyone is
    watching — this just relays whatever scan is happening, automatic or
    manually triggered, to any open browser tab for as long as it stays
    connected.

    Since two scans can be up to 5 minutes apart, the connection can sit
    with nothing to send for a while — long enough for an intermediate
    proxy to decide it's dead and silently drop it, which left the page
    stuck showing "Connessione…" and reconnecting in a loop. A periodic
    SSE comment (ignored by EventSource, invisible to the console) keeps
    bytes flowing so the connection — and the browser's "open" state —
    survives the quiet stretches."""
    from app.sniper import cache as sniper_cache

    async def event_gen():
        q = sniper_cache.subscribe()
        try:
            yield f"data: {json.dumps({'type': 'connected', 'ts': _time.time()})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            sniper_cache.unsubscribe(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sniper/market")
async def sniper_market(
    chain: str = Query("all"),
    q: str = Query(""),
    sort: str = Query("liquidity"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Browse the market screener's store — every pool GeckoTerminal handed
    us on the last market scan, not just new ones. No score here (see
    sniper/market.py docstring for why); this is filter/sort/browse only."""
    from app.sniper import market as sniper_market_mod

    items, total = sniper_market_mod.get_tokens(
        chain=chain or None, query=q or None, sort=sort, limit=limit, offset=offset
    )
    return {
        "tokens": [
            {
                "chain_id": t.chain_id,
                "token_address": t.token_address,
                "pair_address": t.pair_address,
                "symbol": t.symbol,
                "name": t.name,
                "dex_id": t.dex_id,
                "pair_url": t.pair_url,
                "price_usd": t.price_usd,
                "market_cap": t.market_cap,
                "liquidity_usd": t.liquidity_usd,
                "volume_h24": t.volume_h24,
                "age_hours": round(t.age_hours, 1),
                "buy_sell_ratio": round(t.buy_sell_ratio, 2),
                "last_updated": t.last_updated,
            }
            for t in items
        ],
        "total": total,
        "last_scan": sniper_market_mod.last_scan_ts(),
    }


@app.post("/api/sniper/market-scan")
async def sniper_market_trigger_scan() -> dict:
    from app.sniper import market as sniper_market_mod

    added = await sniper_market_mod.run_market_scan()
    return {"ok": True, "added": added}


@app.post("/api/sniper/market-import")
async def sniper_market_import() -> dict:
    """Apply the sniper's primary filter + on-chain scoring to every token
    currently in the market store and add qualifying ones to the sniper
    candidate archive. Progress is streamed via /api/sniper/market-stream."""
    from app.sniper import market as sniper_market_mod

    if sniper_market_mod.import_in_progress():
        return {"ok": False, "error": "Import already in progress"}
    added = await sniper_market_mod.run_import()
    return {"ok": True, "added": added}


@app.get("/api/sniper/market-log")
async def sniper_market_log(limit: int = 500) -> dict:
    from app.sniper import market as sniper_market_mod
    return {"events": sniper_market_mod.get_log(limit=limit)}


@app.get("/api/sniper/agents")
async def sniper_agents_status() -> dict:
    from app.sniper import agents as sniper_agents
    return {"agents": sniper_agents.get_status()}


@app.get("/api/sniper/research/auto/{token_address}")
async def sniper_research_auto(token_address: str) -> dict:
    """Auto-detect chain via DexScreener, then run research."""
    import httpx as _httpx

    chain_id = None
    async with _httpx.AsyncClient(timeout=12.0) as client:
        try:
            r = await client.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            )
            if r.status_code == 200:
                data = r.json()
                pairs = data.get("pairs") or []
                if pairs:
                    chain_id = pairs[0].get("chainId")
        except Exception:
            pass

    if not chain_id:
        return {
            "chain_id": None,
            "token_address": token_address,
            "research_score": 0,
            "description": "Token non trovato su DexScreener — verifica l'indirizzo.",
            "checks": [{"label": "Non trovato su DexScreener", "passed": False}],
            "links": [],
        }

    return await sniper_research(chain_id, token_address)


@app.get("/api/sniper/research/{chain_id}/{token_address}")
async def sniper_research(chain_id: str, token_address: str) -> dict:
    """Query CoinGecko + DexScreener for a token and return a research report."""
    import httpx as _httpx
    from app.sniper.cex_check import _CHAIN_TO_PLATFORM, _CEX_IDS

    checks = []
    links = []
    description = None
    research_score = 0

    platform = _CHAIN_TO_PLATFORM.get(chain_id)

    async with _httpx.AsyncClient(timeout=12.0) as client:
        # ── CoinGecko contract lookup ──
        cg_data = None
        if platform:
            try:
                r = await client.get(
                    f"https://api.coingecko.com/api/v3/coins/{platform}/contract/{token_address}"
                )
                if r.status_code == 200:
                    cg_data = r.json()
            except Exception:
                pass

        if cg_data:
            research_score += 2
            checks.append({"label": "Trovato su CoinGecko", "passed": True, "note": cg_data.get("name", "")})

            description = (cg_data.get("description") or {}).get("en", "")
            if description and len(description) > 400:
                description = description[:400] + "…"

            # market data quality
            md = cg_data.get("market_data") or {}
            mc = (md.get("market_cap") or {}).get("usd")
            if mc and mc > 0:
                research_score += 1
                checks.append({"label": "Market cap on-chain verificato", "passed": True, "note": f"${mc:,.0f}"})

            # community / social
            comm = cg_data.get("community_data") or {}
            tw = comm.get("twitter_followers", 0) or 0
            tg = comm.get("telegram_channel_user_count", 0) or 0
            if tw > 1000:
                research_score += 1
                checks.append({"label": "Twitter attivo", "passed": True, "note": f"{tw:,} follower"})
            elif tw > 0:
                checks.append({"label": "Twitter presente", "warning": True, "note": f"{tw:,} follower"})
            if tg > 500:
                research_score += 1
                checks.append({"label": "Telegram attivo", "passed": True, "note": f"{tg:,} membri"})
            elif tg > 0:
                checks.append({"label": "Telegram presente", "warning": True, "note": f"{tg:,} membri"})

            # dev activity
            dev = cg_data.get("developer_data") or {}
            commits = (dev.get("commit_count_4_weeks") or 0)
            if commits > 5:
                research_score += 1
                checks.append({"label": "Attività GitHub recente", "passed": True, "note": f"{commits} commit/4wk"})
            elif commits > 0:
                checks.append({"label": "Repository GitHub", "warning": True, "note": f"{commits} commit/4wk"})

            # links
            lnks = cg_data.get("links") or {}
            if lnks.get("homepage"):
                for h in (lnks["homepage"] or []):
                    if h:
                        links.append({"label": "Sito ufficiale", "url": h})
                        break
            if lnks.get("twitter_screen_name"):
                links.append({"label": "Twitter", "url": f"https://twitter.com/{lnks['twitter_screen_name']}"})
            if lnks.get("telegram_channel_identifier"):
                links.append({"label": "Telegram", "url": f"https://t.me/{lnks['telegram_channel_identifier']}"})

            # CEX tickers check
            tickers = cg_data.get("tickers") or []
            cex_names = [t["market"]["name"] for t in tickers if t.get("market", {}).get("identifier", "") in _CEX_IDS]
            if cex_names:
                checks.append({"label": f"Listato su {cex_names[0]}", "warning": True, "note": "già su CEX"})
            else:
                research_score += 1
                checks.append({"label": "Non ancora su CEX", "passed": True, "note": "opportunità early"})
        else:
            checks.append({"label": "Non trovato su CoinGecko", "passed": False, "note": "token non indicizzato"})

        # ── DexScreener pair check ──
        try:
            r2 = await client.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            )
            if r2.status_code == 200:
                pairs = (r2.json().get("pairs") or [])
                if pairs:
                    best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                    liq = float((best.get("liquidity") or {}).get("usd", 0) or 0)
                    vol = float((best.get("volume") or {}).get("h24", 0) or 0)
                    if liq >= 10_000:
                        research_score += 1
                        checks.append({"label": "Liquidità solida su DEX", "passed": True, "note": f"${liq:,.0f}"})
                    elif liq >= 1_000:
                        checks.append({"label": "Liquidità bassa su DEX", "warning": True, "note": f"${liq:,.0f}"})
                    else:
                        checks.append({"label": "Liquidità molto bassa", "passed": False, "note": f"${liq:,.0f}"})
                    if liq > 0 and vol / liq > 0.05:
                        research_score += 1
                        checks.append({"label": "Volume reale (>5% liq)", "passed": True, "note": f"${vol:,.0f}/24h"})
                    if best.get("pairUrl"):
                        links.append({"label": "DexScreener", "url": best["pairUrl"]})
        except Exception:
            pass

    research_score = min(research_score, 10)
    return {
        "chain_id": chain_id,
        "token_address": token_address,
        "research_score": research_score,
        "description": description,
        "checks": checks,
        "links": links,
    }


@app.get("/api/sniper/market-stream")
async def sniper_market_stream() -> StreamingResponse:
    """SSE feed of market-scan progress (per-chain, since this is a heavier
    on-demand pull — up to 10 pages per chain — not the every-5-minutes
    sniper scan)."""
    from app.sniper import market as sniper_market_mod

    async def event_gen():
        q = sniper_market_mod.subscribe()
        try:
            yield f"data: {json.dumps({'type': 'connected', 'ts': _time.time()})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            sniper_market_mod.unsubscribe(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.websocket("/ws/live")
async def live_feed(websocket: WebSocket) -> None:
    params = websocket.query_params
    symbol = params.get("symbol", "").strip()
    if not symbol:
        await websocket.close(code=4000)
        return

    intervals = {
        "htf": params.get("htf_interval", DEFAULT_INTERVALS["htf"]),
        "mtf": params.get("mtf_interval", DEFAULT_INTERVALS["mtf"]),
        "ltf": params.get("ltf_interval", DEFAULT_INTERVALS["ltf"]),
    }

    await websocket.accept()
    await mexc_stream_manager.add_client(websocket, symbol, intervals)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await mexc_stream_manager.remove_client(websocket)


class _VersionedStatic(StaticFiles):
    """File statici con la cache decisa dall'URL.

    Con `?v=<hash>` il contenuto non puo' cambiare senza cambiare l'URL, quindi
    si puo' tenere per sempre. Senza, si rivalida ogni volta: e' l'URL che
    qualcuno puo' aver salvato o che arriva da una pagina vecchia, e servirlo
    dalla cache significherebbe servire codice di due deploy fa.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        query = scope.get("query_string", b"").decode("latin-1")
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if "v=" in query else "no-cache"
        )
        return response


app.mount("/static", _VersionedStatic(directory=str(FRONTEND_DIR / "static")), name="static")


def _compute_asset_version() -> str:
    """Hash of the actual CSS/JS bytes being served, not the git commit —
    correct even in the Docker image, which doesn't ship .git. Computed once
    at process startup: every deploy restarts the process, so the version
    (and therefore the /static/*.css?v=... URL) always changes exactly when
    the files do. Without this, browsers — mobile Safari especially — keep
    serving a stale cached style.css/app.js after a deploy since neither the
    URL nor any cache-control header ever changed."""
    try:
        css = (FRONTEND_DIR / "static" / "style.css").read_bytes()
        js = (FRONTEND_DIR / "static" / "app.js").read_bytes()
        return hashlib.sha256(css + js).hexdigest()[:10]
    except OSError:
        return "0"


_ASSET_VERSION = _compute_asset_version()
_INDEX_HTML = (
    (FRONTEND_DIR / "index.html")
    .read_text(encoding="utf-8")
    .replace('href="/static/style.css"', f'href="/static/style.css?v={_ASSET_VERSION}"')
    .replace('src="/static/app.js"', f'src="/static/app.js?v={_ASSET_VERSION}"')
    .replace("</head>", f'<meta name="lae-asset-version" content="{_ASSET_VERSION}" />\n</head>')
)


_SNIPER_HTML = (
    (FRONTEND_DIR / "sniper.html")
    .read_text(encoding="utf-8")
    .replace('href="/static/style.css"', f'href="/static/style.css?v={_ASSET_VERSION}"')
)


# L'HTML non si mette in cache: e' l'unico posto dove vive il numero di
# versione degli asset. Se il browser tiene la pagina, tiene anche il vecchio
# `?v=`, e continua a chiedere il vecchio app.js — che e' esattamente cosa
# succedeva: il deploy era andato, la pagina no. Gli asset restano cacheabili
# per sempre proprio perche' l'URL cambia con il contenuto.
_HTML_HEADERS = {"Cache-Control": "no-cache"}


@app.get("/api/version")
async def asset_version() -> dict:
    """La versione degli asset che il server sta servendo adesso.

    Serve alla pagina per accorgersi di essere vecchia. Il `no-cache` sull'HTML
    risolve il problema dal deploy in poi, ma chi aveva gia' la pagina in cache
    da prima puo' restarci per ore — ed e' successo: uno vedeva il grafico nero
    dopo che la correzione era in produzione da un pezzo.

    `deployed_at` e' quando QUESTO processo e' partito, non quando il commit
    e' stato scritto: un deploy riavvia sempre il container, quindi coincide
    con l'ultimo deploy riuscito — ed e' la risposta diretta alla domanda
    "il sito e' aggiornato o sto guardando una versione vecchia?", senza
    doverlo dedurre dal fatto che un messaggio Telegram sia arrivato o no.
    """
    return {"asset_version": _ASSET_VERSION, "deployed_at": int(_app_start)}


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(_INDEX_HTML, headers=_HTML_HEADERS)


@app.get("/sniper")
async def sniper_app() -> HTMLResponse:
    return HTMLResponse(_SNIPER_HTML, headers=_HTML_HEADERS)
