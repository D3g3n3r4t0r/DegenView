"""La classifica dei progetti migliori: il Gem Finder.

Dal 25/09 non legge piu' il radar (Lorenzo: "il cacciatore di gemme non
deve scansionare il mercato degli ultimi 15 minuti [...] la ricerca al
minuto delle cose che escono deve stare sullo sniper, non qui"). Le fonti
sono solo di ricerca (`discovery.py`: CoinGecko, GitHub, profili) piu' i
riferimenti che Lorenzo ha indicato; il pilastro "site" e' la ricerca di
`research.py`. Il testo sotto racconta la prima versione.

Lorenzo: "una specie di leaderboard [...] primo posto, secondo posto, terzo
posto [...] una classifica dinamica, non fissa, aggiornata in tempo reale
[...] rigoroso [...] da quanto e' che sono usciti [...] e ampliamo anche la
chain per i token lanciati su Pump Fun".

Da dove arrivano i progetti:
- i listing verificati (`listings.recent()`) e le proposte e i token provati
  dal radar (`radar.snapshot()`): hanno gia' passato `legit.assess`;
- pump.fun e i progetti fuori dai limiti del radar (tipo DREGG) li porta il
  radar stesso: qui si legge solo quello che ha salvato, una fonte sola.

Ogni progetto passa da `depth.analyze` (GitHub, sito, tokenomics). Chi viene
bocciato su un pilastro esce e non rientra; chi ha un dato in attesa resta
fuori finche' non arriva. Il punteggio si rifa' da solo: tokenomics ogni
20 minuti (i portafogli cambiano), GitHub ogni 2 ore, sito ogni 12. Cap e
liquidita' ogni minuto da DexScreener. La regola della gemma e' quella del
radar: sopra i $100k solo con tutti e tre i pilastri eccellenti.

L'eccezione (Lorenzo, 24/09: "dregg va bene anche se ha 21 gg e supera i 2
mln, progetti in quel modo voglio che siano eccezione in quanto tecnicamente
incredibili su github"): oltre i 21 giorni o i $2M si entra solo se il radar
l'ha ammesso come eccezione, con la sua stessa regola
(`legit.github_shortfall` e `legit.gem_shortfall`): una regola sola.

Il riferimento (Lorenzo, 24/09: "mi devi mettere drag al primo posto in
assoluto con menzione d'onore"): DREGG sta sempre primo, e gli altri si
ordinano per qualita' (i tre pilastri) e somiglianza tecnica a DREGG
(`benchmark.py`), 70/30.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from app.sniper.quality import _looks_like_meme
from app.trading.onchain import (benchmark, big_coins, code_review, consistency, depth, discovery, gem_track, judge, legit, narrative_map,
                                  narratives, priority, projects_db, radar, research, storage, traction)

logger = logging.getLogger(__name__)

_STORE_FILE = storage.data_file("onchain_leaderboard.json")

TICK_S = 10
MARKET_POLL_S = 60
DEX_TOKENS = "https://api.dexscreener.com/tokens/v1/{chain}/{addresses}"

STALE_S = {"tokenomics": 20 * 60, "github": 2 * 3600, "site": 12 * 3600}
PENDING_RETRY_S = 3 * 60
PENDING_GIVE_UP_S = 6 * 3600       # un dato che non arriva in 6 ore non arrivera'
MAX_AGE_DAYS = radar.AGE_MAX_DAYS  # oltre, non e' piu' un progetto nuovo, salvo eccezioni
MAX_ENTRIES = 400
KEEP_EXCLUDED = 60
ANALYZE_CONCURRENCY = 5   # was 3: "la scansione complessiva e' lenta" (27/09)
# The project database (projects_db): how much of it the board takes in and
# refreshes per step.
DB_FEED_PER_TICK = 6
DB_FEED_MAX_WAITING = 20            # unanalysed entries in the working set before feeding more
DB_MARKET_S = 60
DB_MARKET_BATCH = 150               # 5 DexScreener requests a minute
BOARD_SIZE = 50
SIMILARITY_WEIGHT = 0.30
# Use and price (traction.py, DefiLlama): a lift for the projects it lists,
# never a penalty for the many microcaps it does not.
TRACTION_WEIGHT = 0.10
VALUE_WEIGHT = 0.05
MIN_PILLAR = 35                    # sotto, un pilastro e' troppo debole per stare in classifica
# Sopra i $100k non servono piu' tutti i pilastri eccellenti: basta il
# punteggio finale (Lorenzo, 28/09: "sta cosa dei pilastri a 85 va
# migliorata"). Il giudice di DeepSeek puo' ammettere chi le regole
# escludono, o bocciare chi passa.
BIG_MIN_SCORE = 80
JUDGE_WEIGHT = 0.5
# Progetti trovati dallo scan dedicato (discovery): l'eta' conta poco, la cap
# si' ("sotto 2-3 milioni, non oltre"), e la qualita' deve essere vera.
SERIOUS_SOURCES = ("coingecko", "dexscreener", "github", "reference", "jupiter", "defillama")
RADAR_SOURCES = ("radar", "listing")   # before 25/09: fresh launches, now the Meme Sniper's
# Projects Lorenzo found himself: always examined, never pinned.
REFERENCES = (
    {"chain": "solana", "token_address": "6SjVTj1VGwFSXn7wEjwFm77LvACeTqB7sQUebYKX8Ds5", "symbol": "ROUTER",
     "name": "Solrouter", "website": "https://solrouter.com", "websites": ["https://docs.solrouter.com"]},
    # Lorenzo, 29/09: "roba seria tipo AUERON, STEALF, pfwa, GRID dove cavolo sono".
    {"chain": "solana", "token_address": "G5W6LwkLeoj6rZqBP1y3KT8k6Cz6rXGJmMNU3TArXtXw", "symbol": "STEALF",
     "name": "Stealf", "website": "https://www.stealf.xyz/"},
    {"chain": "robinhood", "token_address": "0xa934bA4F59070149d37A93F8A002Af79BAe35563", "symbol": "PFWA",
     "name": "predict FWA", "website": "https://www.pfwa.fun/", "websites": ["https://www.pfwa.fun/docs"]},
    {"chain": "robinhood", "token_address": "0x727701F88f09Fed71eb217Bcea88b3F314CF7079", "symbol": "GRID",
     "name": "GRID by Virtuals", "website": "https://www.gridarena.xyz/"},
)
# A researcher's floor: an existing project, not a launch.
MIN_AGE_DAYS = 14
MIN_LIQUIDITY_USD = 10_000
# Early gems. Request: "quando la market cap e' sotto i 50k e fondamentali
# ci sono, voglio che il sistema lo evidenzi che potrebbe valere la pena di
# comprare un po'". Below EARLY_CAP_USD a pool is thinner, so the floor is
# lower; the fundamentals are not: public code and every pillar solid.
EARLY_CAP_USD = 50_000
EARLY_MIN_LIQUIDITY_USD = 5_000
EARLY_MIN_PILLAR = 60
EARLY_MIN_SCORE = 65
ALERTS_PER_TICK = 5
SERIOUS_CAP_MAX_USD = discovery.CAP_MAX
# Lorenzo (28/09): "per gemme solitamente si intende roba di capitalizzazione
# bassa [...] massimo 10 milioni". A hard ceiling for every entry, checked on
# the token's global cap too: AAVE's Solana copy showed $585k while AAVE
# is worth $2.2B, and a local pool cap cannot tell the two apart.
BOARD_CAP_MAX_USD = 10_000_000
CG_CONTRACT = "https://api.coingecko.com/api/v3/coins/{platform}/contract/{address}"
CG_PLATFORM = {"solana": "solana", "robinhood": "robinhood"}
GLOBAL_CAP_EVERY_S = 15            # one CoinGecko lookup per gap, shared with discovery
GLOBAL_CAP_TTL_S = 24 * 3600
# DeepSeek re-reads the whole board (judge.review_board): every two hours,
# or ten minutes after the board changes. Its score weighs in the rank; a
# drop keeps the project off for judge.REVIEW_TTL_S.
REVIEW_EVERY_S = 2 * 3600
REVIEW_MIN_GAP_S = 10 * 60
REVIEW_WEIGHT = 0.3
# DeepSeek reads the code of each project (code_review.py): complexity and
# innovation weigh in the rank, one project at a time.
CODE_WEIGHT = 0.2
CODE_EVERY_S = 60
# Scan less, complete more (Lorenzo, 28/09: "quando raggiungiamo un bel bacino
# fermiamo la scansione e concentriamoci su completare le informazioni").
# Past POOL_TARGET projects that passed the filters, discovery of new ones
# pauses while more than BACKLOG_LOW of them still miss a piece (analysis,
# DeepSeek's report, the code reading); once nearly complete, one slow
# discovery round every DISCOVERY_SLOW_S keeps the pool fresh.
POOL_TARGET = 300
BACKLOG_LOW = 10
DISCOVERY_SLOW_S = 6 * 3600
CODE_RETRY_S = 6 * 3600        # a failed reading waits: GitHub allows few calls an hour
SERIOUS_AGE_MAX_DAYS = 3 * 365
SERIOUS_MIN_PILLAR = 60
SERIOUS_MIN_GITHUB = 70
# Without public code the site and the tokenomics must carry the project,
# and it ranks below an equal project that shows its code.
NO_GITHUB_MIN_PILLAR = {"site": 70, "tokenomics": 60}
NO_GITHUB_PENALTY = 10.0
RULES_VERSION = 5              # 2: "no GitHub" stopped being a ban; 3: radar launches out;
                               # 4: research read by reader.py, older bans and readings dropped;
                               # 5: reader recognises research-stage code and stated limits
CAP_MAX_USD = radar.MCAP_MAX_USD

_entries: dict[str, dict] = {}     # chain:token
_excluded: list[dict] = []
_gone: dict[str, float] = {}       # chain:token bocciati: non si riesaminano
_busy: set[str] = set()
_tasks: set[asyncio.Task] = set()
_slots = asyncio.Semaphore(ANALYZE_CONCURRENCY)
_state = {"version": 0, "examined": 0, "last_tick": 0.0, "last_market": 0.0,
          "sources": {}, "board": []}
_alerted: set[str] = set()          # "new:<key>" / "early:<key>": alerts already sent
_outbox: list[tuple[str, str]] = []
_alert_hooks: list = []
_priming = False
_dirty = False


def _key(chain: str, token: str) -> str:
    return f"{chain}:{token}"


# ------------------------------------------------------------------ memoria

def _load() -> None:
    try:
        raw = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(raw, dict):
        _entries.update({k: v for k, v in (raw.get("entries") or {}).items()
                         if isinstance(v, dict) and v.get("source") not in RADAR_SOURCES})
        rules = int(raw.get("rules") or 1)
        if rules < 5:
            # Research pillars scored before the reader existed: read them again now.
            for e in _entries.values():
                (e.get("pillars") or {}).pop("site", None)
                (e.get("checked_at") or {}).pop("site", None)
        # Bans under older rules (no GitHub, the old site score) are lifted.
        if rules >= RULES_VERSION:
            _excluded.extend(x for x in raw.get("excluded") or [] if isinstance(x, dict))
            _gone.update(raw.get("gone") or {})
        _state["examined"] = int(raw.get("examined") or 0)
        _alerted.update(raw.get("alerted") or [])
        # First start with alerts: what is already on the board is not news.
        global _priming
        _priming = "alerted" not in raw
        _rank()
        _priming = False


def _save() -> None:
    global _dirty
    _dirty = False
    try:
        _STORE_FILE.write_text(json.dumps({"entries": _entries, "excluded": _excluded, "gone": _gone,
                                           "examined": _state["examined"], "rules": RULES_VERSION,
                                           "alerted": sorted(_alerted)}, ensure_ascii=False),
                               encoding="utf-8")
    except OSError:
        pass
    gem_track.save()


def reset_for_tests() -> None:
    _alerted.clear()
    _outbox.clear()
    _alert_hooks.clear()
    gem_track.reset_for_tests()
    big_coins.reset_for_tests()
    traction.reset_for_tests()
    _entries.clear()
    _excluded.clear()
    _gone.clear()
    _busy.clear()
    _state.update(version=0, examined=0, last_tick=0.0, last_market=0.0, sources={}, board=[],
                  reviewed_at=0.0, reviewed_board=[], reviewing=False, code_reading=False, code_at=0.0, db_board=[],
                  narr_mapping=False, top_filling=False, top_fill_at=0.0, top_synced_at=0.0, auditing=False)
    _top_tried.clear()
    _top_rank.clear()
    set_top_source(None)


# ------------------------------------------------------------------- fonti

def merge_narratives(hint: list[str] | None, site: list[str] | None, more: list[str] | None) -> list[str]:
    """Hint keys first (the category the coin was found in), then the rest."""
    return list(dict.fromkeys([*(hint or []), *(site or []), *(more or [])]))


def add(item: dict, source: str, now: float | None = None) -> bool:
    """Un progetto da esaminare. False se c'e' gia' o e' gia' stato bocciato."""
    chain, token = item.get("chain"), item.get("token_address")
    if not chain or not token:
        return False
    k = _key(chain, token)
    now = now or time.time()
    try:
        projects_db.upsert(item, source, now)
    except Exception:
        logger.exception("classifica: database non scritto per %s", k)
    # The database decides when a rejected project deserves a second look.
    if benchmark.is_benchmark(chain, token) or source in ("reference", "database"):
        _gone.pop(k, None)
    if k in _gone:
        return False
    fresh = {f: item[f] for f in ("market_cap", "liquidity_usd", "website", "github", "socials", "pair_url",
                                  "report", "scan_url", "checks", "exception", "github_verified", "description",
                                  "categories", "websites", "narratives_hint") if item.get(f)}
    if k in _entries:
        _entries[k].update(fresh)
        return False
    launched = item.get("launched_at") or item.get("created_at")
    if not launched and item.get("age_hours") is not None:
        launched = now - float(item["age_hours"]) * 3600
    _entries[k] = {
        "chain": chain, "token_address": token, "pair_address": item.get("pair_address") or "",
        "symbol": item.get("symbol") or "?", "name": item.get("name") or item.get("symbol") or "?",
        "source": source, "found_at": now, "launched_at": launched,
        "image": item.get("image"), "bonding": bool(item.get("bonding")),
        "bonding_curve": item.get("bonding_curve"), "associated_bonding_curve": item.get("associated_bonding_curve"),
        "pillars": {}, "checked_at": {}, "rank": None, **fresh,
    }
    _state["examined"] += 1
    _mark()
    return True


