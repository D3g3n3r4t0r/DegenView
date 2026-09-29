"""DeepSeek's memory of rug pulls: the database of every token we watched,
read back as cases, similar cases and circumstances.

Lorenzo, 27/09: "aggiungiamo anche una memoria; deepseek deve poter avere
memoria dei rugpull, le circostanze con cui sono avvenuti, per cui
accedere al database con tutti i dati delle crypto monitorate risulta
fondamentale".

The database is outcomes.py's journal (up to KEEP tokens): for each token
the numbers at the moment we decided (cap, liquidity, age, holder shares,
liquidity locked, each check's verdict, the market in its first hour) and
what really happened (rug and when and why, best and worst return). This
module only reads it:

- `similar(features)`: the closest past cases, for the judgement of a new
  alert (ai_scan.py): "5 similar: 3 rugs within 6h".
- `circumstances()`: how rugs differ from the rest, check by check and
  number by number, plus how long they took and how they happened.
- `lookup(query)`: a token by symbol or address, for the Telegram chat,
  where DeepSeek calls these as tools.

No model is trained here: outcomes.py already does that with its out-of-
sample gate. This is the same data made readable.
"""
from __future__ import annotations

import math
import time

from app.trading.onchain import outcomes

NUMS = ("mcap", "liq", "liq_mcap", "age_h", "top_holder_pct", "top10_pct", "lp_locked_pct", "buy_ratio")
CHECKS = ("security", "contract", "socials", "site")


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def case(e: dict, now: float | None = None) -> dict | None:
    """One journal entry, compact; None while its outcome is unknown."""
    o = outcomes.outcome(e, now)
    if o is None:
        return None
    f = e.get("features") or {}
    start = (e.get("entry") or {}).get("at") or e["at"]
    return {"symbol": e.get("symbol") or "?", "chain": e["chain"], "token": e.get("token_address"), "at": e["at"],
            "decision": e.get("decision"), "outcome": o,
            "hours_to_rug": round((e["rug_at"] - start) / 3600, 1) if e.get("rug") and e.get("rug_at") else None,
            "rug_why": e.get("rug_why") or "", "max_ret": e.get("max_ret"), "min_ret": e.get("min_ret"),
            **{k: _num(f.get(k)) for k in NUMS},
            **{f"{c}_ok": (f.get("checks") or {}).get(c, {}).get("ok") for c in CHECKS}}


def cases(now: float | None = None) -> list[dict]:
    now = now or time.time()
    return [c for c in (case(e, now) for e in outcomes.entries().values()) if c]


def _vec(f: dict) -> dict[str, float]:
    """Numbers on comparable scales; missing ones are left out."""
    out = {}
    for k, scale in (("mcap", "log"), ("liq", "log"), ("age_h", "log1p")):
        v = _num(f.get(k))
        if v is not None and v >= 0:
            out[k] = math.log10(v + 1) if scale == "log" else math.log1p(v) / 3
    for k in ("liq_mcap", "buy_ratio"):
        v = _num(f.get(k))
        if v is not None:
            out[k] = min(v, 2.0)
    for k in ("top_holder_pct", "top10_pct", "lp_locked_pct"):
        v = _num(f.get(k))
        if v is not None:
            out[k] = v / 100
    checks = f.get("checks") or {}
    for c in CHECKS:
        ok = f.get(f"{c}_ok", (checks.get(c) or {}).get("ok"))
        if ok is not None:
            out[c] = 1.0 if ok else 0.0
    return out


def distance(a: dict[str, float], b: dict[str, float]) -> float | None:
    common = [k for k in a if k in b]
    if len(common) < 3:
        return None
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in common) / len(common))


def similar(features: dict, chain: str | None = None, k: int = 5, now: float | None = None,
            pool: list[dict] | None = None) -> list[dict]:
    """The k decided cases closest to these features (same chain counts as closer)."""
    me = _vec(features)
    scored = []
    for c in pool if pool is not None else cases(now):
        d = distance(me, _vec(c))
        if d is None:
            continue
        scored.append((d * (0.8 if chain and c["chain"] == chain else 1.0), c))
    scored.sort(key=lambda x: x[0])
    return [c for _d, c in scored[:k]]


