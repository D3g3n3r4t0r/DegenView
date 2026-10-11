"""Market-cap rank for YOUR TICKERS (board issue d46f02f7)."""
from app import market_rank


TICKERS = [
    {"symbol": "BTC", "rank": 1},
    {"symbol": "ETH", "rank": 2},
    {"symbol": "WBTC", "rank": 15},
    {"symbol": "BONK", "rank": 60},
    {"symbol": "ETH", "rank": 900},  # a small coin reusing the symbol
    {"symbol": "DEAD", "rank": 0},   # unranked
    {"symbol": "", "rank": 3},
]


def test_table_keeps_best_rank_per_symbol():
    table = market_rank.ranks_from_tickers(TICKERS)
    assert table["ETH"] == 2
    assert "DEAD" not in table
    assert "" not in table


def test_rank_for_pairs_and_bare_tickers():
    table = market_rank.ranks_from_tickers(TICKERS)
    assert market_rank.rank_for("BTCUSDT", table) == 1
    assert market_rank.rank_for("ETH/USDT", table) == 2
    assert market_rank.rank_for("ethbtc", table) == 2
    assert market_rank.rank_for("WBTC", table) == 15       # not read as W + BTC
    assert market_rank.rank_for("BONK@solana:DezXAZ8z7Pnrn", table) == 60
    assert market_rank.rank_for("NOPEUSDT", table) is None
    assert market_rank.rank_for("", table) is None