def collect_saved() -> int:
    """The benchmark and the references Lorenzo named. Nothing from the
    radar: fresh launches are the Meme Sniper's."""
    n = add(benchmark.seed_item(), "riferimento")
    for item in REFERENCES:
        n += add(dict(item), "reference")
    return n


def is_big(item: dict, now: float | None = None) -> bool:
    """Fuori dai limiti del radar: puo' entrare solo come eccezione."""
    now = now or time.time()
    launched = item.get("launched_at")
    return (float(item.get("market_cap") or 0) > CAP_MAX_USD
            or bool(launched and now - launched > MAX_AGE_DAYS * 86400))


def apply_market(pairs: list[dict]) -> None:
    """Cap, liquidita', variazione e data del pool piu' liquido di ogni token."""
    best: dict[str, dict] = {}
    for p in pairs:
        token = (p.get("baseToken") or {}).get("address")
        k = _key(p.get("chainId") or "", token or "")
        if k not in _entries:
            continue
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
        if k not in best or liq > float((best[k].get("liquidity") or {}).get("usd") or 0):
            best[k] = p
        created = (p.get("pairCreatedAt") or 0) / 1000
        e = _entries[k]
        if created and (not e.get("launched_at") or created < e["launched_at"]):
            e["launched_at"] = created
    for k, p in best.items():
        e = _entries[k]
        cap = p.get("marketCap") or p.get("fdv")
        e.update(market_cap=float(cap) if cap else e.get("market_cap"), price_usd=p.get("priceUsd"),
                 liquidity_usd=float((p.get("liquidity") or {}).get("usd") or 0),
                 change_24h=(p.get("priceChange") or {}).get("h24"), pair_url=p.get("url") or e.get("pair_url"),
                 dex=p.get("dexId"), bonding=(p.get("dexId") == "pumpfun"))
        if not e.get("pair_address") or e.get("bonding"):
            e["pair_address"] = p.get("pairAddress") or e.get("pair_address")
        base = p.get("baseToken") or {}
        if no_name(e.get("symbol")) and not no_name(base.get("symbol")):
            e.update(symbol=base["symbol"], name=base.get("name") or base["symbol"])
        sites = legit.links_from_dexscreener(p)["websites"]
        if sites:
            e["websites"] = list(dict.fromkeys([*(e.get("websites") or []), *sites]))[:6]
        gem_track.sample(e["chain"], e["token_address"], p.get("priceUsd"))
        projects_db.set_market(e["chain"], e["token_address"], mcap=cap, liq=e["liquidity_usd"],
                               vol24=(p.get("volume") or {}).get("h24"), price=p.get("priceUsd"))
    _mark()


