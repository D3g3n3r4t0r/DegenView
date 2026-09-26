"""The Meme Sniper's own engine: a score with its reasons, and a trade that
could really have been made.

Request: "uguale per lo sniper di meme, dobbiamo rendere tutto piu'
professionale". Before this, the "Ready to pump" lane was the leftovers of
the serious-project filter (site, GitHub, AI verdict: noise for a meme),
ranked by buy share and turnover, the two numbers bots inflate most easily
(JIRACHI: 300 buys, 0 sells). And "good" meant +50% at the peak within
seven days, which nobody can sell at.

Two pieces, both pure functions so they can be tested and replayed:

1. `score()`: 0-100 from what matters for a meme, each part with the reason
   shown on the card. Two-way flow (real sells next to buys), average ticket
   (bots trade in dust), momentum that is not already parabolic, turnover
   against liquidity (wash trading shows as absurd turnover), depth (can a
   position get out), holder concentration and RugCheck's own warnings on
   insiders, bundles and the creator's past rugs.
2. The simulated trade (`open_trade` / `step_trade`): enter at the first
   price seen after the decision paying the DEX fee plus the price impact of
   TRADE_SIZE_USD on that liquidity, then take profit, stop loss or time
   stop, paying the same on the way out. The exit only happens if selling
   was possible (sells seen, liquidity above the floor); a token nobody can
   sell counts as a total loss. Prices come every ten minutes, so a stop is
   filled at the first sample past it: the gap is real, not modelled away.

What the memory learns from, and what the track record shows, is this
trade's net return, not the peak.
"""
from __future__ import annotations

import math

TRADE_SIZE_USD = 100.0
DEX_FEE = 0.003
TAKE_PROFIT = 0.50
STOP_LOSS = -0.30
MAX_HOLD_S = 48 * 3600
WIN_RET = 0.20                  # a trade that netted +20% after costs
IMPACT_CAP = 0.50

# Score parts and their maximum points (sum 100).
PARTS = {"flow": 25, "ticket": 15, "momentum": 20, "turnover": 15, "depth": 15, "holders": 10}
FLOW_MIN_TX = 20                # fewer trades in an hour: too thin to read
_RISK_WORDS = (
    (("rug",), 20, "creator has rugged before"),
    (("insider",), 10, "insider wallets detected"),
    (("bundl",), 10, "bundled launch"),
    (("sniper",), 6, "heavy sniping at launch"),
)
BANDS = ((60, "60+"), (40, "40-59"), (0, "under 40"))


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _ramp(x: float, lo: float, hi: float) -> float:
    """0 at lo, 1 at hi (either direction), clamped."""
    if hi == lo:
        return 1.0 if x >= hi else 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


# ---------------------------------------------------------------- score

def derived(market: dict | None, liq: float | None) -> dict:
    """Per-token numbers the score and the memory both read."""
    m = market or {}
    buys, sells = _num(m.get("buys_h1")) or 0.0, _num(m.get("sells_h1")) or 0.0
    tx = buys + sells
    vol = _num(m.get("vol_h1"))
    return {"tx_h1": tx, "avg_trade": (vol / tx) if vol is not None and tx else None,
            "turnover": (vol / liq) if vol is not None and liq else None,
            "chg_h6": _num(m.get("chg_h6"))}


