"""La memoria del radar: cosa e' successo davvero ai token che abbiamo visto.

Lorenzo, dopo il rug pull su VISE (-93%) proposto dal radar: "dobbiamo
implementare una specie di coscienza, imparare dai segnali, da cosa
effettivamente succede, e migliorare il sistema".

Tre passi, a ogni giro (`TICK_S`):

1. **Diario.** Ogni token che il radar o i listing hanno proposto, provato o
   scartato entra qui una volta, con i numeri e i controlli di QUEL momento
   (cap, liquidita', eta', voto di ogni controllo di legit.py) e il prezzo
   d'ingresso. Solo lettura sugli store degli altri moduli.
2. **Esito.** Per `HORIZON_S` si rilegge prezzo e liquidita' del pool su
   DexScreener (30 pool per richiesta). Rug = liquidita' scesa sotto il
   `RUG_LIQ_LEFT` di quella d'ingresso, prezzo a `RUG_DROP` o pool sparito.
   Buono = in qualche momento `GOOD_UP` sopra l'ingresso: c'era un trend da
   prendere.
3. **Lezione.** Per ogni controllo e ogni numero: separa i rug dagli altri?
   (AUC: 0.5 = moneta, 1 = perfetto, sotto 0.5 = inganna). Poi una
   regressione logistica su tutti insieme; entra nel filtro (`judge`) solo
   se prevede i rug FUORI CAMPIONE (validazione a k fold) meglio di
   `MODEL_MIN_AUC`, con almeno `MODEL_MIN_N` esiti e `MODEL_MIN_RUGS` rug.
   Prima di allora osserva e basta: una regola imparata da dieci token e'
   rumore, e qui abbiamo gia' misurato quanto il rumore sembri un segnale.

Un token visto tardi (store vecchi al primo avvio) prende il prezzo
d'ingresso dalle candele del momento della decisione, pochi per giro per
non rubare GeckoTerminal al radar.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time

import httpx
import numpy as np

from app.trading.onchain.storage import data_file

logger = logging.getLogger(__name__)

_STORE_FILE = data_file("onchain_outcomes.json")
DEXSCREENER_PAIRS = "https://api.dexscreener.com/latest/dex/pairs"

TICK_S = 10 * 60
FIRST_TICK_DELAY_S = 90
HORIZON_S = 7 * 86400          # quanto si segue un token
RUG_FINAL_S = 3 * 86400        # dopo 3 giorni senza rug, "non rug" e' un esito
RUG_LIQ_LEFT = 0.20            # liquidita' rimasta sotto il 20% d'ingresso
RUG_DROP = -0.80               # o prezzo a -80%
CRASH_DROP = -0.50
GOOD_UP = 0.50
MISSING_TICKS = 3              # pool che non risponde piu' per 3 giri: tolto
LATE_S = 2 * 3600              # visto oltre 2 ore dopo la decisione: ingresso dalle candele
BACKFILL_PER_TICK = 4
KEEP = 5000

MODEL_MIN_N = 40
MODEL_MIN_RUGS = 8
MODEL_MIN_AUC = 0.65
MODEL_FOLDS = 5
BLOCK_RISK = 0.5               # sopra, il filtro scarta
SIGNAL_MIN_N = 12

# Quanto conta una decisione: un token proposto dopo essere stato solo
# provato prende l'ingresso del momento della proposta.
DECISIONS = {"rejected": 0, "tested": 1, "listed": 2, "proposed": 3}
PASSED = {"tested", "listed", "proposed"}
CHECK_KEYS = ("name", "security", "contract", "socials", "site", "github", "ai")
# Numeri dei controlli, non solo il voto. Dopo VISE: quanto tengono il primo
# wallet e i primi 10 (legit.holder_concentration).
FACT_KEYS = ("top_holder_pct", "top10_pct", "lp_locked_pct")
RISK_UP = {"top_holder_pct", "top10_pct"}   # qui un numero alto dovrebbe voler dire piu' rug
CHECK_LABELS = {"top_holder_pct": "Primo wallet %", "top10_pct": "Primi 10 wallet %",
                "lp_locked_pct": "Liquidità bloccata %",
                "name": "Nome", "security": "Sicurezza (RugCheck/GoPlus)", "contract": "Contratto (GoPlus)",
                "socials": "Social", "site": "Sito", "github": "GitHub", "ai": "Claude sul sito",
                "report": "Pagella complessiva", "mcap": "Capitalizzazione", "liq": "Liquidità",
                "liq_mcap": "Liquidità / cap", "age_h": "Età"}

_journal: dict[str, dict] = {}
_model: dict = {"active": False}
_state: dict = {"last_tick": 0.0, "error": ""}


# ------------------------------------------------------------------ archivio

def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if isinstance(raw, dict):
        _journal.update(raw.get("journal") or {})
        _state.update(raw.get("state") or {})


def _save() -> None:
    if len(_journal) > KEEP:
        for key in sorted(_journal, key=lambda k: _journal[k]["at"])[:len(_journal) - KEEP]:
            del _journal[key]
    try:
        _STORE_FILE.write_text(json.dumps({"journal": _journal, "state": _state}, ensure_ascii=False),
                               encoding="utf-8")
    except OSError:
        pass


def reset_for_tests() -> None:
    _journal.clear()
    _model.clear()
    _model["active"] = False
    _state.update(last_tick=0.0, error="")


_load()


# ------------------------------------------------------------------- diario

def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def features(item: dict, now: float | None = None) -> dict:
    """I numeri di un token al momento della decisione. Stessa funzione per
    il diario e per `judge`, cosi' il modello vede sempre le stesse cose."""
    now = now or time.time()
    cap, liq = _num(item.get("market_cap")), _num(item.get("liquidity_usd"))
    age = _num(item.get("age_hours"))
    if age is None and _num(item.get("created_at")):
        age = max(0.0, (now - float(item["created_at"])) / 3600)
    checks, facts = {}, {}
    for c in item.get("checks") or []:
        if c.get("key") in CHECK_KEYS:
            checks[c["key"]] = {"ok": c.get("ok"), "score": c.get("score")}
        facts.update({k: v for k, v in (c.get("facts") or {}).items() if k in FACT_KEYS})
    report = (item.get("report") or {}).get("score")
    return {"mcap": cap, "liq": liq, "liq_mcap": (liq / cap) if cap and liq else None, "age_h": age,
            "report": _num(report), "checks": checks, **{k: _num(facts.get(k)) for k in FACT_KEYS},
            "chain": item.get("chain"),
            "exception": bool(item.get("exception"))}