async def _poll_market(client: httpx.AsyncClient) -> None:
    by_chain: dict[str, list[str]] = {}
    for e in _entries.values():
        by_chain.setdefault(e["chain"], []).append(e["token_address"])
    for chain, tokens in by_chain.items():
        for i in range(0, len(tokens), 30):
            r = await client.get(DEX_TOKENS.format(chain=chain, addresses=",".join(tokens[i:i + 30])),
                                 timeout=10.0)
            if r.status_code == 200 and isinstance(r.json(), list):
                apply_market(r.json())


# ---------------------------------------------------------------- analisi

def due(e: dict, now: float) -> set[str]:
    """I pilastri da rifare adesso."""
    out = set()
    for k, every in STALE_S.items():
        p = e["pillars"].get(k)
        at = e["checked_at"].get(k, 0)
        if p is None or (p.get("pending") and now - at >= PENDING_RETRY_S) or now - at >= every:
            out.add(k)
    return out


def apply_analysis(k: str, result: dict, now: float | None = None) -> None:
    now = now or time.time()
    e = _entries.get(k)
    if e is None:
        return
    for name, pillar in result.items():
        e["pillars"][name] = pillar
        e["checked_at"][name] = now
        if name == "github" and (pillar.get("facts") or {}).get("url"):
            e["github"] = pillar["facts"]["url"]
    e["overall"] = depth.overall(e["pillars"])
    e["similarity"] = benchmark.similarity(benchmark.signals(
        (e["pillars"].get("github") or {}).get("facts"),
        (e["pillars"].get("site") or {}).get("facts", {}).get("tech_terms")))
    gh = (e["pillars"].get("github") or {}).get("facts") or {}
    site_keys = (e["pillars"].get("site") or {}).get("facts", {}).get("narratives") or []
    more = narratives.match(e.get("description"), e.get("categories"), gh.get("topics"), gh.get("description"))
    e["narratives"] = merge_narratives(e.get("narratives_hint"), site_keys, [*more, *(e.get("narr_ds") or [])])
    if e["overall"]["fatal"] and not benchmark.is_benchmark(e["chain"], e["token_address"]) \
            and e.get("source") != "reference":     # Lorenzo's references stay, with their reason
        _exclude(k, e["overall"]["fatal"], now)
        _remember(e, "rejected", e["overall"]["fatal"], now)
        _mark()
        return
    _mark()
    if not (e["overall"] or {}).get("pending"):
        why = qualifies(e, now)
        _remember(e, "ranked" if e.get("rank") else "studied", why, now)


def _remember(e: dict, status: str, why: str, now: float) -> None:
    """The verdict goes to the database, so it outlives the working set.
    "ranked" or "studied" is the Top's word, not the board's (see sync_top)."""
    rank = e.get("rank")
    if status in ("ranked", "studied"):
        status, rank = _place(_key(e["chain"], e["token_address"]), rank)
        if status == "ranked":
            why = ""
    try:
        projects_db.record({**e, "rank": rank}, status, why, final_score(e) if status != "rejected" else None,
                           traction_of(e), now)
    except Exception:
        logger.exception("classifica: verdetto non salvato per %s", e.get("symbol"))


def _exclude(k: str, reason: str, now: float) -> None:
    e = _entries.pop(k, None)
    _gone[k] = now
    if e is None:
        return
    _excluded.insert(0, {"chain": e["chain"], "token_address": e["token_address"], "symbol": e["symbol"],
                         "name": e["name"], "source": e["source"], "reason": reason, "at": now,
                         "was_rank": e.get("rank")})
    del _excluded[KEEP_EXCLUDED:]


