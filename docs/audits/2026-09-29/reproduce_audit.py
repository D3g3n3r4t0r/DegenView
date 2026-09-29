"""Offline characterization of audited source. PASS means the stated behavior exists.

Usage: python reproduce_audit.py PATH_TO_REPOSITORY
Uses original AST function bodies, with fake network/signing adapters and a temporary
SQLite database. No credentials, live requests, signing, or transfers. Not an HTTP
integration suite. After remediation these vulnerability assertions should fail;
replace them with inverse regression expectations in the application's tests.
"""
from __future__ import annotations
import ast
import asyncio
import base64
import hashlib
import gc
import hmac
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace as NS
import uuid

ROOT = Path(sys.argv[1]).resolve()
RESULTS = []

def functions(path, names=None, **extra):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    ns = dict(globals())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name):
                    ns[t.id] = value
    ns.update(extra)
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (names is None or node.name in names):
            node.decorator_list = []
            # FastAPI dependency defaults only; tests supply user/body explicitly.
            node.args.defaults = [ast.Constant(None) if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "Depends" else d for d in node.args.defaults]
            selected.append(node)
    mod = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
    exec(compile(ast.fix_missing_locations(mod), path, "exec"), ns)
    return ns

def check(name, fn):
    try:
        detail = fn()
        RESULTS.append({"test": name, "status": "REPRODUCED", "evidence": detail})
    except Exception as exc:
        RESULTS.append({"test": name, "status": "FAILED", "error": repr(exc)})

def tokenomics_contract():
    d = functions("backend/app/trading/onchain/depth.py", {"_pillar", "_judge_tokenomics", "judge_tokenomics_evm"})
    info = {"holders": [{"address": "0x111", "percent": "0.9", "is_contract": "1"}], "holder_count": "5000", "creator_percent": "0", "owner_percent": "0", "is_mintable": "0", "transfer_pausable": "0", "is_honeypot": "0", "buy_tax": "0", "sell_tax": "0"}
    result = d["judge_tokenomics_evm"](info, "")
    assert result["fatal"] == "" and result["score"] >= 85 and result["facts"]["top1_pct"] == 0
    return {"score": result["score"], "facts": result["facts"]}

def tokenomics_unknown():
    d = functions("backend/app/trading/onchain/depth.py", {"_pillar", "_pending", "_judge_tokenomics", "judge_tokenomics_evm"})
    result = d["judge_tokenomics_evm"]({"holder_count": "5000"}, "")
    assert result["score"] == 100 and not result["fatal"]
    return result

def crypto_tamper():
    c = functions("backend/app/trading/crypto.py")
    key = b"audit-only-no-real-secret"
    encrypted = bytearray(base64.b64decode(c["encrypt"]("AAA", key)))
    encrypted[16] ^= ord("A") ^ ord("B")
    result = c["decrypt"](base64.b64encode(encrypted).decode(), key)
    assert result == "BAA"
    return "Modified ciphertext accepted as BAA without authentication error"

def benchmark_bypass():
    l = functions("backend/app/trading/onchain/leaderboard.py", {"qualifies"}, benchmark=NS(is_benchmark=lambda c,t: c == "solana" and t == "benchmark"))
    result = l["qualifies"]({"chain":"solana", "token_address":"benchmark", "overall":{"fatal":"already rugged or honeypot"}, "market_cap": 999999999}, time.time())
    assert result == ""
    return "Benchmark qualifies before fatal and cap checks"

def ai_weight():
    l = functions("backend/app/trading/onchain/leaderboard.py", {"final_score", "no_github"}, narratives=NS(bonus=lambda _:0), traction_of=lambda _:None)
    e = {"overall":{"score":60}, "similarity":{"score":0}, "pillars":{}, "judge":{"score":80}, "code":{"complexity":70,"innovation":70}, "review":{"keep":True,"score":90}}
    value = l["final_score"](e)
    assert value == 76.0
    return {"final": value, "formula": "0.28*60 + 0.28*80 + 0.14*70 + 0.30*90 = 76"}

def stale_positive_review():
    l = functions("backend/app/trading/onchain/leaderboard.py", {"final_score", "no_github"}, narratives=NS(bonus=lambda _:0), traction_of=lambda _:None)
    e = {"overall":{"score":50},"pillars":{},"review":{"keep":True,"score":100,"at":1}}
    assert l["final_score"](e) == 65
    return "Ancient positive review still increases score 50 -> 65"