def summary(features: dict, chain: str | None = None, pool: list[dict] | None = None) -> str:
    """One line for a prompt: what happened to the closest cases."""
    near = similar(features, chain, pool=pool)
    if not near:
        return "no similar past cases"
    rugs = [c for c in near if c["outcome"] == "rug"]
    parts = [f"{len(near)} similar: {len(rugs)} rug"]
    if rugs:
        hours = sorted(c["hours_to_rug"] for c in rugs if c["hours_to_rug"] is not None)
        if hours:
            parts.append(f"after {', '.join(f'{h:g}h' for h in hours[:3])}")
    others = {}
    for c in near:
        if c["outcome"] != "rug":
            others[c["outcome"]] = others.get(c["outcome"], 0) + 1
    parts += [f"{n} {o}" for o, n in others.items()]
    return ", ".join(parts)


def _median(vals: list[float]) -> float | None:
    s = sorted(vals)
    if not s:
        return None
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def circumstances(chain: str | None = None, now: float | None = None) -> dict:
    """How the rugs differed from the rest: base rate, timing, how, and per
    number/check the rugs' median against the others'."""
    rows = [c for c in cases(now) if not chain or c["chain"] == chain]
    rugs = [c for c in rows if c["outcome"] == "rug"]
    rest = [c for c in rows if c["outcome"] != "rug"]
    out = {"n": len(rows), "rugs": len(rugs), "rug_rate": round(len(rugs) / len(rows), 3) if rows else None,
           "median_hours_to_rug": _median([c["hours_to_rug"] for c in rugs if c["hours_to_rug"] is not None]),
           "how": {}, "numbers": {}, "checks": {}}
    for c in rugs:
        why = (c["rug_why"] or "other").split(":")[0][:40]
        out["how"][why] = out["how"].get(why, 0) + 1
    for k in NUMS:
        a = [c[k] for c in rugs if c[k] is not None]
        b = [c[k] for c in rest if c[k] is not None]
        if len(a) >= 3 and len(b) >= 3:
            out["numbers"][k] = {"rug_median": round(_median(a), 3), "other_median": round(_median(b), 3)}
    for ck in CHECKS:
        key = f"{ck}_ok"
        a = [c[key] for c in rugs if c[key] is not None]
        b = [c[key] for c in rest if c[key] is not None]
        if len(a) >= 3 and len(b) >= 3:
            out["checks"][ck] = {"rug_ok_share": round(sum(a) / len(a), 3), "other_ok_share": round(sum(b) / len(b), 3)}
    return out


def circumstances_text(chain: str | None = None, now: float | None = None) -> str:
    """The same, in a few prompt lines."""
    s = circumstances(chain, now)
    if not s["n"]:
        return "Rug memory: no decided cases yet."
    lines = [f"Rug memory{f' ({chain})' if chain else ''}: {s['rugs']} rugs of {s['n']} decided "
             f"({(s['rug_rate'] or 0) * 100:.0f}%), median {s['median_hours_to_rug']}h to rug; how: "
             + ", ".join(f"{k} {v}" for k, v in sorted(s["how"].items(), key=lambda x: -x[1])[:4])]
    for k, v in s["numbers"].items():
        lines.append(f"- {k}: rugs {v['rug_median']} vs others {v['other_median']}")
    for k, v in s["checks"].items():
        lines.append(f"- {k} ok: rugs {v['rug_ok_share'] * 100:.0f}% vs others {v['other_ok_share'] * 100:.0f}%")
    return "\n".join(lines)


def lookup(query: str, now: float | None = None, limit: int = 5) -> list[dict]:
    """Tokens in the database by symbol (exact, any case) or address prefix,
    newest first, with their outcome (None = still being followed)."""
    q = (query or "").strip().lstrip("$")
    if not q:
        return []
    hits = []
    for e in outcomes.entries().values():
        if (e.get("symbol") or "").lower() == q.lower() or (len(q) >= 6 and (e.get("token_address") or "").lower().startswith(q.lower())):
            c = case(e, now) or {"symbol": e.get("symbol"), "chain": e["chain"], "token": e.get("token_address"),
                                 "at": e["at"], "decision": e.get("decision"), "outcome": None}
            hits.append(c)
    hits.sort(key=lambda c: -c["at"])
    return hits[:limit]