async def _analyze(k: str, skip: set[str], client: httpx.AsyncClient) -> None:
    try:
        async with _slots:
            e = _entries.get(k)
            if e is None:
                return
            item = {**e, "links": [s.get("url") for s in e.get("socials") or [] if s.get("url")],
                    # only projects past the researcher's floor are worth Claude's reading
                    "finalist": not research_floor(e)}
            result = await depth.analyze(item, client, skip=skip)
        apply_analysis(k, result)
        e = _entries.get(k)
        if e is not None and result:
            _note_study(e, sorted(result))
        if e is not None:
            o = e.get("overall") or {}
            if not o.get("pending") and not o.get("fatal"):
                j = await judge.judge(e, qualifies(e))
                if j:
                    e["judge"] = j
                    _remember(e, "ranked" if e.get("rank") else "studied", qualifies(e), time.time())
                    _mark()
    except Exception:
        logger.exception("classifica: analisi fallita su %s", k)
    finally:
        _busy.discard(k)


_PILLAR_NAMES = {"github": "GitHub", "site": "site", "tokenomics": "tokenomics"}


def _note_study(e: dict, pillars: list[str]) -> None:
    """Ogni studio di un progetto nel registro dell'agente (Lorenzo, 28/09:
    "voglio avere la sensazione che stia lavorando costantemente [...]
    andando nel database a approfondire"). Solo lavoro vero, niente LLM."""
    from app.notify import deepseek_desk
    names = [_PILLAR_NAMES.get(p, p) for p in pillars]
    steps = []
    for p in pillars:
        pil = (e.get("pillars") or {}).get(p) or {}
        if pil.get("score") is not None:
            steps.append(f"{_PILLAR_NAMES.get(p, p)}: {round(pil['score'])}")
        elif pil.get("detail"):
            steps.append(f"{_PILLAR_NAMES.get(p, p)}: {str(pil['detail'])[:80]}")
    o = e.get("overall") or {}
    outcome = ("rejected: " + str(o.get("fatal"))[:80] if o.get("fatal")
               else f"score {round(o['score'])}" if o.get("score") is not None else "")
    deepseek_desk.note("study", f"Studied {e.get('symbol') or e.get('name')}: {', '.join(names)}",
                       steps=steps, outcome=outcome, chain=e.get("chain"), token=e.get("token_address"))


def _prune(now: float) -> None:
    for k, e in list(_entries.items()):
        launched = e.get("launched_at")
        pending_since = e.get("found_at", now)
        limit = (radar.EXC_AGE_MAX_DAYS if exceptional(e)
                 else SERIOUS_AGE_MAX_DAYS if e.get("source") in SERIOUS_SOURCES else MAX_AGE_DAYS)
        if benchmark.is_benchmark(e["chain"], e["token_address"]):
            continue
        if launched and now - launched > limit * 86400:
            _entries.pop(k)
        elif (e.get("overall") or {}).get("pending") and now - pending_since > PENDING_GIVE_UP_S:
            # A slow service (GitHub out of requests) is not the project's
            # fault: drop it from the queue, but let it come back.
            _entries.pop(k)
    if len(_entries) > MAX_ENTRIES:
        for k in sorted(_entries, key=lambda k: _entries[k].get("found_at", 0))[:len(_entries) - MAX_ENTRIES]:
            _entries.pop(k)
    for k, at in list(_gone.items()):
        if now - at > 30 * 86400:
            del _gone[k]


# -------------------------------------------------------------- classifica

def exceptional(e: dict) -> bool:
    """La regola del radar per le eccezioni, sui controlli che ha salvato."""
    checks = e.get("checks") or []
    gh = next((c for c in checks if c.get("key") == "github"), None)
    return bool(gh) and not legit.github_shortfall(gh) and not legit.gem_shortfall(checks, e.get("report"))


def true_cap(e: dict) -> float:
    """The larger of the pool's cap, the contract's global cap (CoinGecko) and
    the cap of the top coin this token is a copy of (bridged AAVE)."""
    return max(float(e.get("market_cap") or 0), float(e.get("global_cap") or 0), big_coins.cap_of(e))


def too_big(e: dict) -> str:
    """Why a token is not a small cap at all: a port from another chain or
    a cap over the ceiling (pool, CoinGecko, or the top coin it copies)."""
    if big_coins.bridged(e):
        return "bridged copy of a coin from another chain"
    if true_cap(e) > BOARD_CAP_MAX_USD:
        return f"over ${BOARD_CAP_MAX_USD / 1e6:.0f}M (${true_cap(e) / 1e6:,.0f}M)"
    return ""


def qualifies(e: dict, now: float | None = None) -> str:
    """"" se entra in classifica, altrimenti perche' no."""
    if benchmark.is_benchmark(e.get("chain"), e.get("token_address")):
        return ""   # il metro di paragone c'e' sempre, i suoi numeri si vedono comunque
    big = too_big(e)
    if big:
        return big
    r = e.get("review") or {}
    if r.get("keep") is False and (now or time.time()) - (r.get("at") or 0) < judge.REVIEW_TTL_S:
        return f"DeepSeek review: {r.get('reason') or 'dropped'}"
    floor = research_floor(e, now)
    if floor:
        return floor
    o = e.get("overall") or {}
    pillars = e.get("pillars") or {}
    if not o or o.get("fatal"):
        return o.get("fatal") or "to be examined"
    if o.get("pending"):
        return o["pending"]
    closed = no_github(e)
    need = [k for k in depth.WEIGHTS if not (closed and k == "github")]
    if any((pillars.get(k) or {}).get("score") is None for k in need):
        return "incomplete analysis"
    j = e.get("judge") or {}
    if j.get("verdict") in ("avoid", "scam") and (j.get("confidence") or 0) >= judge.VETO_MIN_CONF:
        return f"DeepSeek: {(j.get('problems') or [j['verdict']])[0]}"
    admitted = j.get("verdict") in ("gem", "watch") and (j.get("score") or 0) >= judge.ADMIT_MIN
    weak = [k for k in need if pillars[k]["score"] < (NO_GITHUB_MIN_PILLAR[k] if closed else MIN_PILLAR)]
    if weak and not admitted:
        return f"{weak[0]} too weak ({pillars[weak[0]]['score']})"
    if e.get("source") in SERIOUS_SOURCES:
        return _serious_shortfall(e, pillars, now)
    if is_big(e, now):
        if closed:
            return "beyond the radar limits without public code"
        launched = e.get("launched_at")
        if (float(e.get("market_cap") or 0) > radar.EXC_MCAP_MAX_USD
                or (launched and (now or time.time()) - launched > radar.EXC_AGE_MAX_DAYS * 86400)):
            return "beyond the limits even for an exception"
        if not exceptional(e):
            return f"over {MAX_AGE_DAYS} days or ${CAP_MAX_USD / 1e6:.0f}M without an exceptional GitHub"
        # Anche l'analisi profonda deve confermare che il codice e' eccezionale.
        if pillars["github"]["score"] < legit.GEM_MIN_SCORE:
            return f"radar exception, but deep GitHub score only {pillars['github']['score']}"
        return ""
    cap = float(e.get("market_cap") or 0)
    if cap > legit.GEM_CAP_USD and final_score(e) < BIG_MIN_SCORE and not admitted:
        return f"above $100k with score {round(final_score(e))} (needs {BIG_MIN_SCORE})"
    return ""


