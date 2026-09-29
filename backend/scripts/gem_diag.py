"""Gem finder diagnostics: run inside the app container,
`docker compose exec app python scripts/gem_diag.py [chain:token ...]`."""
import json
import sys
import time

sys.path.insert(0, ".")
from app.trading.onchain import leaderboard as lb, projects_db  # noqa: E402

DEFAULT = ["robinhood:0xd293291060334d42e5dbea6fb854c231af527777", "solana:G5W6LwkLeoj6rZqBP1y3KT8k6Cz6rXGJmMNU3TArXtXw",
           "robinhood:0xa934ba4f59070149d37a93f8a002af79bae35563", "robinhood:0x727701f88f09fed71eb217bcea88b3f314cf7079",
           "robinhood:0x459476869af797eb9061b41fa04de46a60fbedbd"]
now = time.time()
store = json.loads(lb._STORE_FILE.read_text(encoding="utf-8"))
entries = store.get("entries") or {}
print("rules", store.get("rules"), "entries", len(entries), "no_pillars", sum(1 for e in entries.values() if not e.get("pillars")),
      "gone", len(store.get("gone") or {}), "excluded", len(store.get("excluded") or []))
print("db", projects_db.stats().get("by_status"))
print("band", projects_db.CAP_MIN, projects_db.CAP_MAX, projects_db.LIQ_MIN)
print("due_now", len(projects_db.due_for_analysis(50, set(), now)))
lower = {k.lower(): k for k in entries}
for ref in sys.argv[1:] or DEFAULT:
    chain, _, token = ref.partition(":")
    row = projects_db.get(chain, token) or {}
    k = lower.get(ref.lower())
    e = entries.get(k) if k else None
    print("\n==", ref, row.get("symbol"))
    print(" db:", {f: row.get(f) for f in ("status", "score", "rank", "why", "mcap", "liq", "cg_mcap", "website", "github",
                                         "next_check", "analyzed_at", "sources")})
    print(" gone:", (store.get("gone") or {}).get(k or ref))
    if e:
        print(" entry: overall", e.get("overall"), "checked", e.get("checked_at"))
        for n, p in (e.get("pillars") or {}).items():
            print(f"  {n}: score {p.get('score')} fatal {p.get('fatal')!r} pending {p.get('pending')!r} flags {p.get('flags')}")
        j = e.get("judge") or {}
        print(" judge:", j.get("score"), j.get("verdict"), j.get("v"), j.get("at"))
    else:
        print(" entry: not in working set")