def low_confidence_admit():
    l = functions("backend/app/trading/onchain/leaderboard.py", {"qualifies", "no_github"}, benchmark=NS(is_benchmark=lambda *_:False), too_big=lambda _:"", research_floor=lambda *_:"", depth=NS(WEIGHTS={"github":.4,"site":.3,"tokenomics":.3}), judge=NS(REVIEW_TTL_S=259200, VETO_MIN_CONF=.7, ADMIT_MIN=80))
    e = {"overall":{"score":10}, "pillars":{k:{"score":10} for k in ("github","site","tokenomics")}, "judge":{"score":80,"verdict":"gem","confidence":0}}
    assert l["qualifies"](e, time.time()) == ""
    return "All pillars 10/100 admitted by score 80, confidence 0"

async def execute_checks(tmp):
    lg = functions("backend/app/trading/onchain/ledger.py", _DB_FILE=str(Path(tmp)/"audit.sqlite"), _lock=threading.Lock())
    lg["_init_db"]()
    ledger = NS(**{k:v for k,v in lg.items() if callable(v) and not k.startswith("__")})
    settings = NS(onchain_max_usd_per_trade=100, onchain_max_usd_per_day=200, onchain_max_token_concentration_pct=100, onchain_execution_enabled=True)
    async def pool(*_):
        return {"liquidity_usd":100000,"created_at":0}
    safety = NS(fetch_pool_snapshot=pool, DEFAULT_MIN_LIQUIDITY_USD=1000, DEFAULT_MIN_POOL_AGE_MINUTES=0, DEFAULT_MAX_LIQUIDITY_DROP_PCT=50,
                check_liquidity_minimum=lambda *_:(True,""), check_pool_age=lambda *_:(True,""), check_liquidity_drop=lambda *_:(True,""))
    r = functions("backend/app/trading/onchain/risk.py", settings=settings, ledger=ledger, pool_safety=safety)
    risk = NS(**{k:v for k,v in r.items() if callable(v) and not k.startswith("__")})
    signed_amounts = []
    async def build(pk, ti, to, fee, amount, minimum):
        signed_amounts.append(amount)
        return b"FAKE-NO-SIGNATURE"
    async def broadcast(_):
        return "FAKE-BROADCAST-ACK-NO-RECEIPT"
    e = functions("backend/app/trading/onchain/execute.py", {"execute_order"}, settings=settings, ledger=ledger, risk=risk, pool_safety=safety,
                  execution=NS(build_signed_robinhood_swap=build, send_signed_evm_tx=broadcast), logger=logging.getLogger("audit"))
    quote = {"token_in":"IN","token_out":"OUT","fee":3000,"amount_in":1000,"amount_out_minimum":1}
    async def place(owner, amount=1000, pool_address="pool", guards=True):
        return await e["execute_order"](owner,"robinhood","OUT","manuale","buy",amount,0,1,"FAKE",quote,pool_address,guards)
    result = await place("clamp")
    order = ledger.get_order(result["idempotency_key"])
    assert result["accepted"] and signed_amounts[-1] == 1000 and order["size_usd"] == 100
    RESULTS.append({"test":"S02-clamp-does-not-resize-transaction","status":"REPRODUCED","evidence":{"quote_input":1000,"recorded_size_usd":order["size_usd"]}})
    assert order["status"] == "confirmed" and ledger.pending_unconfirmed("clamp") == []
    RESULTS.append({"test":"S04-confirmed-without-receipt","status":"REPRODUCED","evidence":"Broadcast-only fake adapter -> confirmed; not seen by pending reconciliation"})
    one = await place("retry", 10, None)
    two = await place("retry", 10, None)
    assert one["accepted"] and two["accepted"] and one["idempotency_key"] != two["idempotency_key"]
    RESULTS.append({"test":"S03-identical-retry-submits-twice","status":"REPRODUCED","evidence":{"first":one["idempotency_key"],"second":two["idempotency_key"]}})
    ledger.reserve("double", "double", "robinhood", "T", "manuale", "buy", "live", 10)
    ledger.mark_confirmed("double", 10, 1, 0)
    ledger.mark_confirmed("double", 10, 1, 0)
    assert ledger.get_position("double","robinhood","T")["quantity"] == 20
    RESULTS.append({"test":"S03-ledger-confirmation-is-not-idempotent","status":"REPRODUCED","evidence":"Same order confirmed twice: quantity/spend 10 -> 20"})
    ledger.reserve("crash", "crash", "robinhood", "T", "manuale", "buy", "live", 10)
    assert ledger.pending_unconfirmed("crash") == []
    RESULTS.append({"test":"S04-reserved-crash-not-reconciled","status":"REPRODUCED","evidence":"pending row is excluded from pending_unconfirmed"})
    async def delayed_build(*args):
        await asyncio.sleep(.02)
        return await build(*args)
    e["execution"].build_signed_robinhood_swap = delayed_build
    settings.onchain_max_usd_per_day = 150
    both = await asyncio.gather(place("race",100,None), place("race",100,None))
    assert all(x["accepted"] for x in both) and ledger.get_daily_spent("race","robinhood") == 200
    RESULTS.append({"test":"S03-concurrent-daily-limit-bypass","status":"REPRODUCED","evidence":"Two simultaneous $100 orders pass $150/day cap; $200 recorded"})
    for i in range(5):
        ledger.record_trade_outcome("breaker","robinhood",-1,5)
    assert ledger.breaker_status("breaker","robinhood")["tripped"]
    bypass = await place("breaker",10,None,False)
    assert bypass["accepted"]
    RESULTS.append({"test":"S01-autotrader-bypasses-circuit-breaker","status":"REPRODUCED","evidence":"guards=False accepts order with breaker tripped"})