def no_name(symbol) -> bool:
    """A symbol nobody can read: missing, "?", or a JSON null that became
    the string "null" upstream (Lorenzo, 28/09: "ci sono ticker tra le top
    che si chiamano null")."""
    return str(symbol or "").strip().lower() in ("", "?", "null", "none", "undefined", "nan")


def research_floor(e: dict, now: float | None = None) -> str:
    """What a researcher would not even open: no name, a launch of days
    ago, a pool nobody can trade."""
    if no_name(e.get("symbol")):
        return "no name"
    launched = e.get("launched_at")
    if launched and (now or time.time()) - launched < MIN_AGE_DAYS * 86400:
        return f"younger than {MIN_AGE_DAYS} days"
    liq = e.get("liquidity_usd")
    small = float(e.get("market_cap") or 0) and float(e.get("market_cap") or 0) < EARLY_CAP_USD
    floor = EARLY_MIN_LIQUIDITY_USD if small else MIN_LIQUIDITY_USD
    if liq is not None and float(liq) < floor:
        return f"liquidity under ${floor // 1000}k"
    return ""


def is_early(e: dict, now: float | None = None) -> bool:
    """Under $50k with the fundamentals of a board project: public code,
    every pillar solid, a strong final score. Worth a small bag, flagged."""
    cap = float(e.get("market_cap") or 0)
    if not cap or cap >= EARLY_CAP_USD or no_github(e) or benchmark.is_benchmark(e["chain"], e["token_address"]):
        return False
    pillars = e.get("pillars") or {}
    if any((pillars.get(k) or {}).get("score") is None or pillars[k]["score"] < EARLY_MIN_PILLAR
           for k in depth.WEIGHTS):
        return False
    return final_score(e) >= EARLY_MIN_SCORE and not qualifies(e, now)


def _serious_shortfall(e: dict, pillars: dict, now: float | None) -> str:
    launched = e.get("launched_at")
    if float(e.get("market_cap") or 0) > SERIOUS_CAP_MAX_USD:
        return f"over ${SERIOUS_CAP_MAX_USD / 1e6:.0f}M"
    if launched and (now or time.time()) - launched > SERIOUS_AGE_MAX_DAYS * 86400:
        return f"over {SERIOUS_AGE_MAX_DAYS} days"
    if no_github(e):
        return ""          # site and tokenomics already cleared NO_GITHUB_MIN_PILLAR
    if pillars["github"]["score"] < SERIOUS_MIN_GITHUB:
        return f"GitHub only {pillars['github']['score']}"
    weak = [k for k in depth.WEIGHTS if pillars[k]["score"] < SERIOUS_MIN_PILLAR]
    return f"{weak[0]} only {pillars[weak[0]]['score']}" if weak else ""


def no_github(e: dict) -> bool:
    return bool(((e.get("pillars") or {}).get("github") or {}).get("facts", {}).get("missing"))


def final_score(e: dict) -> float:
    """Qualita' (i tre pilastri) e somiglianza tecnica a DREGG."""
    q = (e.get("overall") or {}).get("score") or 0
    sim = (e.get("similarity") or {}).get("score") or 0
    # Likeness to DREGG lifts a project, never sinks it: its traits are read
    # from code, so a project without public code scored 0 there and lost 30%
    # on top of its penalty (Solrouter: research 78, tokenomics 64, ranked 47).
    base = max(q, (1 - SIMILARITY_WEIGHT) * q + SIMILARITY_WEIGHT * sim)
    if no_github(e):
        base -= NO_GITHUB_PENALTY
    use = traction_of(e)
    if use:
        base += TRACTION_WEIGHT * use["traction"] + VALUE_WEIGHT * (use["value"] or 0)
    rules = round(max(0.0, min(100.0, base + narratives.bonus(e.get("narratives") or []))), 1)
    j = e.get("judge") or {}
    if j.get("score") is not None:
        rules = round(max(0.0, min(100.0, (1 - JUDGE_WEIGHT) * rules + JUDGE_WEIGHT * j["score"])), 1)
    c = e.get("code") or {}
    if c.get("complexity") is not None and c.get("innovation") is not None:
        rules = round((1 - CODE_WEIGHT) * rules + CODE_WEIGHT * (c["complexity"] + c["innovation"]) / 2, 1)
    r = e.get("review") or {}
    if r.get("keep") and r.get("score") is not None:
        rules = round((1 - REVIEW_WEIGHT) * rules + REVIEW_WEIGHT * r["score"], 1)
    return rules


def traction_of(e: dict) -> dict | None:
    if not e.get("chain") or not e.get("token_address"):
        return None
    return traction.judge(traction.lookup(e["chain"], e["token_address"]), e.get("market_cap"))


def _rank() -> None:
    # By score only (Lorenzo, 27/09: "nel podio compaiono token con punteggi
    # piu' bassi rispetto a quelli presenti in database"): the benchmark keeps
    # its honorable mention, no longer the first place by decree.
    ranked = sorted((e for e in _entries.values() if not qualifies(e)),
                    key=lambda e: (-final_score(e), -(e.get("launched_at") or 0)))[:BOARD_SIZE]
    order = [_key(e["chain"], e["token_address"]) for e in ranked]
    now = time.time()
    for i, e in enumerate(ranked, 1):
        gem_track.enter(e, final_score(e), i, now)
        k = _key(e["chain"], e["token_address"])
        for kind in ("new", "early"):
            if kind == "early" and not is_early(e, now):
                continue
            tag = f"{kind}:{k}"
            if tag not in _alerted:
                _alerted.add(tag)
                if not _priming and not benchmark.is_benchmark(e["chain"], e["token_address"]):
                    _outbox.append((kind, k))
        if e.get("rank") != i:
            e["rank_before"], e["rank"], e["moved_at"] = e.get("rank"), i, now
    for k, e in _entries.items():
        if k not in order and e.get("rank") is not None:
            e["rank_before"], e["rank"], e["moved_at"] = e["rank"], None, now
    if order != _state["board"]:
        _state["board"] = order
    _sync_database(order)


def _sync_database(order: list[str]) -> None:
    """Keep the database's score and "Ranked" in step with the board: DeepSeek's
    report, review and code reading move the score after the analysis was saved
    (Lorenzo, 28/09: three at 93 in the database, off the podium)."""
    board = set(order)
    # Once the Top has been synced (sync_top), "ranked" means "in the Top":
    # the board only moves scores, it no longer demotes what the Top holds.
    if not _state.get("top_synced_at") and board != set(_state.get("db_board") or []):
        try:
            projects_db.demote_ranked(board)
            _state["db_board"] = sorted(board)
        except Exception:
            logger.exception("classifica: stato ranked non riallineato")
    for k, e in _entries.items():
        o = e.get("overall") or {}
        if not o or o.get("fatal") or o.get("pending"):
            continue
        status, rank = _place(k, e.get("rank"))
        score = final_score(e)
        seen = (status, score, rank)
        if e.get("_db") == list(seen):
            continue
        try:
            projects_db.set_standing(e["chain"], e["token_address"], status, score, rank,
                                     "" if status == "ranked" else qualifies(e))
        except Exception:
            logger.exception("classifica: posizione non salvata per %s", e.get("symbol"))
            continue
        e["_db"] = list(seen)


