"""Strategies backtests first.

Lorenzo, 28/09: "la parte di backtest abbia la priorità massima [...] popolare
quella schermata e poi fare tutte le altre attività". While any meme alert is
still waiting for its backtests, the other background jobs wait.
"""


def backtests_first() -> dict | None:
    """The meme backtest status while something is still pending, else None."""
    from app.trading.onchain import alert_track
    st = alert_track.backtest_status("meme")
    return st if st.get("pending", 0) > 0 else None
