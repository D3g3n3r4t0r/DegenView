"""A second reader on every pull request: DeepSeek reads the diff and
leaves one comment, in Italian, with what it thinks could break.

Lorenzo, 27/09: "facciamo leggere a deep seek la repository?". Not the
whole repository at once (too big to be useful): each PR's changes, plus
the project's rules from CLAUDE.md, which say what is easy to get wrong
here. The comment is replaced on every push, not stacked.

Only code goes out: DeepSeek's servers are in China, and the diff is the
same code that sits on GitHub. No secrets are in the repository.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

API = "https://api.github.com"
MARK = "<!-- deepseek-review -->"
MAX_DIFF = 90_000          # characters; the model reads ~128k tokens, leave room
USAGE: dict = {}          # the last call's tokens, for the daily recap (app/notify/deepseek_desk.py)
SKIP = (".json", ".lock", ".png", ".jpg", ".webp", ".svg", ".min.js")


def gh(path: str, method: str = "GET", body: dict | None = None, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                          "Accept": accept, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return raw.decode() if accept.endswith("diff") else json.loads(raw or b"null")


def trimmed_diff(diff: str) -> str:
    """Drop data and binary files, then cut to MAX_DIFF."""
    parts, out = diff.split("\ndiff --git "), []
    for i, part in enumerate(parts):
        head = part.split("\n", 1)[0]
        if any(head.split(" b/")[-1].endswith(s) for s in SKIP):
            continue
        out.append(part if i == 0 else "diff --git " + part)
    text = "\n".join(out)
    return text if len(text) <= MAX_DIFF else text[:MAX_DIFF] + "\n\n[... diff cut here: too long ...]"


def rules() -> str:
    """CLAUDE.md's project rules, then DEEPSEEK.md (the exchange file: what
    it is asked to watch for, and how its past reviews went)."""
    try:
        text = open("CLAUDE.md", encoding="utf-8").read()
    except OSError:
        text = ""
    start = text.find("## Il progetto")
    end = text.find("## Consumo di token")
    out = text[start:end] if start >= 0 and end > start else text[:6000]
    try:
        out += "\n\n" + open("DEEPSEEK.md", encoding="utf-8").read()
    except OSError:
        pass
    return out


def ask(pr: dict, diff: str) -> str:
    system = (
        "Sei un revisore di codice esperto (Python/FastAPI, JavaScript vanilla, trading on-chain). "
        "Leggi la pull request e rispondi in italiano, breve. Cerca solo problemi reali: bug, casi limite, "
        "errori di concorrenza, sicurezza (chiavi, firme, soldi degli utenti), regressioni, test che mancano "
        "per un comportamento nuovo. Niente complimenti, niente stile, niente riassunto della PR. "
        "Per ogni problema: file e riga, cosa succede, come correggerlo. Ordina dal piu' grave. "
        "Se non trovi niente di serio scrivi solo: 'Nessun problema serio trovato.'\n\n"
        "Regole del progetto:\n" + rules())
    user = f"Titolo: {pr['title']}\n\nDescrizione:\n{pr.get('body') or ''}\n\nDiff:\n{diff}"
    # deepseek-chat answers in seconds; deepseek-reasoner thinks first
    # (minutes) and can spend the whole max_tokens thinking, answering nothing.
    body = {"model": os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": 8000}
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.loads(r.read())
    u = res.get("usage") or {}
    USAGE.update(at=int(time.time()), **{"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)})
    choice = res["choices"][0]
    text = (choice["message"].get("content") or "").strip()
    if not text:
        raise RuntimeError(f"empty answer (finish_reason={choice.get('finish_reason')})")
    return text


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY not set: skipping")
        return 0
    repo, number = os.environ["GITHUB_REPOSITORY"], int(os.environ["PR_NUMBER"])
    pr = gh(f"/repos/{repo}/pulls/{number}")
    diff = trimmed_diff(gh(f"/repos/{repo}/pulls/{number}", accept="application/vnd.github.diff"))
    if not diff.strip():
        return 0
    try:
        review = ask(pr, diff)
    except Exception as exc:          # a reviewer that is down must not fail the PR
        print(f"DeepSeek did not answer: {exc}")
        return 0
    usage = f"<!-- deepseek-usage {json.dumps(USAGE)} -->" if USAGE else ""
    text = f"{MARK}{usage}\n### Revisione DeepSeek\n\n{review}\n\n<sub>Commit {pr['head']['sha'][:7]} · secondo parere automatico, non vincolante</sub>"
    mine = [c for c in gh(f"/repos/{repo}/issues/{number}/comments?per_page=100") if MARK in (c.get("body") or "")]
    if mine:
        gh(f"/repos/{repo}/issues/comments/{mine[-1]['id']}", "PATCH", {"body": text})
    else:
        gh(f"/repos/{repo}/issues/{number}/comments", "POST", {"body": text})
    return 0


if __name__ == "__main__":
    sys.exit(main())