def _mark() -> None:
    global _dirty
    _dirty = True
    _state["version"] += 1
    _rank()


def _public(e: dict) -> dict:
    keep = ("chain", "token_address", "pair_address", "symbol", "name", "source", "launched_at", "found_at",
            "market_cap", "liquidity_usd", "change_24h", "website", "github", "socials", "pair_url", "scan_url",
            "image", "bonding", "rank", "rank_before", "moved_at", "overall", "pillars", "checked_at")
    top = benchmark.is_benchmark(e["chain"], e["token_address"])
    return {**{k: e.get(k) for k in keep}, "market_cap": true_cap(e) or e.get("market_cap"),
            "exception": is_big(e) and not top, "score": final_score(e),
            "similarity": e.get("similarity"), "benchmark": top, "early": is_early(e), "price_usd": e.get("price_usd"),
            "narratives": narratives.labels(e.get("narratives") or []), "closed_source": no_github(e),
            **_research_public(e), "honor": benchmark.HONOR if top else None, "traction": traction_of(e),
            "review": {k: (e.get("review") or {}).get(k) for k in ("keep", "score", "reason")} if e.get("review") else None,
            "judge": {k: (e.get("judge") or {}).get(k)
                      for k in ("score", "verdict", "problems", "strengths", "admit_reason")} if e.get("judge") else None,
            "code": {k: (e.get("code") or {}).get(k)
                     for k in ("complexity", "innovation", "fork_of", "summary", "strengths", "concerns")}
            if e.get("code") else None}


def _research_public(e: dict) -> dict:
    f = ((e.get("pillars") or {}).get("site") or {}).get("facts") or {}
    return {"summary": f.get("summary") or None, "stage": f.get("stage"), "verdict": f.get("verdict")}


CLOSE_SIZE = 6


def close_calls(now: float | None = None) -> list[dict]:
    """The projects nearest the board and what keeps each out: past the
    researcher's floor, ranked by their research score."""
    out = []
    for k, e in _entries.items():
        if k in _state["board"] or research_floor(e, now):
            continue
        site = (e.get("pillars") or {}).get("site") or {}
        out.append({"symbol": e.get("symbol"), "name": e.get("name"), "chain": e.get("chain"),
                    "token_address": e.get("token_address"), "market_cap": e.get("market_cap"),
                    "research": site.get("score"), "verdict": (site.get("facts") or {}).get("verdict"),
                    "why": qualifies(e, now) or "ranking"})
    out.sort(key=lambda x: -(x["research"] if x["research"] is not None else -1))
    return out[:CLOSE_SIZE]


def board() -> dict:
    entries = [_entries[k] for k in _state["board"] if k in _entries and not no_name(_entries[k].get("symbol"))]
    waiting = sum(1 for k, e in _entries.items() if k not in _state["board"])
    return {
        "version": _state["version"], "updated_at": _state["last_tick"] or None,
        "entries": [_public(e) for e in entries],
        "examined": _state["examined"], "analyzing": len(_busy), "waiting": waiting,
        "excluded": _excluded[:20], "excluded_total": len(_gone),
        "sources": _state["sources"], "discovery": discovery.status(),
        "github_rate": legit.github_rate or None,
        "research_ai": research.ai_status(), "close": close_calls(),
        "track": gem_track.stats(), "defillama": traction.status(), "database": projects_db.stats(),
        "past_floor": sum(1 for e in _entries.values() if not research_floor(e)),
        "rules": {"weights": depth.WEIGHTS, "similarity_weight": SIMILARITY_WEIGHT,
                  "traction_weight": TRACTION_WEIGHT, "value_weight": VALUE_WEIGHT,
                  "early_cap_usd": EARLY_CAP_USD, "early_min_pillar": EARLY_MIN_PILLAR, "early_min_score": EARLY_MIN_SCORE, "benchmark": benchmark.NAME, "min_pillar": MIN_PILLAR, "gem_cap_usd": legit.GEM_CAP_USD,
                  "gem_min_score": legit.GEM_MIN_SCORE, "cap_max_usd": CAP_MAX_USD, "board_cap_max_usd": BOARD_CAP_MAX_USD, "max_age_days": MAX_AGE_DAYS,
                  "big_min_score": BIG_MIN_SCORE, "judge_weight": JUDGE_WEIGHT,
                  "exception_cap_usd": radar.EXC_MCAP_MAX_USD, "exception_age_days": radar.EXC_AGE_MAX_DAYS},
    }


# -------------------------------------------------------------------- giro

async def _step(name: str, fn, *args) -> None:
    try:
        await fn(*args)
        _state["sources"][name] = {"ok": True, "at": time.time()}
    except Exception as exc:
        _state["sources"][name] = {"ok": False, "at": time.time(), "error": type(exc).__name__}
        logger.info("classifica: %s non riuscito: %s", name, exc)


def on_alert(fn) -> None:
    """fn(kind, public_entry) is awaited for a project new on the board
    ("new") or flagged early ("early"). Telegram lives in main.py."""
    _alert_hooks.append(fn)


async def drain_alerts() -> int:
    sent = 0
    while _outbox and sent < ALERTS_PER_TICK:
        kind, k = _outbox.pop(0)
        e = _entries.get(k)
        if e is None or (kind == "early" and not is_early(e)):
            continue
        item = _public(e)
        for fn in list(_alert_hooks):
            try:
                await fn(kind, item)
            except Exception:
                logger.exception("classifica: avviso %s fallito", k)
        sent += 1
    return sent


async def _db_market(client: httpx.AsyncClient, now: float) -> None:
    """Cap and liquidity for the database, oldest first: this is what puts a
    project known only by name into the band, or out of it."""
    for chain, tokens in projects_db.stale_market(DB_MARKET_BATCH, now).items():
        for i in range(0, len(tokens), 30):
            batch = tokens[i:i + 30]
            r = await client.get(DEX_TOKENS.format(chain=chain, addresses=",".join(batch)), timeout=10.0)
            if r.status_code == 200 and isinstance(r.json(), list):
                projects_db.apply_pairs(chain, batch, r.json(), now)
            await asyncio.sleep(0.3)


def feed_from_database(now: float | None = None) -> int:
    """Move the next projects from the database into the working set, while
    the analysis queue has room: never analysed first, then second looks."""
    now = now or time.time()
    waiting = sum(1 for e in _entries.values() if not e["pillars"])
    if waiting >= DB_FEED_MAX_WAITING or len(_entries) >= MAX_ENTRIES:
        return 0
    fed = 0
    for p in projects_db.due_for_analysis(DB_FEED_PER_TICK * 3, set(_entries), now):
        item = projects_db.as_item(p)
        if _looks_like_meme(item["symbol"], item["name"]):
            projects_db.record(item, "rejected", "meme name", now=now)
            continue
        if add(item, "database", now):
            fed += 1
        if fed >= DB_FEED_PER_TICK:
            break
    return fed


