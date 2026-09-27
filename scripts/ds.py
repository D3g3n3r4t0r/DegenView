#!/usr/bin/env python3
"""Ask DeepSeek for a code draft, from Claude's sandbox.

Lorenzo, 27/09: "devi usare intensamente deepseek per aiutarti nel coding
[...] voglio che deepseek riduca drasticamente il tuo consumo di token".
Claude writes the task, DeepSeek writes the code (the expensive, long part),
Claude reviews, runs the checks and fixes what is wrong.

Needs DEEPSEEK_API_KEY in the environment and api.deepseek.com allowed by
the network policy (cloud environment settings).

    python3 scripts/ds.py "task in words" path/a.py path/b.js:120-260 > /tmp/draft.txt

Files are sent whole, or as a line range with :start-end. The answer is
SEARCH/REPLACE blocks (the same shape as Claude's Edit tool), printed to
stdout; tokens used go to stderr. Nothing is applied: `--apply` writes the
blocks to the files and reports any that did not match.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

SYSTEM = """You write code changes for this repository as SEARCH/REPLACE blocks:

<<<<<<< SEARCH path/to/file
exact existing lines (enough to be unique)
=======
new lines
>>>>>>> REPLACE

Empty SEARCH = new file. Copy SEARCH exactly. Change only what the task needs, match the
surrounding style (comments and names in English), add tests when behaviour changes.
No prose outside the blocks.

Project rules:
"""
BLOCK = re.compile(r"<<<<<<< SEARCH (\S+)\n(.*?)\n?=======\n(.*?)\n?>>>>>>> REPLACE", re.S)


def context(specs: list[str]) -> str:
    parts = []
    for spec in specs:
        path, _, rng = spec.partition(":")
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        a, b = (int(x) for x in rng.split("-")) if rng else (1, len(lines))
        parts.append(f"### {path} (lines {a}-{min(b, len(lines))} of {len(lines)})\n" + "\n".join(lines[a - 1:b]))
    return "\n\n".join(parts)


def ask(task: str, files: list[str]) -> str:
    rules = Path("CLAUDE.md").read_text(encoding="utf-8") if Path("CLAUDE.md").exists() else ""
    body = {"model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"), "temperature": 0, "max_tokens": 8000,
            "messages": [{"role": "system", "content": SYSTEM + rules[:6000]},
                         {"role": "user", "content": f"Task:\n{task}\n\nFiles:\n{context(files)}"}]}
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.loads(r.read())
    u = res.get("usage") or {}
    print(f"[deepseek] {u.get('prompt_tokens')} in, {u.get('completion_tokens')} out", file=sys.stderr)
    return res["choices"][0]["message"]["content"]


def apply(text: str) -> int:
    bad = 0
    for path, search, replace in BLOCK.findall(text):
        p = Path(path)
        if not search.strip():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(replace + "\n", encoding="utf-8")
            continue
        src = p.read_text(encoding="utf-8") if p.exists() else ""
        if src.count(search) != 1:
            print(f"[deepseek] no unique match in {path}:\n{search[:300]}", file=sys.stderr)
            bad += 1
            continue
        p.write_text(src.replace(search, replace, 1), encoding="utf-8")
    return bad


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--apply"]
    if not args or not os.environ.get("DEEPSEEK_API_KEY"):
        sys.exit("usage: DEEPSEEK_API_KEY=... ds.py 'task' file[:a-b] ... [--apply]")
    out = ask(args[0], args[1:])
    print(out)
    if "--apply" in sys.argv:
        sys.exit(1 if apply(out) else 0)