def session_logout():
    a = functions("backend/app/auth.py", {"make_session_cookie","_verify_session_cookie"}, _SECRET=b"test-only", SESSION_MAX_AGE_SECONDS=30*86400)
    cookie = a["make_session_cookie"]("victim")
    response = NS(delete_cookie=lambda *_:None)
    m = functions("backend/app/main.py", {"logout"}, auth=NS(SESSION_COOKIE="session"), guest_links=NS(GUEST_COOKIE="guest"))
    asyncio.run(m["logout"](response))
    assert a["_verify_session_cookie"](cookie) == "victim"
    return "Copied session cookie remains valid after logout"

def wallet_switch_static():
    root = ast.parse((ROOT/"backend/app/main.py").read_text(encoding="utf-8"))
    targets = {"onchain_execute_solana","onchain_execute_robinhood","onchain_send_token"}
    for fn in root.body:
        if isinstance(fn, ast.AsyncFunctionDef) and fn.name in targets:
            assert not any(isinstance(n, ast.Attribute) and n.attr == "enabled" for n in ast.walk(fn))
    return "Three direct execution handlers do not inspect wallet.enabled; risk checks do not either (static evidence)"

def top_bypass():
    row = {"chain":"solana","token":"TEST","symbol":"TEST","name":"Test","score":95,"analyzed_at":time.time(),"mcap":100000,"liq":1,"overall":{"score":95},"why":"liquidity under $10k"}
    class DB:
        def search(self, **kw):
            return {"items":[row] if kw["status"] == "studied" else []}
    m = functions("backend/app/main.py", {"_top_entries"}, onchain_leaderboard=NS(board=lambda:{"entries":[]}, no_name=lambda _:False, too_big=lambda _:""), onchain_projects_db=DB(), onchain_judge=NS(get=lambda *_:None))
    result = m["_top_entries"](50, "")
    assert len(result)==1 and result[0]["liquidity_usd"]==1
    return "Studied row rejected by liquidity floor enters Top with $1 liquidity"

def readme_payload():
    payload = {"encoding":"base64", "content":base64.b64encode(b"# Real README text").decode()}
    class Response:
        status_code=200
        def __init__(self, data): self.data=data; self.text=json.dumps(data)
        def json(self): return self.data
    async def gh_get(client,url,**kw):
        return Response(payload if url.endswith("/readme") else {"tree":[]} if "/git/trees/" in url else {"default_branch":"main"})
    c=functions("backend/app/trading/onchain/code_review.py", {"fetch_code","pick_files","_is_source","_cut"}, legit=NS(GITHUB_API="https://api.github.com", _gh_headers=lambda:{"Accept":"application/vnd.github+json"}, gh_get=gh_get))
    result=asyncio.run(c["fetch_code"]("owner/repo",None))
    assert "# Real README text" not in result["readme"] and '"encoding": "base64"' in result["readme"]
    return "GitHub JSON metadata/base64 is sent as README text"

check("M01-contract-holder-excluded", tokenomics_contract)
check("M02-missing-security-data-is-perfect", tokenomics_unknown)
check("S07-unauthenticated-ciphertext", crypto_tamper)
check("M03-benchmark-bypasses-fatal", benchmark_bypass)
check("M04-effective-ai-weights", ai_weight)
check("M04-expired-positive-review", stale_positive_review)
check("M05-zero-confidence-ai-admission", low_confidence_admit)
check("S06-logout-does-not-revoke", session_logout)
check("S01-wallet-switch-static", wallet_switch_static)
check("M06-top-bypasses-liquidity-floor", top_bypass)
check("M07-readme-is-not-decoded", readme_payload)
with tempfile.TemporaryDirectory(prefix="liquid-audit-") as tmp:
    try:
        asyncio.run(execute_checks(tmp))
    except Exception as exc:
        RESULTS.append({"test":"execution-proofs","status":"FAILED","error":repr(exc)})
    gc.collect()
print(json.dumps({"method":"offline AST characterization; not full integration", "results":RESULTS}, indent=2))
sys.exit(1 if any(r["status"]=="FAILED" for r in RESULTS) else 0)
