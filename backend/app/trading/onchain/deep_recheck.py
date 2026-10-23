"""A dedicated, in-depth re-check of ONE token, on demand.

Lorenzo, 01/10: "in ogni review metti un tasto per forzare un ricontrollo
approfondito dedicato con deepseek". The board-wide review gives one short
line per project; this gives a single token a second, deeper opinion, with
the scout's red points and the earlier board call in front of it.
Since 22/10 it is a re-check by facts: see fact_check.py.
"""
from __future__ import annotations

import copy as _copy
import json
import logging
import time

from app.trading.onchain import depth, jstext, scout_recheck, storage

logger = logging.getLogger(__name__)

COOLDOWN_S = 6 * 3600     # guests only; account holders re-check whenever they want
DAILY_MAX = 40
WEEK_S = 7 * 86400         # Lorenzo, 01/10: the whole Top 50 re-checked once a week, from today
SWEEP_GAP_S = 90           # one token at a time, spaced: the weekly sweep is never a burst
TAP_GAP_S = 10             # everyone: a double tap must not pay DeepSeek twice

_STORE = storage.data_file("onchain_deep_recheck.json")


def _load() -> dict:
    try:
        d = json.loads(_STORE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return {"results": d.get("results") or {}, "calls": d.get("calls") or {}, "sweep": d.get("sweep") or {}}
    except Exception:
        pass
    return {"results": {}, "calls": {}, "sweep": {}}


_state = _load()
_running: set[str] = set()   # a double tap must not pay DeepSeek twice
_progress: dict[str, dict] = {}   # live steps of a running or just-finished re-check, by key


LOG_SHOWN = 8


def progress(chain: str, token: str) -> dict | None:
    """{running, started, steps: [{label, detail, state: done|run|fail}],
    log: the last lines of [{n, src, text, code}], what it is opening now}"""
    pr = _progress.get(_key(chain, token))
    if pr is None:
        return None
    return {**pr, "log": pr["log"][-LOG_SHOWN:]}


def _tracker(key: str, now: float):
    pr = {"running": True, "started": now, "steps": [], "log": []}
    _progress[key] = pr

    def log(src: str, text: str) -> dict:
        entry = {"n": pr["log"][-1]["n"] + 1 if pr["log"] else 0, "src": src, "text": text, "code": None}
        pr["log"].append(entry)
        del pr["log"][:-60]   # n keeps counting: the client follows it, not the position
        return entry

    def note(label: str | None, detail: str = "") -> None:
        steps = pr["steps"]
        if label is None:
            if steps:
                steps[-1]["detail"] = detail[:140]
            return
        for st in steps:
            if st["state"] == "run":
                st["state"] = "done"
        steps.append({"label": label, "detail": detail[:140], "state": "run", "at": time.time()})
    return pr, note, log


def _save() -> None:
    try:
        from app.atomic_write import write_text_atomic
        write_text_atomic(_STORE, json.dumps(_state, ensure_ascii=False))
    except Exception as exc:
        logger.info("deep recheck: save failed: %s", exc)


def reset_for_tests() -> None:
    _state["results"] = {}
    _state["calls"] = {}
    _state["sweep"] = {}
    _progress.clear()


def _key(chain: str, token: str) -> str:
    return f"{chain}:{token}"


def get(chain: str, token: str) -> dict | None:
    return tidy(_state["results"].get(_key(chain, token)))


def _text(x) -> str:
    return x if isinstance(x, str) else (x or {}).get("text") or ""


def tidy(res: dict | None) -> dict | None:
    """Each fact once, and the counts the list shows (AUREON, 08/10: the
    verdict's problems repeated the red points in other words, and "site
    built in JavaScript" was red next to a cleared "Site is a JavaScript
    shell"). Also applied to results saved before this rule."""
    if not res:
        return res
    claims = scout_recheck.merge_points([scout_recheck.read_gap(c) for c in res.get("claims") or [] if isinstance(c, dict)])
    problems: list = []
    for p in res.get("problems") or []:
        t = _text(p)
        # A problem the red points already carry is shown there, with its checked status.
        if scout_recheck.READ_GAP.search(t) or any(scout_recheck.same_fact(t, _text(q)) for q in claims + problems):
            continue
        problems.append(p)
    strengths: list = []
    for p in res.get("strengths") or []:
        if not any(scout_recheck.same_fact(_text(p), _text(q)) for q in strengths):
            strengths.append(p)
    out = {**res, "claims": claims, "problems": problems, "strengths": strengths}
    if claims:
        out.update({"cleared": sum(c.get("status") == "refuted" for c in claims),
                    "unverified": sum(c.get("status") == "unverified" for c in claims),
                    "confirmed": sum(c.get("status") == "confirmed" for c in claims)})
    return out


def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def wait_s(chain: str, token: str, now: float | None = None, limited: bool = True) -> int:
    now = now or time.time()
    if not limited:
        res = _state["results"].get(_key(chain, token))
        return max(0, int(res["at"] + TAP_GAP_S - now)) if res and res.get("at") else 0
    day = _day(now)
    if _state["calls"].get(day, 0) >= DAILY_MAX:
        midnight = (int(now // 86400) + 1) * 86400
        return max(0, int(midnight - now))
    res = _state["results"].get(_key(chain, token))
    if res and res.get("at"):
        left = int(res["at"] + COOLDOWN_S - now)
        if left > 0:
            return left
    return 0


class TooSoon(Exception):
    def __init__(self, wait_s: int):
        super().__init__(f"too soon: {wait_s}s")
        self.wait_s = wait_s


def next_in_sweep(board_keys: list[str], now: float) -> str | None:
    """The next Top 50 token the weekly sweep still owes a re-check, starting
    a new sweep (on the board as it is now) once a week has passed."""
    sw = _state["sweep"]
    # A week after the start a new round begins even if the last one stalled
    # (DeepSeek down for days): the board of today, not of a week ago.
    if not sw.get("started") or now - sw["started"] >= WEEK_S:
        sw.clear()
        sw.update({"started": now, "keys": list(board_keys), "done": [], "finished": None})
        _save()
    if sw.get("finished"):
        return None
    left = [k for k in sw.get("keys") or [] if k not in sw.get("done", [])]
    if not left:
        sw["finished"] = now
        _save()
        return None
    return left[0]


def _sweep_done(key: str) -> None:
    sw = _state["sweep"]
    if key not in sw.setdefault("done", []):
        sw["done"].append(key)
    _save()


async def sweep_loop(board_keys, start_delay_s: float = 300) -> None:
    """Re-checks the whole Top 50 once a week, one token every SWEEP_GAP_S.
    `board_keys()` gives the board's "chain:token" keys in rank order."""
    import asyncio
    import httpx
    await asyncio.sleep(start_delay_s)
    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "Mozilla/5.0 (LiquidityEngine)"}) as client:
        while True:
            pause = SWEEP_GAP_S
            try:
                key = next_in_sweep(board_keys(), time.time())
                if key is None:
                    pause = 3600
                elif await sweep_one(key, client) == "down":
                    pause = 1800
            except Exception:
                logger.exception("weekly re-check failed")
            await asyncio.sleep(pause)


async def sweep_one(key: str, client) -> str:
    """One token of the weekly sweep: "done", "busy" (re-checked moments ago,
    try later) or "down" (DeepSeek missing or unavailable: stop for now)."""
    chain, token = key.split(":", 1)
    try:
        res = await run(chain, token, client, limited=False)
        res["auto"] = True
        _save()
        _sweep_done(key)
    except TooSoon:
        return "busy"
    except LookupError:
        _sweep_done(key)      # left the board and the database
    except RuntimeError as exc:
        logger.info("weekly re-check: %s: %s", key, exc)
        if "not configured" in str(exc) or "unavailable" in str(exc):
            return "down"
        _sweep_done(key)      # an unreadable answer: move on, the button can retry
    return "done"


async def run(chain: str, token: str, client, now: float | None = None, ask=None, limited: bool = True) -> dict:
    key = _key(chain, token)
    if key in _running:
        raise TooSoon(TAP_GAP_S)
    if limited and _state["calls"].get(_day(now or time.time()), 0) + len(_running) >= DAILY_MAX:
        raise TooSoon(max(60, wait_s(chain, token, now)))
    _running.add(key)
    pr, note, log = _tracker(key, now or time.time())
    tok = scout_recheck.PROGRESS.set(note)
    trace = scout_recheck.TRACE.set(log)
    urgent = jstext.URGENT.set(True)
    scout_recheck.watch(client)
    try:
        return await _run(chain, token, client, now, ask, limited)
    except Exception as exc:
        if pr["steps"]:
            pr["steps"][-1]["state"] = "fail"
        pr["error"] = str(exc)[:140] if not isinstance(exc, TooSoon) else "too soon"
        raise
    finally:
        for st in pr["steps"]:
            if st["state"] == "run":
                st["state"] = "done"
        pr["running"] = False
        pr["ended"] = time.time()
        scout_recheck.PROGRESS.reset(tok)
        scout_recheck.TRACE.reset(trace)
        jstext.URGENT.reset(urgent)
        _running.discard(key)


async def _run(chain: str, token: str, client, now: float | None = None, ask=None, limited: bool = True) -> dict:
    from app.trading.onchain import leaderboard, judge, projects_db

    now = now or time.time()
    left = wait_s(chain, token, now, limited)
    if left > 0:
        raise TooSoon(left)
    key = _key(chain, token)
    scout_recheck.step("Loading the project and its last review")
    entry = leaderboard._entries.get(key)
    p = projects_db.get(chain, token)
    if entry is None and p is None:
        raise LookupError(key)
    if entry is None:
        entry = leaderboard.db_entry(p)
    copy = _copy.deepcopy(entry)
    if not copy.get("judge"):
        j = judge.get(chain, token)
        if j:
            copy["judge"] = j
    item = projects_db.as_item(p) if p is not None else copy

    # Lorenzo, 22/10: facts first (fact_check.py), measured again now, area by
    # area; the model answers only what no number answers.
    from app.trading.onchain import ai_veto, coordinated_sells, dev_payments, fact_check, market_peaks, wallet_clusters
    scout_recheck.step("Reading the wallet cluster report")
    state = await wallet_clusters.ensure(chain, token, copy.get("symbol") or "")
    cluster_facts = coordinated_sells.ai_facts(chain, token)
    cluster_line = coordinated_sells.ai_text(cluster_facts, state)
    scout_recheck.step_detail(cluster_line[:160])

    scout_recheck.step("Reading contract and holders again")
    tokenomics = (copy.get("pillars") or {}).get("tokenomics")
    try:
        fresh = (await leaderboard.retokenomics(chain, token, client) if key in leaderboard._entries
                 else await depth.analyze_tokenomics(chain, token, client,
                                                     pair_address=item.get("pair_address") or "",
                                                     liquidity_usd=float(item.get("liquidity_usd") or 0)))
        if fresh:
            tokenomics = fresh
            copy.setdefault("pillars", {})["tokenomics"] = fresh
    except Exception as exc:
        logger.info("deep recheck: tokenomics not read again: %s", exc)
    scout_recheck.step_detail((tokenomics or {}).get("fatal") or "read")

    try:
        ev = await scout_recheck.gather(copy, item, client)
    except Exception as exc:
        logger.info("deep recheck: second search failed: %s", exc)
        ev = {"found": [], "pages": [], "checked": [], "snippets": [], "gecko": None}
    board = leaderboard._entries.get(key) or copy
    areas = fact_check.all_areas(
        cluster_facts=cluster_facts, cluster_state=state, tokenomics=tokenomics, item={**item, **{
            k: board.get(k) for k in ("liquidity_usd", "market_cap") if board.get(k) is not None}},
        crashed=market_peaks.crashed(key.lower()), gate=leaderboard.usage_gate(board),
        usage_facts=judge.usage_facts(chain, token), ev=ev, pillars=copy.get("pillars") or {},
        dev_report=dev_payments.report(token) if chain == "solana" else None, now=now)
    c = fact_check.counts(areas)
    scout_recheck.step("Measured facts", f"{c['good']} good, {c['warn']} to watch, {c['bad']} serious, "
                                         f"{c['unknown']} not measured")

    ai = None
    from app import free_ai
    if free_ai.available():
        if ask is None:
            from app.notify import deepseek_desk
            ask = deepseek_desk.ask
        scout_recheck.step("Asking the AI about the product")
        try:
            raw = await ask([{"role": "system", "content": fact_check.SYSTEM},
                             {"role": "user", "content": "Project data:\n" + fact_check.ai_payload(copy, item, areas, ev)}],
                            kind="research", max_tokens=700, json_mode=True, purpose="deep_recheck", subject=key)
            ai = fact_check.parse_ai(raw)
        except Exception as exc:
            logger.info("deep recheck: AI unavailable: %s", exc)
        if limited:   # the daily cap is a guard on guests: owners and the weekly sweep do not use it up
            day = _day(now)
            _state["calls"][day] = _state["calls"].get(day, 0) + 1
        scout_recheck.step_detail((ai or {}).get("product") or "no readable answer: verdict from the facts alone")

    v = fact_check.verdict(areas, ai, ai_veto.excellent(board))
    on_board = key in leaderboard._entries
    prev = _state["results"].get(key) or {}
    old = copy.get("review")
    was_out = (old or {}).get("keep") is False or prev.get("keep") is False
    effect = ("not_on_board" if not on_board else "out" if not v["keep"] else "back" if was_out else "stays")
    score = ((copy.get("overall") or {}).get("score"))
    scout_recheck.step({"out": "Out of the Top", "back": "Back in the Top", "stays": "Stays in the Top",
                        "not_on_board": "Verdict"}[effect], v["reason"])
    result = {"v": 2, "keep": v["keep"], "score": round(score) if score is not None else None,
              "verdict": "keep" if v["keep"] else "drop", "reason": v["reason"][:220], "by": v["by"],
              "effect": effect, "effect_until": now + judge.REVIEW_TTL_S if effect == "out" else None,
              "areas": areas, "counts": c, "ai": ai, "clusters": cluster_line,
              "found": (ev.get("found") or [])[:8], "checked": (ev.get("checked") or [])[:12], "at": now,
              "before": {"keep": old.get("keep"), "reason": old.get("reason")} if old else None,
              # what the views written before v2 read
              "strengths": [{"text": a["line"], "evidence": ""} for a in areas if a["status"] == "good"][:4],
              "problems": [{"text": a["line"], "evidence": ""} for a in areas if a["status"] in ("bad", "warn")][:4],
              "claims": [], "unsupported": False}
    if ai is not None:
        result["ai"] = {**ai, "provider": getattr(ask, "provider", None)}
    if not v["keep"] and p is not None and p.get("status") in ("studied", "ranked"):
        result["dropped_from"] = {"status": p.get("status"), "rank": p.get("rank")}
    elif prev.get("dropped_from"):
        result["dropped_from"] = prev["dropped_from"] if not v["keep"] else None
    _state["results"][key] = result
    _save()

    # The site read now that it was not before: the stored pillars are stale.
    if any(str(f).startswith(scout_recheck.SITE_READ) for f in ev.get("found") or []):
        leaderboard.analyze_now(chain, token)
    if on_board:
        leaderboard._entries[key]["review"] = {"keep": v["keep"], "score": result["score"],
                                               "reason": v["reason"], "at": now, "deep": True}
        leaderboard._mark()

    if p is not None and p.get("status") in ("studied", "ranked"):
        if not v["keep"]:
            projects_db.set_standing(chain, token, "studied", p.get("score"), None, why=f"Re-check: {v['reason']}")
        elif (p.get("why") or "").startswith(("DeepSeek", "Re-check")):
            back = prev.get("dropped_from") or {}
            projects_db.set_standing(chain, token, back.get("status") or p.get("status"), p.get("score"),
                                     back.get("rank") if back else p.get("rank"), why="")
    return result