def score(market: dict | None, liq: float | None, mcap: float | None, safety: dict | None = None,
          age_h: float | None = None) -> dict:
    """{score, parts, reasons, risks}. Every point comes with a sentence."""
    m = market or {}
    d = derived(m, liq)
    parts: dict[str, float] = {}
    reasons: list[str] = []
    risks: list[str] = []

    share = _num(m.get("buy_ratio"))
    tx = d["tx_h1"]
    if share is None or tx == 0:
        parts["flow"] = 0.0
        risks.append("no trades in the last hour")
    else:
        # Healthy: more buyers than sellers, but sellers exist. 100% buys is
        # not demand, it is a pool nobody can (or is allowed to) sell into.
        shape = (_ramp(share, 0.35, 0.55) if share < 0.55
                 else 1.0 if share <= 0.72 else 1 - _ramp(share, 0.72, 0.97))
        parts["flow"] = PARTS["flow"] * shape * min(1.0, tx / FLOW_MIN_TX)
        if share > 0.9:
            risks.append(f"one-way flow: {share:.0%} buys")
        elif shape >= 0.8 and tx >= FLOW_MIN_TX:
            reasons.append(f"two-way flow: {share:.0%} buys over {tx:.0f} trades")

    avg = d["avg_trade"]
    if avg is None:
        parts["ticket"] = 0.0
    else:
        # Bots and volume farms move dust; people buy tens to hundreds of dollars.
        parts["ticket"] = PARTS["ticket"] * _ramp(math.log10(max(avg, 0.01)), math.log10(5), math.log10(25))
        if avg < 5:
            risks.append(f"average trade ${avg:.2f}: bot activity")
        elif avg >= 25:
            reasons.append(f"average trade ${avg:,.0f}")

    h1, h6 = _num(m.get("chg_h1")), d["chg_h6"]
    # A price that rises with nobody selling is not a price yet.
    sold = min(1.0, (_num(m.get("sells_h1")) or 0.0) / 5)
    if h1 is None:
        parts["momentum"] = 0.0
    elif h1 > 200:
        parts["momentum"] = PARTS["momentum"] * 0.3
        risks.append(f"already +{h1:.0f}% in 1h: late")
    elif h1 >= 0 and (h6 is None or h6 >= 0):
        parts["momentum"] = PARTS["momentum"] * (0.6 + 0.4 * _ramp(h1, 0, 30))
        reasons.append(f"rising: {h1:+.0f}% in 1h" + (f", {h6:+.0f}% in 6h" if h6 is not None else ""))
    elif h1 > -20 and h6 is not None and h6 > 0:
        parts["momentum"] = PARTS["momentum"] * 0.5
        reasons.append(f"pullback ({h1:+.0f}% 1h) inside a {h6:+.0f}% 6h move")
    else:
        parts["momentum"] = 0.0
        if h1 <= -20:
            risks.append(f"falling: {h1:+.0f}% in 1h")

    parts["momentum"] *= sold
    turn = d["turnover"]
    if turn is None:
        parts["turnover"] = 0.0
    elif turn > 6:
        parts["turnover"] = PARTS["turnover"] * 0.2
        risks.append(f"volume {turn:.0f}x liquidity in 1h: wash trading?")
    else:
        parts["turnover"] = PARTS["turnover"] * _ramp(turn, 0.05, 0.3)
        if turn >= 0.3:
            reasons.append(f"active: 1h volume {turn:.1f}x liquidity")

    if liq:
        ratio = (liq / mcap) if mcap else None
        parts["depth"] = PARTS["depth"] * (0.6 * _ramp(liq, 8_000, 40_000)
                                           + 0.4 * (_ramp(ratio, 0.03, 0.10) if ratio is not None else 0.5))
        if liq >= 40_000:
            reasons.append(f"deep pool: ${liq / 1000:,.0f}k liquidity")
        elif liq < 12_000:
            risks.append(f"thin pool: ${liq / 1000:,.0f}k liquidity")
    else:
        parts["depth"] = 0.0

    s = safety or {}
    top = _num(s.get("top_holder_pct"))
    if top is None:
        parts["holders"] = PARTS["holders"] * 0.4          # not checked yet: neither good nor bad
    else:
        parts["holders"] = PARTS["holders"] * (1 - _ramp(top, 4, 15))
        if top <= 4:
            reasons.append(f"spread out: top wallet {top:.1f}%")
        elif top >= 10:
            risks.append(f"top wallet holds {top:.0f}%")

    penalty = 0.0
    names = " ".join(str(w).lower() for w in s.get("warnings") or [])
    for words, pts, text in _RISK_WORDS:
        if any(w in names for w in words):
            penalty += pts
            risks.append(text)
    if age_h is not None and age_h < 0.5:
        penalty += 5
        risks.append("under 30 minutes old: too early to read")

    total = max(0.0, min(100.0, sum(parts.values()) - penalty))
    return {"score": round(total, 1), "parts": {k: round(v, 1) for k, v in parts.items()},
            "reasons": reasons[:4], "risks": risks[:4]}


def band(value: float | None) -> str | None:
    if value is None:
        return None
    return next(label for floor, label in BANDS if value >= floor)


# ---------------------------------------------------------------- trade

def cost(liq: float | None) -> float:
    """One side: DEX fee plus price impact of the position on a constant
    product pool (liquidity counts both sides, so half of it is the depth)."""
    impact = 2 * TRADE_SIZE_USD / liq if liq else IMPACT_CAP
    return DEX_FEE + min(impact, IMPACT_CAP)


def open_trade(liq: float | None, now: float) -> dict:
    return {"at": now, "cost_in": round(cost(liq), 5), "open": True, "ret": None, "exit": None,
            "closed_at": None}


def _close(t: dict, gross: float, liq: float | None, why: str, now: float) -> None:
    out = 0.0 if gross <= -1 else cost(liq)
    net = (1 + max(gross, -1.0)) * (1 - t["cost_in"]) * (1 - out) - 1
    t.update(open=False, ret=round(net, 4), gross=round(gross, 4), exit=why, closed_at=now)


def step_trade(t: dict, gross: float | None, liq: float | None, now: float, *, can_sell: bool,
               rug: bool = False, final: bool = False) -> None:
    """One new price for an open trade. `gross` is the price change since
    the entry; `final` is the end of the watch window."""
    if not t or not t.get("open"):
        return
    if rug:
        _close(t, -1.0 if gross is None else gross, liq, "rug", now)
        return
    if gross is None:
        return
    held = now - t["at"]
    if gross <= STOP_LOSS and can_sell:
        _close(t, gross, liq, "stop", now)
    elif gross >= TAKE_PROFIT and can_sell:
        _close(t, TAKE_PROFIT, liq, "target", now)
    elif held >= MAX_HOLD_S and can_sell:
        _close(t, gross, liq, "time", now)
    elif final:
        # Never sellable in the whole window: the money is not coming back.
        _close(t, gross if can_sell else -1.0, liq, "time" if can_sell else "stuck", now)


def won(t: dict | None) -> bool | None:
    if not t or t.get("open") or t.get("ret") is None:
        return None
    return t["ret"] >= WIN_RET


# ---------------------------------------------------------------- track record

def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def summarize(rets: list[float]) -> dict:
    n = len(rets)
    return {"n": n,
            "win_rate": round(sum(r >= WIN_RET for r in rets) / n, 3) if n else None,
            "positive": round(sum(r > 0 for r in rets) / n, 3) if n else None,
            "median": round(_median(rets), 4) if n else None,
            "mean": round(sum(rets) / n, 4) if n else None}


def rules() -> dict:
    return {"size_usd": TRADE_SIZE_USD, "fee": DEX_FEE, "take_profit": TAKE_PROFIT, "stop_loss": STOP_LOSS,
            "max_hold_h": MAX_HOLD_S / 3600, "win_ret": WIN_RET}