def observe(item: dict, decision: str, at: float | None = None, reason: str = "", source: str = "",
            now: float | None = None) -> dict | None:
    """Mette un token nel diario (una volta; una decisione piu' forte lo
    aggiorna). Ritorna la voce se e' nuova o cambiata."""
    now = now or time.time()
    token = item.get("token_address") or ""
    pair = item.get("pair_address") or ""
    if not token or not pair or not item.get("chain"):
        return None
    key = f"{item['chain']}:{token}"
    old = _journal.get(key)
    if old and DECISIONS[decision] <= DECISIONS[old["decision"]]:
        return None
    at = float(at or now)
    entry = {
        "chain": item["chain"], "symbol": item.get("symbol") or "", "name": item.get("name") or "",
        "token_address": token, "pair_address": pair, "pair_url": item.get("pair_url") or "",
        "decision": decision, "reason": reason, "source": source, "at": at, "seen_at": now,
        "features": features(item, at),
        "entry": None, "last": None, "min_ret": None, "max_ret": None, "min_liq": None,
        "misses": 0, "rug": None, "rug_at": None, "rug_why": "", "closed": False,
        "late": now - at > LATE_S, "previous": old["decision"] if old else None,
    }
    _journal[key] = entry
    return entry


def collect(now: float | None = None) -> int:
    """Legge le decisioni degli altri moduli. Import qui: legit importa
    questo modulo, e radar/listings importano legit."""
    from app.trading.onchain import listings, radar
    now = now or time.time()
    added = 0
    snap = radar.snapshot()
    for p in snap.get("proposals") or []:
        added += bool(observe(p, "proposed", p.get("found_at"), p.get("strategy") or "", "radar", now))
    for t in snap.get("tested") or []:
        added += bool(observe(t, "tested", None, "nessuna strategia", "radar", now))
    for item in listings.recent():
        added += bool(observe(item, "listed", item.get("found_at"), "", "listing", now))
    for r in listings.rejected():
        added += bool(observe(r, "rejected", r.get("at"), r.get("reason") or "", r.get("source") or "", now))
    return added