async def _from_database(client: httpx.AsyncClient, now: float) -> None:
    if now - _state.get("db_market_at", 0.0) >= DB_MARKET_S:
        _state["db_market_at"] = now
        await _db_market(client, now)
    feed_from_database(now)


async def tick(client: httpx.AsyncClient, now: float | None = None) -> None:
    now = now or time.time()
    _state["last_tick"] = now
    try:
        collect_saved()
    except Exception:
        logger.exception("classifica: lettura del radar fallita")
    if discovery_open(now):
        await _step("progetti", discovery.tick, client, add, now)
    if now - _state["last_market"] >= MARKET_POLL_S and _entries:
        _state["last_market"] = now
        await _step("dexscreener", _poll_market, client)
    await _step("storico", gem_track.poll, client, set(_entries), now)
    await _step("database", _from_database, client, now)
    await _step("grandi monete", _refresh_big_coins, client, now)
    await _step("cap globale", _check_global_cap, client, now)
    if not _state.get("reviewing") and not priority.backtests_first():
        task = asyncio.create_task(_step("revisione", _review_board, now))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    if not _state.get("code_reading"):
        task = asyncio.create_task(_step("codice", _read_code, client, now))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    if not _state.get("top_filling") and _top_source is not None \
            and now - _state.get("top_fill_at", 0.0) >= TOP_FILL_EVERY_S:
        task = asyncio.create_task(_step("top", top_fill, client, now))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    if _top_source is not None and now - _state.get("top_synced_at", 0.0) >= TOP_SYNC_EVERY_S:
        await _step("top sync", _sync_top, now)
    if not _state.get("auditing") and consistency.due(now):
        task = asyncio.create_task(_step("coerenza", _audit, now))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    if not _state.get("narr_mapping"):
        task = asyncio.create_task(_step("narrative", _map_narratives, now))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    await drain_alerts()
    _prune(now)
    # I nuovi prima (nessun pilastro), poi i piu' vecchi da rinfrescare.
    todo = sorted(((k, due(e, now)) for k, e in _entries.items() if k not in _busy),
                  key=lambda kv: (bool(_entries[kv[0]]["pillars"]), -_entries[kv[0]].get("found_at", 0)))
    for k, need in todo:
        if not need or len(_busy) >= ANALYZE_CONCURRENCY * 2:
            continue
        _busy.add(k)
        task = asyncio.create_task(_analyze(k, set(STALE_S) - need, client))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    if _dirty:
        _save()


async def _refresh_big_coins(client: httpx.AsyncClient, now: float) -> None:
    if await big_coins.refresh(client, now):
        _mark()     # re-rank at once: a copy of a top coin leaves the board now


async def _check_global_cap(client: httpx.AsyncClient, now: float) -> None:
    """One CoinGecko lookup: the board first, then the rest past the floor."""
    if now < _state.get("cap_next_at", 0):
        return
    _state["cap_next_at"] = now + GLOBAL_CAP_EVERY_S
    board = set(_state["board"])
    todo = [k for k, e in _entries.items()
            if now - (e.get("global_cap_at") or 0) > GLOBAL_CAP_TTL_S and not research_floor(e, now)
            and CG_PLATFORM.get(e.get("chain")) and not benchmark.is_benchmark(e["chain"], e["token_address"])]
    if not todo:
        return
    k = min(todo, key=lambda k: (k not in board, -(float(_entries[k].get("market_cap") or 0))))
    e = _entries[k]
    r = await client.get(CG_CONTRACT.format(platform=CG_PLATFORM[e["chain"]], address=e["token_address"]),
                         timeout=15.0, headers={"Accept": "application/json"})
    if r.status_code == 429:
        _state["cap_next_at"] = now + 120
        return
    md = (r.json().get("market_data") or {}) if r.status_code == 200 else {}
    e["global_cap"] = max(float((md.get("market_cap") or {}).get("usd") or 0),
                          float((md.get("fully_diluted_valuation") or {}).get("usd") or 0)) or None
    e["global_cap_at"] = now
    _mark()


async def _review_board(now: float) -> None:
    """DeepSeek challenges the board as a whole (Lorenzo, 28/09)."""
    keys = [k for k in _state["board"] if k in _entries
            and not benchmark.is_benchmark(_entries[k]["chain"], _entries[k]["token_address"])]
    last = _state.get("reviewed_at", 0)
    changed = set(keys) != set(_state.get("reviewed_board") or [])
    if not keys or _state.get("reviewing") or now - last < (REVIEW_MIN_GAP_S if changed else REVIEW_EVERY_S):
        return
    _state["reviewing"] = True
    try:
        res = await judge.review_board([_entries[k] for k in keys], now)
    finally:
        _state["reviewing"] = False
    _state["reviewed_at"], _state["reviewed_board"] = now, keys
    for k, v in res.items():
        if k in _entries:
            _entries[k]["review"] = v
    if res:
        _mark()


def pool_status(now: float | None = None) -> dict:
    """The pool (projects past the filters, in the database) and what is
    still missing on the ones in the working set."""
    now = now or time.time()
    try:
        by = projects_db.stats().get("by_status") or {}
    except Exception:
        by = {}
    pool = int(by.get("studied", 0)) + int(by.get("ranked", 0))
    waiting = reports = code = done = 0
    for e in _entries.values():
        o = e.get("overall") or {}
        if not e.get("pillars") or o.get("pending"):
            waiting += 1
            continue
        if o.get("fatal") or research_floor(e, now):
            continue
        miss_report = not e.get("judge")
        has_repo = bool((((e.get("pillars") or {}).get("github") or {}).get("facts") or {}).get("repo"))
        miss_code = has_repo and not e.get("code")
        reports += miss_report
        code += miss_code
        done += not (miss_report or miss_code)
    backlog = waiting + reports + code
    return {"pool": pool, "target": POOL_TARGET, "waiting": waiting, "reports": reports, "code": code,
            "complete": done, "backlog": backlog,
            "paused": pool >= POOL_TARGET and backlog > BACKLOG_LOW}


def discovery_open(now: float) -> bool:
    """Scan for new projects only while the pool is small, or slowly once
    what we have is nearly complete."""
    st = pool_status(now)
    _state["pool"] = st
    if st["pool"] < POOL_TARGET:
        return True
    if st["paused"]:
        return False
    if now - _state.get("slow_scan_at", 0.0) < DISCOVERY_SLOW_S:
        return False
    _state["slow_scan_at"] = now
    return True


