"""Board ids (seed-NNNN + account letter) without collisions between chats.

Two chats working in parallel, even from the same account, picked the same
number three times on 23/10 (seed-0398l, seed-0401l, seed-0403l). The letter
tells accounts apart, not chats: the number has to be checked against what
has landed on origin/main in the meantime, and that check has to be cheap.

    python scripts/seed_id.py next --letter l    # first free id on origin/main
    python scripts/seed_id.py check              # do my new ids collide? exit 1 if so
    python scripts/seed_id.py fix seed-0403l     # move MY entry to the next free id

`fix` renames only what this branch added: the _SEED tuple, the
resolutions.json / replies.json block and the HANDOVER.md lines that are not
on origin/main. Commit messages already pushed are not rewritten.

Run from the repository root. Needs a remote called origin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ISSUES = "backend/app/issues.py"
RESOLUTIONS = "backend/app/data/resolutions.json"
REPLIES = "backend/app/data/replies.json"
HANDOVER = "HANDOVER.md"
FILES = (ISSUES, RESOLUTIONS, REPLIES, HANDOVER)

# CLAUDE.md: the sha256 of the user's email decides the letter (never the email itself).
G_FINGERPRINT = "31481b16338555f6c4ee68b1c0f22747f7bdafa5b3def21a9a8fcead8b944c09"

_NUM_ID = re.compile(r"\bseed-(\d{4})([a-z]?)\b")
_SEED_TUPLE = re.compile(r'^\s*\(\s*"(seed-[^"]+)",\s*"([^"]*)"', re.M)


# ---- pure helpers (tested in backend/tests/test_seed_id_script.py) ----------

def seed_titles(issues_text: str) -> list[tuple[str, str]]:
    """(id, title) of every _SEED tuple, in file order."""
    return _SEED_TUPLE.findall(issues_text)


def json_pairs(text: str) -> list[tuple[str, object]]:
    """Top-level keys in file order, duplicates kept (json.load drops them)."""
    if not text.strip():
        return []
    pairs = json.loads(text, object_pairs_hook=lambda p: p)
    return [(k, v) for k, v in pairs]


def max_number(files: dict[str, str]) -> int:
    nums = [int(m.group(1)) for text in files.values() for m in _NUM_ID.finditer(text)]
    return max(nums, default=0)


def next_id(base: dict[str, str], work: dict[str, str], letter: str) -> str:
    """One past the highest number on origin/main or in this branch, any letter."""
    return f"seed-{max(max_number(base), max_number(work)) + 1:04d}{letter}"


def collisions(base: dict[str, str], work: dict[str, str]) -> list[str]:
    """Human-readable problems; empty when the branch is safe to merge."""
    problems = []
    work_seed = seed_titles(work.get(ISSUES, ""))
    base_seed = dict(seed_titles(base.get(ISSUES, "")))
    seen: dict[str, str] = {}
    for sid, title in work_seed:
        if sid in seen and seen[sid] != title:
            problems.append(f"{sid}: two _SEED entries ({seen[sid][:50]!r} / {title[:50]!r})")
        seen.setdefault(sid, title)
        if sid in base_seed and base_seed[sid] != title:
            problems.append(f"{sid}: origin/main already uses it for {base_seed[sid][:60]!r}")
    for name in (RESOLUTIONS, REPLIES):
        keys = [k for k, _ in json_pairs(work.get(name, ""))]
        dup = sorted({k for k in keys if keys.count(k) > 1})
        for k in dup:
            problems.append(f"{k}: key written twice in {name} (only the last one is read)")
    return problems


def _blocks(text: str, key: str) -> list[tuple[int, int]]:
    """Spans of each top-level `"key": ...` member of a 2-space indented JSON file."""
    spans = []
    for m in re.finditer(r'^  "%s":' % re.escape(key), text, re.M):
        nxt = re.compile(r'^  "|^}', re.M).search(text, m.end())
        spans.append((m.start(), nxt.start() if nxt else len(text)))
    return spans


def rename(base: dict[str, str], work: dict[str, str], old: str, new: str) -> dict[str, str]:
    """New texts for the files where this branch's `old` entry becomes `new`.

    Only what origin/main does not have is touched, so the other chat's entry
    with the same id stays as it is."""
    out = {}
    # _SEED: the tuple whose title origin/main does not know under `old`
    text = work.get(ISSUES, "")
    base_title = dict(seed_titles(base.get(ISSUES, ""))).get(old)
    for m in _SEED_TUPLE.finditer(text):
        if m.group(1) == old and m.group(2) != base_title:
            start = m.start(1)
            text = text[:start] + new + text[start + len(old):]
            out[ISSUES] = text
            break
    # JSON files: the block whose value differs from every origin/main block for `old`
    for name in (RESOLUTIONS, REPLIES):
        text = work.get(name, "")
        if not text:
            continue
        base_values = [v for k, v in json_pairs(base.get(name, "")) if k == old]
        for start, end in reversed(_blocks(text, old)):
            chunk = text[start:end].rstrip().rstrip(",")
            value = json.loads("{" + chunk + "}", object_pairs_hook=lambda p: p)[0][1]
            if value not in base_values:
                text = text[:start] + text[start:end].replace(f'"{old}"', f'"{new}"', 1) + text[end:]
                out[name] = text
    # HANDOVER.md: lines this branch added
    text = work.get(HANDOVER, "")
    base_lines = set(base.get(HANDOVER, "").splitlines())
    lines = text.splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        if old in line and line.rstrip("\n") not in base_lines:
            lines[i] = re.sub(r"\b%s\b" % re.escape(old), new, line)
            changed = True
    if changed:
        out[HANDOVER] = "".join(lines)
    return out


def letter_for_email(email: str) -> str:
    return "g" if hashlib.sha256(email.strip().lower().encode()).hexdigest() == G_FINGERPRINT else "l"


# ---- git plumbing -----------------------------------------------------------

def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def _base_files() -> dict[str, str]:
    subprocess.run(["git", "fetch", "-q", "origin", "main"], check=True)
    out = {}
    for name in FILES:
        try:
            out[name] = _git("show", f"origin/main:{name}")
        except subprocess.CalledProcessError:
            out[name] = ""
    return out


def _work_files() -> dict[str, str]:
    return {name: (Path(name).read_text(encoding="utf-8") if Path(name).exists() else "") for name in FILES}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_next = sub.add_parser("next", help="first free id")
    p_next.add_argument("--letter", choices=["g", "l"])
    p_next.add_argument("--email", help="decide the letter from this email's fingerprint (never stored)")
    sub.add_parser("check", help="exit 1 if this branch's ids collide")
    p_fix = sub.add_parser("fix", help="move this branch's entry to a free id")
    p_fix.add_argument("old")
    p_fix.add_argument("new", nargs="?")
    args = ap.parse_args(argv)

    base, work = _base_files(), _work_files()
    if args.cmd == "next":
        if not (args.letter or args.email):
            ap.error("next needs --letter or --email")
        print(next_id(base, work, args.letter or letter_for_email(args.email)))
        return 0
    if args.cmd == "check":
        problems = collisions(base, work)
        for line in problems:
            print("COLLISION", line)
        if problems:
            print("Fix: python scripts/seed_id.py fix <id>  (then amend the commit message)")
            return 1
        print("ok: no seed id collisions with origin/main")
        return 0
    m = _NUM_ID.fullmatch(args.old)
    new = args.new or next_id(base, work, m.group(2) if m else "l")
    changed = rename(base, work, args.old, new)
    if not changed:
        print(f"nothing of this branch uses {args.old}")
        return 1
    for name, text in changed.items():
        Path(name).write_text(text, encoding="utf-8")
        print(f"{name}: {args.old} -> {new}")
    print(f"Now: amend commit messages that mention {args.old}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