# --------------------------------------------------------------------- esito

def apply_sample(e: dict, price: float | None, liq: float | None, now: float) -> None:
    """Un nuovo prezzo per una voce: aggiorna minimi, massimi ed esito."""
    if e["closed"]:
        return
    if price is None:
        if e["entry"]:
            e["misses"] += 1
            if e["misses"] >= MISSING_TICKS:
                _mark_rug(e, now, "pool sparito")
        return
    e["misses"] = 0
    if not e["entry"]:
        e["entry"] = {"price": price, "liq": liq, "at": now, "from": "live"}
    base = e["entry"]["price"]
    ret = price / base - 1 if base else 0.0
    e["last"] = {"price": price, "liq": liq, "at": now, "ret": round(ret, 4)}
    e["min_ret"] = ret if e["min_ret"] is None else min(e["min_ret"], ret)
    e["max_ret"] = ret if e["max_ret"] is None else max(e["max_ret"], ret)
    if e["entry"].get("liq") is None and liq:
        e["entry"]["liq"] = liq  # ingresso dalle candele: la liquidita' si misura da qui
    entry_liq = e["entry"].get("liq")
    if liq is not None and entry_liq:
        ratio = liq / entry_liq
        e["min_liq"] = ratio if e["min_liq"] is None else min(e["min_liq"], ratio)
        if ratio <= RUG_LIQ_LEFT:
            _mark_rug(e, now, f"liquidità scesa al {ratio:.0%}")
    if e["rug"] is None and ret <= RUG_DROP:
        _mark_rug(e, now, f"prezzo {ret:+.0%}")
    if now - e["entry"]["at"] >= HORIZON_S:
        e["closed"] = True
        if e["rug"] is None:
            e["rug"] = False


def _mark_rug(e: dict, now: float, why: str) -> None:
    if e["rug"]:
        return
    e.update(rug=True, rug_at=now, rug_why=why, closed=True)


def outcome(e: dict, now: float | None = None) -> str | None:
    """rug / crollo / buono / piatto, oppure None finche' non si sa."""
    now = now or time.time()
    if not e.get("entry"):
        return None
    if e["rug"]:
        return "rug"
    if (e.get("max_ret") or 0) >= GOOD_UP:
        return "buono"
    if not e["closed"]:
        return None
    return "crollo" if (e.get("min_ret") or 0) <= CRASH_DROP else "piatto"


def rug_label(e: dict, now: float | None = None) -> bool | None:
    """True/False quando l'esito "rug" e' deciso, None altrimenti."""
    now = now or time.time()
    if not e.get("entry"):
        return None
    if e["rug"]:
        return True
    if e["closed"] or now - e["entry"]["at"] >= RUG_FINAL_S:
        return False
    return None


async def _sample(client: httpx.AsyncClient, now: float) -> int:
    open_by_chain: dict[str, list[dict]] = {}
    for e in _journal.values():
        if not e["closed"] and not (e["late"] and not e["entry"]):
            open_by_chain.setdefault(e["chain"], []).append(e)
    sampled = 0
    for chain, entries in open_by_chain.items():
        for i in range(0, len(entries), 30):
            batch = entries[i:i + 30]
            try:
                r = await client.get(f"{DEXSCREENER_PAIRS}/{chain}/{','.join(e['pair_address'] for e in batch)}")
                pairs = (r.json() or {}).get("pairs") or [] if r.status_code == 200 else None
            except (httpx.HTTPError, ValueError) as exc:
                logger.info("outcomes: DexScreener %s: %s", chain, exc)
                pairs = None
            if pairs is None:
                continue  # l'API non ha risposto: non e' un pool sparito
            by_pair = {(p.get("pairAddress") or "").lower(): p for p in pairs}
            for e in batch:
                p = by_pair.get(e["pair_address"].lower())
                price = _num(p.get("priceUsd")) if p else None
                liq = _num((p.get("liquidity") or {}).get("usd")) if p else None
                apply_sample(e, price, liq, now)
                sampled += 1
            await asyncio.sleep(0.3)
    return sampled


