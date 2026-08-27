from typing import Literal

from pydantic import BaseModel

from app.timeframes import IntervalChoice

AssetType = Literal["stock", "crypto"]
CryptoExchange = Literal["mexc", "binance"]
TimeframeKey = Literal["htf", "mtf", "ltf"]
LevelType = Literal["order_block", "fvg", "eqh", "eql", "bos", "choch"]


class SymbolSuggestion(BaseModel):
    symbol: str
    name: str
    exchange: str  # human label, e.g. "NASDAQ", "MEXC (USDT)", "Binance (USDT)"
    asset_type: AssetType
    provider: Literal["stock", "mexc", "binance"]


class Candle(BaseModel):
    time: int  # unix seconds, required by Lightweight Charts
    open: float
    high: float
    low: float
    close: float
    volume: float


class LiquidityLevel(BaseModel):
    type: LevelType
    direction: Literal["bullish", "bearish"]
    price_high: float
    price_low: float
    start_time: int
    end_time: int | None = None
    mitigated: bool = False
    label: str


class IndicatorSeries(BaseModel):
    name: str
    values: list[float | None]


class TimeframeAnalysis(BaseModel):
    interval: str
    candles: list[Candle]
    levels: list[LiquidityLevel]
    indicators: list[IndicatorSeries]
    bias: Literal["bullish", "bearish", "neutral"]
    dealing_range: tuple[float, float] | None = None


class StrategySignal(BaseModel):
    time: int
    type: Literal["entry_long", "entry_short", "exit_long", "exit_short", "flip_to_long", "flip_to_short"]
    price: float
    label: str


class StrategyState(BaseModel):
    name: str
    position: Literal["long", "short", "flat"]
    signals: list[StrategySignal]


class BacktestTrade(BaseModel):
    direction: Literal["long", "short"]
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_abs: float
    equity_after: float


class BacktestResult(BaseModel):
    initial_capital: float
    final_equity: float
    total_return_pct: float
    num_trades: int
    win_rate_pct: float | None
    max_drawdown_pct: float
    profit_factor: float | None
    equity_curve: list[tuple[int, float]]
    trades: list[BacktestTrade]


class User(BaseModel):
    id: str
    email: str
    password_hash: str
    telegram_chat_id: str = ""  # user pastes this in from their own DM with the shared bot


class WatchlistEntry(BaseModel):
    id: str
    owner_id: str
    symbol: str
    asset_type: AssetType
    exchange: CryptoExchange = "mexc"
    strategies: list[str] = []  # which strategies fire Telegram alerts for this ticker
    interval: IntervalChoice = "1d"  # which timeframe those strategies are evaluated on


class ConfluenceZone(BaseModel):
    price_high: float
    price_low: float
    timeframes: list[TimeframeKey]
    types: list[LevelType]
    score: int
    label: str


class AnalysisSummary(BaseModel):
    htf_bias: Literal["bullish", "bearish", "neutral"]
    text: str
    indicator_readout: list[str]
    long_term_context: list[str]
    top_confluence_zones: list[ConfluenceZone]
    unmitigated_gaps: int
    nearest_liquidity_above: float | None
    nearest_liquidity_below: float | None


class AnalysisResponse(BaseModel):
    symbol: str
    asset_type: AssetType
    current_price: float
    timeframes: dict[TimeframeKey, TimeframeAnalysis]
    confluence_zones: list[ConfluenceZone]
    summary: AnalysisSummary
    strategies: dict[TimeframeKey, list[StrategyState]]
    backtests: dict[TimeframeKey, BacktestResult]
    disclaimer: str = (
        "Strumento di analisi tecnica automatica. Non costituisce consulenza "
        "finanziaria, raccomandazione di investimento o segnale operativo."
    )