async def _read_code(client: httpx.AsyncClient, now: float) -> None:
    """DeepSeek legge il codice di un progetto per volta (Lorenzo, 28/09)."""
    if _state.get("code_reading") or now - _state.get("code_at", 0.0) < CODE_EVERY_S:
        return
    _state["code_at"] = now
    board = set(_state["board"])
    todo = []
    for k, e in _entries.items():
        gh = (e.get("pillars") or {}).get("github") or {}
        if not (gh.get("facts") or {}).get("repo"):
            continue
        c = e.get("code") or {}
        if c and now - (c.get("at") or 0) < code_review.TTL_S:
            continue
        if now - (e.get("code_tried_at") or 0) < CODE_RETRY_S:
            continue
        if k in board or not research_floor(e, now) or benchmark.is_benchmark(e["chain"], e["token_address"]):
            todo.append(k)
    if not todo:
        return
    k = min(todo, key=lambda k: (k not in board, -(float(_entries[k].get("market_cap") or 0))))
    e = _entries[k]
    e["code_tried_at"] = now
    _state["code_reading"] = True
    try:
        result = await code_review.review(e, client, now)
    finally:
        _state["code_reading"] = False
    if result:
        e["code"] = result
        _mark()


async def _map_narratives(now: float) -> None:
    """DeepSeek maps the database to narratives, a batch per turn
    (narrative_map.py); keys it finds for a board entry join its own."""
    _state["narr_mapping"] = True
    try:
        written = await narrative_map.step(now)
    finally:
        _state["narr_mapping"] = False
    changed = False
    for k, keys in written.items():
        e = _entries.get(k)
        if e is None:
            continue
        e["narr_ds"] = keys          # survives the next analysis, which rebuilds "narratives"
        have = list(e.get("narratives") or [])
        new = [x for x in keys if x not in have]
        if new:
            e["narratives"] = have + new
            changed = True
    if changed:
        _mark()


# ------------------------------------------------------------ the Top first

# Lorenzo, 29/09: "tutti i token che entrano in top dovranno avere l'indagine
# di deepseek nella tab why e info, come fatto per dregg". The Top (main.py
# _top_entries) mixes board entries with database rows the board never
# judged, and a board entry may still wait for the daily cap: every minute a
# few of them are read first, on their own allowance (priority=True).
TOP_FILL_EVERY_S = 60
TOP_FILL_PER_TURN = 3
TOP_RETRY_S = 6 * 3600         # a reading that failed waits before the next try
_top_source = None             # callable(n) -> the Top's entries (main._top_entries)
_top_tried: dict[str, float] = {}
TOP_SYNC_EVERY_S = 60
_top_rank: dict[str, int] = {}  # "chain:token" -> place in the unfiltered Top, after sync_top


def _place(k: str, board_rank: int | None) -> tuple[str, int | None]:
    """("ranked", place) when the project is in the Top, else ("studied", None).
    Before the first sync the board's own order stands in for the Top."""
    if _state.get("top_synced_at"):
        return ("ranked", _top_rank[k]) if k in _top_rank else ("studied", None)
    return ("ranked", board_rank) if board_rank else ("studied", None)


def sync_top(now: float | None = None) -> int:
    """The database's "ranked" follows the Top (Lorenzo, 29/09: HATCHER
    "Studied" in the Database and first on the podium). Only the unfiltered
    Top counts: a narrative filter is a view, not the ranking."""
    if _top_source is None:
        return 0
    keys = [_key(t["chain"], t["token_address"]) for t in _top_source(50)]
    changed = projects_db.sync_top(keys)
    _top_rank.clear()
    _top_rank.update({k: i for i, k in enumerate(keys, 1)})
    _state["top_synced_at"] = now or time.time()
    for e in _entries.values():
        e.pop("_db", None)      # the next _sync_database rewrites with the Top's places
    return changed


async def _sync_top(now: float) -> None:
    sync_top(now)
    _sync_database(_state["board"])


async def _audit(now: float) -> None:
    """DeepSeek looks for contradictions between the Top and the database."""
    _state["auditing"] = True
    try:
        await consistency.step(_top_source(50) if _top_source else [], now, requeue=requeue)
    finally:
        _state["auditing"] = False


def requeue(chain: str, token: str) -> bool:
    """A fresh analysis: a board entry's pillars go stale at once, a
    database row goes back in the queue."""
    e = _entries.get(_key(chain, token))
    if e is not None:
        e["checked_at"] = {}
        e.pop("_db", None)
        return True
    return projects_db.recheck(chain, token)


def set_top_source(fn) -> None:
    global _top_source
    _top_source = fn


def db_entry(p: dict) -> dict:
    """A database row in board shape: what the token page and the judge read."""
    return {**projects_db.as_item(p), "score": p.get("score"), "pillars": p.get("pillars") or {},
            "overall": p.get("overall"), "narratives": p.get("narratives") or [],
            "traction": p.get("traction"), "rank": p.get("rank"), "status": p.get("status"),
            "why": p.get("why"), "on_board": False}


async def top_fill(client: httpx.AsyncClient, now: float | None = None) -> int:
    """DeepSeek's report and code reading for the Top's entries that lack
    them, up to TOP_FILL_PER_TURN readings a turn. Returns the readings tried."""
    now = now or time.time()
    if _top_source is None or _state.get("top_filling"):
        return 0
    _state["top_fill_at"] = now
    _state["top_filling"] = True
    tried = 0
    changed = False
    try:
        for t in _top_source(50):
            if tried >= TOP_FILL_PER_TURN:
                break
            k = _key(t["chain"], t["token_address"])
            e = _entries.get(k)
            board = e is not None
            if e is None:
                p = projects_db.get(t["chain"], t["token_address"])
                if p is None:
                    continue
                e = db_entry(p)
            o = e.get("overall") or {}
            has_judge = e.get("judge") if board else judge.get(e["chain"], e["token_address"])
            if not has_judge and not o.get("pending") and now - _top_tried.get("judge:" + k, 0) >= TOP_RETRY_S:
                _top_tried["judge:" + k] = now
                tried += 1
                j = await judge.judge(e, qualifies(e, now) if board else (e.get("why") or ""), now, priority=True)
                if j and board and k in _entries:
                    _entries[k]["judge"] = j
                    _remember(e, "ranked" if e.get("rank") else "studied", qualifies(e), now)
                    changed = True
            repo = code_review.repo_of(e)
            has_code = e.get("code") if board else code_review.get(repo)
            if repo and not has_code and tried < TOP_FILL_PER_TURN \
                    and now - _top_tried.get("code:" + k, 0) >= TOP_RETRY_S:
                _top_tried["code:" + k] = now
                tried += 1
                c = await code_review.review(e, client, now, priority=True)
                if c and board and k in _entries:
                    _entries[k]["code"] = c
                    changed = True
    finally:
        _state["top_filling"] = False
    if changed:
        _mark()
    return tried


START_DELAY_S = 20


async def leaderboard_loop() -> None:
    await asyncio.sleep(START_DELAY_S)
    try:
        n = projects_db.recheck_studied(("over $%", "over % days%"))
        if n:
            logger.info("classifica: %d progetti rimessi in coda (limiti vecchi)", n)
    except Exception:
        logger.exception("classifica: recheck_studied fallito")
    async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "Mozilla/5.0 (LiquidityEngine)"}) as client:
        while True:
            try:
                await tick(client)
            except Exception:
                logger.exception("classifica: giro fallito")
            await asyncio.sleep(TICK_S)


_load()