async def _backfill(now: float, limit: int = BACKFILL_PER_TICK) -> int:
    """Voci viste tardi: ingresso e minimi/massimi dalle candele."""
    from app.providers.base import ProviderError
    from app.providers.dexscreener import DexScreenerProvider, make_symbol
    todo = [e for e in _journal.values() if e["late"] and not e["entry"] and not e["closed"]]
    todo.sort(key=lambda e: -e["at"])
    provider = DexScreenerProvider()
    done = 0
    for e in todo[:limit]:
        if now - e["at"] > HORIZON_S:
            e["closed"] = True  # troppo vecchio per le candele a 15m
            continue
        try:
            df = await provider.fetch_ohlcv(make_symbol(e["symbol"] or "T", e["chain"], e["pair_address"]),
                                            "15m", 1000, token_address=e["token_address"])
        except ProviderError as exc:
            logger.info("outcomes: candele %s: %s", e["symbol"], exc)
            e["misses"] += 1
            if e["misses"] >= MISSING_TICKS:
                e["closed"] = True
            continue
        replay_candles(e, df)
        done += 1
    return done


def replay_candles(e: dict, df) -> None:
    """Prezzo d'ingresso alla prima candela dopo la decisione, poi minimo e
    massimo veri. La liquidita' storica non c'e': la si legge da ora in poi."""
    idx = df.index.tz_localize("UTC") if df.index.tz is None else df.index
    after = df[idx.map(lambda t: t.timestamp()) >= e["at"]]
    if after.empty:
        e["closed"] = True
        return
    base = float(after["open"].iloc[0])
    if base <= 0:
        e["closed"] = True
        return
    e["entry"] = {"price": base, "liq": None, "at": e["at"], "from": "candles"}
    e["min_ret"] = float(after["low"].min()) / base - 1
    e["max_ret"] = float(after["high"].max()) / base - 1
    last = float(after["close"].iloc[-1])
    e["last"] = {"price": last, "liq": None, "at": after.index[-1].timestamp(), "ret": round(last / base - 1, 4)}
    if e["min_ret"] <= RUG_DROP:
        low_at = after["low"].idxmin()
        _mark_rug(e, low_at.timestamp(), f"prezzo {e['min_ret']:+.0%}")


# ------------------------------------------------------------------- lezione

def auc(scores: list[float], labels: list[bool]) -> float | None:
    """Probabilita' che un rug abbia un valore piu' alto di un non-rug
    (pareggi a meta'). Mann-Whitney, senza dipendenze."""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    order = sorted((s, i) for i, s in enumerate(pos + neg))
    ranks = [0.0] * len(order)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and order[j + 1][0] == order[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k][1]] = (i + j) / 2 + 1
        i = j + 1
    r_pos = sum(ranks[:len(pos)])
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def _check_value(f: dict, key: str) -> float | None:
    c = (f.get("checks") or {}).get(key)
    if not c:
        return None
    if c.get("score") is not None:
        return float(c["score"])
    return {True: 100.0, False: 0.0}.get(c.get("ok"))


def _value(f: dict, key: str) -> float | None:
    if key in CHECK_KEYS:
        return _check_value(f, key)
    v = f.get(key)
    if v is None:
        return None
    return math.log10(v + 1) if key in ("mcap", "liq", "age_h") else float(v)


MODEL_KEYS = ("mcap", "liq", "liq_mcap", "age_h", "report") + FACT_KEYS + CHECK_KEYS


def _matrix(rows: list[dict], means: dict | None = None) -> tuple[np.ndarray, dict]:
    """Una riga per token. Un valore mancante prende la media e accende un
    indicatore: "non controllato" e' un'informazione, non uno zero."""
    cols = {k: [_value(f, k) for f in rows] for k in MODEL_KEYS}
    if means is None:
        means = {}
        for k, vals in cols.items():
            known = [v for v in vals if v is not None]
            means[k] = (sum(known) / len(known), (np.std(known) or 1.0)) if known else (0.0, 1.0)
    out = []
    for k in MODEL_KEYS:
        mu, sd = means[k]
        out.append([((v if v is not None else mu) - mu) / sd for v in cols[k]])
        out.append([float(v is None) for v in cols[k]])
    out.append([float(f.get("chain") == "solana") for f in rows])
    return np.array(out, dtype=float).T, means


def _fit(x: np.ndarray, y: np.ndarray, l2: float = 1.0, steps: int = 400, lr: float = 0.3) -> np.ndarray:
    xb = np.hstack([x, np.ones((len(x), 1))])
    w = np.zeros(xb.shape[1])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-xb @ w))
        grad = xb.T @ (p - y) / len(y) + l2 * np.r_[w[:-1], 0] / len(y)
        w -= lr * grad
    return w


