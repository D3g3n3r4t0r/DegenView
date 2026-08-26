import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
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

from app import watchlist as watchlist_store
from app.analysis.backtest import run_backtest
from app.analysis.confluence import compute_confluence
from app.analysis.indicators import compute_indicators
from app.analysis.smc_engine import compute_dealing_range, compute_levels
from app.analysis.strategies import AVAILABLE_STRATEGIES, DEFAULT_STRATEGY, build_strategy_state
from app.analysis.summary import build_summary, determine_bias
from app.cache import get_or_fetch
from app.config import settings
from app.live.mexc_stream import mexc_stream_manager
from app.models import (
    AnalysisResponse,
    AssetType,
    Candle,
    StrategyState,
    SymbolSuggestion,
    TimeframeAnalysis,
    TimeframeKey,
    WatchlistEntry,
)
from app.notify import telegram
from app.notify.alerts import find_new_signals, format_signal_message
from app.providers.base import DataProvider, ProviderError
from app.providers.mexc import MexcProvider
from app.providers.twelvedata import TwelveDataProvider
from app.timeframes import DEFAULT_INTERVALS, IntervalChoice

logger = logging.getLogger("watchlist_alerts")
if getattr(sys, "frozen", False):
    FRONTEND_DIR = Path(sys._MEIPASS) / "frontend"  # type: ignore[attr-defined]
else:
    FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
WATCHLIST_POLL_SECONDS = 60

twelvedata_provider = TwelveDataProvider()
mexc_provider = MexcProvider()


def get_provider(asset_type: AssetType) -> DataProvider:
    return mexc_provider if asset_type == "crypto" else twelvedata_provider


async def _watchlist_alert_loop() -> None:
    """Background loop, independent of any browser tab: evaluates every
    enabled watchlist entry on its own chosen strategy and fires Telegram
    alerts for it — never for whatever symbol happens to be open on screen."""
    while True:
        await asyncio.sleep(WATCHLIST_POLL_SECONDS)
        if not telegram.is_configured():
            continue
        for entry in watchlist_store.list_entries():
            if not entry.enabled:
                continue
            provider = get_provider(entry.asset_type)
            for tf_key in entry.timeframes:
                try:
                    df = await provider.fetch_ohlcv(
                        entry.symbol, DEFAULT_INTERVALS[tf_key], settings.candles_per_timeframe
                    )
                    strategy = build_strategy_state(entry.strategy_name, df)
                    _dispatch_telegram_alerts(entry.symbol, tf_key, strategy)
                except Exception:
                    logger.exception("Watchlist check failed for %s [%s]", entry.symbol, tf_key)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_watchlist_alert_loop())
    yield
    task.cancel()


app = FastAPI(title="Liquidity Analysis Engine", lifespan=lifespan)


class StrategyParamsQuery(BaseModel):
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


class BacktestParamsQuery(BaseModel):
    initial_capital: float = 10000.0
    qty_pct_of_equity: float = 30.0
    commission_pct: float = 0.06
    slippage_pct: float = 0.02


@app.get("/api/symbols", response_model=list[SymbolSuggestion])
async def search_symbols(
    query: str = Query(..., min_length=1, max_length=20),
    asset_type: AssetType = Query("stock"),
) -> list[SymbolSuggestion]:
    try:
        results = await get_provider(asset_type).search_symbols(query)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [SymbolSuggestion(**r) for r in results]


def _dispatch_telegram_alerts(symbol: str, timeframe_key: TimeframeKey, strategy: StrategyState) -> None:
    if not telegram.is_configured():
        return
    fresh = find_new_signals(symbol, timeframe_key, strategy)
    for signal in fresh:
        message = format_signal_message(symbol, timeframe_key, strategy.name, signal)
        asyncio.create_task(telegram.send_message(message))


@app.get("/api/strategies", response_model=list[str])
async def list_strategies() -> list[str]:
    return AVAILABLE_STRATEGIES


@app.get("/api/watchlist", response_model=list[WatchlistEntry])
async def get_watchlist() -> list[WatchlistEntry]:
    return watchlist_store.list_entries()


class WatchlistAddRequest(BaseModel):
    symbol: str
    asset_type: AssetType
    strategy_name: str = DEFAULT_STRATEGY
    timeframes: list[TimeframeKey] = ["htf", "mtf", "ltf"]


@app.post("/api/watchlist", response_model=WatchlistEntry)
async def add_watchlist_entry(req: WatchlistAddRequest) -> WatchlistEntry:
    symbol = req.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    if req.strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {req.strategy_name}")
    return watchlist_store.add_entry(symbol, req.asset_type, req.strategy_name, req.timeframes)


@app.delete("/api/watchlist/{entry_id}")
async def delete_watchlist_entry(entry_id: str) -> dict:
    watchlist_store.remove_entry(entry_id)
    return {"ok": True}


@app.patch("/api/watchlist/{entry_id}", response_model=WatchlistEntry)
async def toggle_watchlist_entry(entry_id: str, enabled: bool = Query(...)) -> WatchlistEntry:
    entry = watchlist_store.set_enabled(entry_id, enabled)
    if entry is None:
        raise HTTPException(status_code=404, detail="Voce non trovata")
    return entry


@app.get("/api/analyze", response_model=AnalysisResponse)
async def analyze(
    symbol: str = Query(..., min_length=1, max_length=20),
    asset_type: AssetType = Query("stock"),
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

    provider = get_provider(asset_type)
    intervals: dict[TimeframeKey, str] = {"htf": htf_interval, "mtf": mtf_interval, "ltf": ltf_interval}

    async def fetch_timeframe(tf_key: TimeframeKey):
        interval = intervals[tf_key]
        cache_key = (f"{asset_type}:{symbol.upper()}", interval)

        async def do_fetch():
            return await provider.fetch_ohlcv(symbol, interval, settings.candles_per_timeframe)

        try:
            df = await get_or_fetch(cache_key, do_fetch)
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

        levels = compute_levels(df, tf_key)
        indicators = compute_indicators(df)
        bias = determine_bias(levels)
        dealing_range = compute_dealing_range(df, tf_key)
        strategy = build_strategy_state(strategy_name, df, strategy_params_dict)
        strategies[tf_key] = [strategy]
        backtests[tf_key] = run_backtest(df, strategy_params_dict, backtest_params_dict)
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
        timeframes[tf_key] = TimeframeAnalysis(
            interval=intervals[tf_key],
            candles=candles,
            levels=levels,
            indicators=indicators,
            bias=bias,
            dealing_range=dealing_range,
        )

    confluence_zones = compute_confluence(timeframes)
    current_price = timeframes["ltf"].candles[-1].close
    summary = build_summary(current_price, timeframes, confluence_zones)

    return AnalysisResponse(
        symbol=symbol.upper(),
        asset_type=asset_type,
        current_price=current_price,
        timeframes=timeframes,
        confluence_zones=confluence_zones,
        summary=summary,
        strategies=strategies,
        backtests=backtests,
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


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))
