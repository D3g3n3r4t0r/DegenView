import asyncio
import itertools
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
    CryptoExchange,
    StrategyState,
    SymbolSuggestion,
    TimeframeAnalysis,
    TimeframeKey,
    WatchlistEntry,
)
from app.notify import telegram
from app.notify.alerts import find_new_signals, format_signal_message
from app.pine import PineError, PineInterpreter, is_strategy_style, parse_program, scan_inputs
from app.pine import storage as pine_storage
from app.providers.base import DataProvider, ProviderError
from app.providers.binance import BinanceProvider
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
binance_provider = BinanceProvider()


def get_provider(asset_type: AssetType, exchange: CryptoExchange = "mexc") -> DataProvider:
    if asset_type != "crypto":
        return twelvedata_provider
    return binance_provider if exchange == "binance" else mexc_provider


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
            provider = get_provider(entry.asset_type, entry.exchange)
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


async def _safe_search(
    provider: DataProvider, query: str, asset_type: AssetType, provider_id: str
) -> list[SymbolSuggestion]:
    try:
        results = await provider.search_symbols(query)
    except ProviderError:
        return []  # one source being down shouldn't sink the combined search
    return [SymbolSuggestion(**r, asset_type=asset_type, provider=provider_id) for r in results]


def _interleave(*lists: list) -> list:
    """Round-robin merge so one source's larger result count (typically
    stocks) doesn't crowd the others out of a capped combined list."""
    out = []
    for group in itertools.zip_longest(*lists):
        out.extend(item for item in group if item is not None)
    return out


@app.get("/api/symbols", response_model=list[SymbolSuggestion])
async def search_symbols(query: str = Query(..., min_length=1, max_length=20)) -> list[SymbolSuggestion]:
    # Single unified search across stocks and both crypto exchanges — no
    # upfront "stock vs crypto" toggle. The user picks the asset from results
    # that already say which market/exchange it's on.
    stock_res, binance_res, mexc_res = await asyncio.gather(
        _safe_search(twelvedata_provider, query, "stock", "stock"),
        _safe_search(binance_provider, query, "crypto", "binance"),
        _safe_search(mexc_provider, query, "crypto", "mexc"),
    )
    return _interleave(stock_res, binance_res, mexc_res)[:12]


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

    async def do_fetch():
        return await provider.fetch_ohlcv(symbol, interval, settings.candles_per_timeframe)

    try:
        df = await get_or_fetch((f"pine:{req.asset_type}:{req.exchange}:{symbol.upper()}", interval), do_fetch)
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
        roles = {"entry_long", "entry_short", "exit_long", "exit_short"}
        mapped = set((req.signal_map or {}).keys())
        if not roles.issubset(mapped):
            return {
                "needs_mapping": True,
                "candidates": interp.boolean_candidates(),
                "warning": (
                    "Questo script non usa strategy.entry/close: seleziona quali variabili booleane "
                    "corrispondono a entry_long / entry_short / exit_long / exit_short."
                ),
            }

    strategy = build_strategy_state(f"Script: {_meta['name']}", df, signals=signals)
    backtest = run_backtest(df, None, req.backtest_params.model_dump(), signals=signals)
    return {"needs_mapping": False, "strategy": strategy.model_dump(), "backtest": backtest.model_dump()}


@app.get("/api/watchlist", response_model=list[WatchlistEntry])
async def get_watchlist() -> list[WatchlistEntry]:
    return watchlist_store.list_entries()


class WatchlistAddRequest(BaseModel):
    symbol: str
    asset_type: AssetType
    exchange: CryptoExchange = "mexc"
    strategy_name: str = DEFAULT_STRATEGY
    timeframes: list[TimeframeKey] = ["htf", "mtf", "ltf"]


@app.post("/api/watchlist", response_model=WatchlistEntry)
async def add_watchlist_entry(req: WatchlistAddRequest) -> WatchlistEntry:
    symbol = req.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    if req.strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategia sconosciuta: {req.strategy_name}")
    return watchlist_store.add_entry(symbol, req.asset_type, req.strategy_name, req.timeframes, exchange=req.exchange)


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
        cache_key = (f"{asset_type}:{exchange}:{symbol.upper()}", interval)

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
        backtests[tf_key] = run_backtest(df, strategy_params_dict, backtest_params_dict, strategy_name=strategy_name)
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