def _predict(w: np.ndarray, x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-(np.hstack([x, np.ones((len(x), 1))]) @ w)))


def labelled(now: float | None = None) -> list[tuple[dict, bool]]:
    now = now or time.time()
    out = []
    for e in _journal.values():
        y = rug_label(e, now)
        if y is not None:
            out.append((e, y))
    return out


def train(now: float | None = None) -> dict:
    """Allena il modello dei rug e decide se merita di entrare nel filtro."""
    data = labelled(now)
    n, rugs = len(data), sum(y for _, y in data)
    model = {"active": False, "n": n, "rugs": rugs, "cv_auc": None, "why": ""}
    if n < MODEL_MIN_N or rugs < MODEL_MIN_RUGS or n - rugs < MODEL_MIN_RUGS:
        model["why"] = f"servono {MODEL_MIN_N} esiti con almeno {MODEL_MIN_RUGS} rug (ora {n}, {rugs} rug)"
        _model.clear()
        _model.update(model)
        return model
    rows = [e["features"] for e, _ in data]
    y = np.array([float(v) for _, v in data])
    # k fold deterministici: stesso diario, stesso verdetto.
    folds = np.arange(n) % MODEL_FOLDS
    pred = np.zeros(n)
    for k in range(MODEL_FOLDS):
        tr, te = folds != k, folds == k
        if y[tr].min() == y[tr].max():
            continue
        x_tr, means = _matrix([r for r, m in zip(rows, tr) if m])
        x_te, _ = _matrix([r for r, m in zip(rows, te) if m], means)
        pred[te] = _predict(_fit(x_tr, y[tr]), x_te)
    cv = auc(pred.tolist(), [bool(v) for v in y])
    x, means = _matrix(rows)
    w = _fit(x, y)
    model.update(cv_auc=round(cv, 3) if cv is not None else None, weights=w.tolist(), means=means)
    if cv is None or cv < MODEL_MIN_AUC:
        model["why"] = f"fuori campione separa i rug solo con AUC {cv or 0:.2f} (serve {MODEL_MIN_AUC})"
    else:
        model.update(active=True, why=f"separa i rug fuori campione con AUC {cv:.2f} su {n} esiti")
    _model.clear()
    _model.update(model)
    return model


def risk(item: dict) -> float | None:
    """Probabilita' di rug stimata dagli esiti passati, None se il modello
    non e' ancora affidabile."""
    if not _model.get("active"):
        return None
    x, _ = _matrix([features(item)], {k: tuple(v) for k, v in _model["means"].items()})
    return float(_predict(np.array(_model["weights"]), x)[0])


def judge(token: dict, checks: list[dict], report: dict | None) -> dict | None:
    """Il controllo "Memoria" per legit.assess, o None se non c'e' ancora
    abbastanza passato per dire qualcosa."""
    p = risk({**token, "checks": checks, "report": report})
    if p is None:
        return None
    ok = p < BLOCK_RISK
    detail = (f"somiglia ai rug passati: rischio {p:.0%}" if not ok
              else f"rischio rug {p:.0%} dagli esiti di {_model['n']} token")
    return {"key": "memory", "label": "Memoria", "ok": ok, "detail": detail,
            "score": int(round(100 * (1 - p)))}


def _rate(entries: list[dict], now: float) -> dict:
    outs = [outcome(e, now) for e in entries]
    done = [o for o in outs if o]
    n = len(done)
    return {"n": len(entries), "decided": n,
            "rug": done.count("rug"), "crollo": done.count("crollo"),
            "buono": done.count("buono"), "piatto": done.count("piatto"),
            "rug_rate": round(done.count("rug") / n, 3) if n else None,
            "good_rate": round(done.count("buono") / n, 3) if n else None}


def signals(now: float | None = None) -> list[dict]:
    """Per ogni controllo e numero: quanto separa i rug e quanto le salite.
    Ogni numero nel verso in cui dovrebbe proteggere (voto alto = meno rug,
    concentrazione alta = piu' rug): 1 = li prevede, 0.5 = inutile, <0.5 =
    inganna."""
    now = now or time.time()
    data = labelled(now)
    good = [(e, outcome(e, now) == "buono") for e in _journal.values() if outcome(e, now)]
    out = []
    for key in MODEL_KEYS:
        pairs = [(v, y) for e, y in data if (v := _value(e["features"], key)) is not None]
        gpairs = [(v, y) for e, y in good if (v := _value(e["features"], key)) is not None]
        if len(pairs) < SIGNAL_MIN_N:
            continue
        sign = 1 if key in RISK_UP else -1
        a = auc([sign * v for v, _ in pairs], [y for _, y in pairs])
        g = auc([-sign * v for v, _ in gpairs], [y for _, y in gpairs]) if len(gpairs) >= SIGNAL_MIN_N else None
        out.append({"key": key, "label": CHECK_LABELS.get(key, key), "n": len(pairs),
                    "rugs": sum(y for _, y in pairs),
                    "rug_auc": round(a, 3) if a is not None else None,
                    "good_auc": round(g, 3) if g is not None else None,
                    "verdict": _verdict(a)})
    out.sort(key=lambda s: -abs((s["rug_auc"] or 0.5) - 0.5))
    return out


def _verdict(a: float | None) -> str:
    if a is None:
        return "nessun rug o nessun non-rug"
    if a >= 0.7:
        return "prevede i rug"
    if a >= 0.6:
        return "aiuta un po'"
    if a > 0.4:
        return "non dice niente"
    return "inganna: voti alti, piu' rug"


def _brief(e: dict, now: float) -> dict:
    return {"chain": e["chain"], "symbol": e["symbol"], "pair_url": e["pair_url"], "decision": e["decision"],
            "reason": e["reason"], "at": e["at"], "outcome": outcome(e, now), "rug_why": e["rug_why"],
            "max_ret": e["max_ret"], "min_ret": e["min_ret"], "report": e["features"].get("report")}


def lessons(now: float | None = None) -> dict:
    """Tutto quello che il diario ha imparato, per l'API e la pagina."""
    now = now or time.time()
    entries = list(_journal.values())
    passed = [e for e in entries if e["decision"] in PASSED]
    rejected = [e for e in entries if e["decision"] == "rejected"]
    slipped = sorted((e for e in passed if e["rug"]), key=lambda e: -(e["rug_at"] or 0))
    missed = sorted((e for e in rejected if outcome(e, now) == "buono"), key=lambda e: -(e["max_ret"] or 0))
    sig = signals(now)
    notes = []
    for s in sig[:3]:
        if s["rug_auc"] is not None and s["verdict"] != "non dice niente":
            notes.append(f"{s['label']}: {s['verdict']} (AUC {s['rug_auc']:.2f} su {s['n']})")
    p, r = _rate(passed, now), _rate(rejected, now)
    if p["rug_rate"] is not None and r["rug_rate"] is not None:
        notes.insert(0, f"Passati dal filtro: {p['rug_rate']:.0%} rug; scartati: {r['rug_rate']:.0%} rug")
    return {
        "tracked": len(entries), "open": sum(not e["closed"] for e in entries),
        "passed": p, "rejected": r,
        "by_decision": {d: _rate([e for e in entries if e["decision"] == d], now) for d in DECISIONS},
        "signals": sig, "model": {k: v for k, v in _model.items() if k not in ("weights", "means")},
        "slipped": [_brief(e, now) for e in slipped[:10]],
        "missed": [_brief(e, now) for e in missed[:10]],
        "notes": notes, "last_tick": _state["last_tick"], "error": _state["error"],
        "rules": {"horizon_days": HORIZON_S / 86400, "rug_liq_left": RUG_LIQ_LEFT, "rug_drop": RUG_DROP,
                  "good_up": GOOD_UP, "model_min_n": MODEL_MIN_N, "model_min_auc": MODEL_MIN_AUC},
    }


# --------------------------------------------------------------------- giro

async def tick(now: float | None = None) -> dict:
    now = now or time.time()
    try:
        collect(now)
        async with httpx.AsyncClient(timeout=20.0) as client:
            await _sample(client, now)
        await _backfill(now)
        train(now)
        _state["error"] = ""
    except Exception as exc:
        logger.exception("outcomes: giro fallito")
        _state["error"] = str(exc)[:200]
    _state["last_tick"] = now
    _save()
    return _state


async def outcomes_loop() -> None:
    await asyncio.sleep(FIRST_TICK_DELAY_S)
    train()
    while True:
        await tick()
        await asyncio.sleep(TICK_S)
