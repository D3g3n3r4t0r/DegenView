"""DeepSeek as a coding worker through GitHub, reviewed by Claude.

Lorenzo, 27/09: "devi usare deepseek assiduamente, voglio ridurre
drasticamente il consumo di token con te [...] non devi usarli nel tuo
ambiente ma comunicarci tramite github".

Claude opens an issue labelled `deepseek`:

    <the task, in plain words>

    Files:
    - backend/app/foo.py
    - backend/app/main.py:3800-3900

    Tests:
    - backend/tests/test_foo.py

`generate` (DeepSeek key, no GitHub token) asks for SEARCH/REPLACE edits,
applies them, runs ruff and the listed tests, retries once with the errors,
and writes .deepseek-result.json. `publish` (GitHub token, runs none of the
generated code) pushes a branch and opens a pull request. Nothing merges by
itself: Claude reviews every PR, fixes it and merges.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

RESULT = Path(".deepseek-result.json")
MAX_CONTEXT = 120_000
RELATED_MAX = 10
EDIT = re.compile(r"<<<<<<< SEARCH (\S+)\n(.*?)\n?=======\n(.*?)\n?>>>>>>> REPLACE", re.S)
APPEND = re.compile(r"<<<<<<< APPEND (\S+)\n(.*?)\n?>>>>>>> END", re.S)
SYSTEM = """You change this repository with SEARCH/REPLACE blocks:

<<<<<<< SEARCH path/to/file
exact existing lines, enough to be unique
=======
new lines
>>>>>>> REPLACE

To add lines at the end of an existing file (CSS rules, new functions) use:

<<<<<<< APPEND path/to/file
new lines
>>>>>>> END

A SEARCH must match exactly one place: include a neighbouring line that is unique.
Every file the task names as new must be created (empty SEARCH), and every module you import
must exist. When a behaviour changes, update the old tests that asserted the old behaviour.

First line of your answer: `TITLE: <English commit title, imperative>`. Second line:
`ITALIAN: <one Italian sentence on what changes for the site's users>`. Then only the
blocks. Empty SEARCH = new file. Change only what the task needs, match the style,
add tests when behaviour changes. Never touch .github/.

Project rules:
"""


def parse_issue(body: str) -> dict:
    task, files, tests, section = [], [], [], "task"
    lines = (body or "").splitlines()
    # Only the last "Files:" opens the lists: a "Tests:" inside the task text stays task text.
    marks = [i for i, line in enumerate(lines) if line.strip().lower() == "files:"]
    start = marks[-1] if marks else len(lines)
    task, lines = lines[:start], lines[start:]
    for line in lines:
        low = line.strip().lower()
        if low in ("files:", "tests:"):
            section = low[:-1]
            continue
        item = line.strip()[2:].split()[0].strip("`") if line.strip().startswith("- ") and len(line.strip()) > 2 else None
        if section == "files" and item:
            files.append(item)
        elif section == "tests" and item:
            tests.append(item)
        elif section == "task":
            task.append(line)
    return {"task": "\n".join(task).strip(), "files": files, "tests": tests}


def context(specs: list[str]) -> str:
    out, used = [], 0
    for spec in specs:
        path, _, rng = spec.partition(":")
        p = Path(path)
        if not p.exists():
            out.append(f"### {path} (new file)")
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        a, b = (int(x) for x in rng.split("-", 1)) if "-" in rng else (1, len(lines))
        chunk = "\n".join(lines[a - 1:b])[:max(0, MAX_CONTEXT - used)]
        used += len(chunk)
        out.append(f"### {path} (lines {a}-{min(b, len(lines))} of {len(lines)})\n{chunk}")
    return "\n\n".join(out)


def apply(text: str) -> list[str]:
    errors, n = [], 0
    for path, search, replace in EDIT.findall(text):
        n += 1
        # The model sometimes writes "path=x", "`x`" or "x:" instead of the bare path.
        path = path.removeprefix("path=").strip("`'\":")
        p = Path(path)
        if path == "path/to/file":
            errors.append(f"{path}: the example path from the instructions, not a file of the task")
            continue
        if path.startswith((".github/", "/")) or ".." in p.parts:
            errors.append(f"{path}: not allowed")
            continue
        if not search.strip():
            if p.exists():
                errors.append(f"{path}: empty SEARCH on an existing file")
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(replace + "\n", encoding="utf-8")
            continue
        if not p.exists():
            errors.append(f"{path}: no such file (write the bare path after SEARCH)")
            continue
        src = p.read_text(encoding="utf-8")
        if src.count(search) != 1:
            errors.append(f"{path}: SEARCH found {src.count(search)} times:\n{search[:300]}")
            continue
        p.write_text(src.replace(search, replace, 1), encoding="utf-8")
    for path, text_ in APPEND.findall(text):
        n += 1
        path = path.removeprefix("path=").strip("`'\":")
        p = Path(path)
        if path == "path/to/file" or path.startswith((".github/", "/")) or ".." in p.parts or not p.exists():
            errors.append(f"{path}: cannot append (missing file or path not allowed)")
            continue
        src = p.read_text(encoding="utf-8")
        p.write_text(src + ("" if src.endswith("\n") else "\n") + text_ + "\n", encoding="utf-8")
    return errors if n else ["no SEARCH/REPLACE block"]


def ask(messages: list[dict]) -> tuple[str, dict]:
    body = {"model": os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat", "messages": messages,
            "max_tokens": 8000, "temperature": 0}
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.loads(r.read())
    return res["choices"][0]["message"].get("content") or "", res.get("usage") or {}


def changed() -> list[str]:
    """Files the answer created or modified (the result file aside)."""
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                         capture_output=True, text=True).stdout
    return [line[3:].strip() for line in out.splitlines() if line[3:].strip() != RESULT.name]


IMPORT = re.compile(r"""(?:from\s+|import\s*\(?\s*)["']@onchain/([\w.-]+\.js)["']""")


def related_tests(files: list[str]) -> list[str]:
    """Tests that import a backend module the answer touched: a change can
    break an old test nobody listed (#189 broke test_system.py)."""
    stems = {Path(f).stem for f in files if f.startswith("backend/app/") and f.endswith(".py")}
    # main.py is imported by half the suite: its tests would run for more
    # than the 15-minute budget (#226 timed out on 34 files).
    stems -= {"__init__", "main"}
    if not stems:
        return []
    pat = re.compile(r"^\s*(?:from|import)\s[^\n]*\b(" + "|".join(map(re.escape, stems)) + r")\b", re.M)
    found = sorted(str(t) for t in Path("backend/tests").glob("test_*.py") if pat.search(t.read_text(encoding="utf-8")))
    return found[:RELATED_MAX]


def js_problems(files: list[str]) -> list[str]:
    """Syntax of every touched frontend module, and every @onchain import it
    names must exist (#188 imported nozoom.js without writing it)."""
    import shutil
    import tempfile
    errors = []
    node = shutil.which("node")
    for f in files:
        if not (f.startswith("frontend/") and f.endswith(".js")) or not Path(f).exists():
            continue
        src = Path(f).read_text(encoding="utf-8")
        for name in IMPORT.findall(src):
            if not Path("frontend/static/onchain", name).exists():
                errors.append(f"{f}: imports @onchain/{name}, which does not exist")
        if node:
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d, Path(f).stem + ".mjs")
                tmp.write_text(src, encoding="utf-8")
                r = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True)
                if r.returncode:
                    errors.append(f"{f}: syntax error\n{r.stderr[-1500:]}")
    return errors


def checks(tests: list[str]) -> str:
    env = {k: v for k, v in os.environ.items() if k not in ("DEEPSEEK_API_KEY", "GITHUB_TOKEN")}
    files = changed()
    if not files:
        return "no file changed: the answer did nothing"
    log = js_problems(files)
    tests = sorted({t.removeprefix("backend/") for t in [*tests, *related_tests(files)]})
    cmds = [(["ruff", "check", "backend/", "--select", "E,F,W", "--ignore", "E501"], ".")]
    if tests:
        cmds.append(([sys.executable, "-m", "pytest", "-q", "-x", *tests], "backend"))
    for cmd, cwd in cmds:
        try:
            r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            log.append(f"$ {' '.join(cmd)}\ntimed out after 10 minutes")
            continue
        if r.returncode:
            log.append(f"$ {' '.join(cmd)}\n{(r.stdout + r.stderr)[-4000:]}")
    return "\n\n".join(log)


def generate() -> int:
    issue = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())["issue"]
    spec = parse_issue(issue.get("body") or "")
    rules = Path("CLAUDE.md").read_text(encoding="utf-8")[:8000] if Path("CLAUDE.md").exists() else ""
    # Its own past mistakes, kept by Claude after each review (Lorenzo, 28/09:
    # "istruisci deepseek per migliorarlo nei suoi compiti ogni volta che
    # sbaglia"). Under .github/, so the worker can read it but never edit it.
    lessons = Path(".github/deepseek/LESSONS.md")
    lessons = lessons.read_text(encoding="utf-8")[:6000] if lessons.exists() else ""
    messages = [{"role": "system", "content": SYSTEM + lessons + "\n\n" + rules},
                {"role": "user", "content": f"Task #{issue['number']}: {issue['title']}\n{spec['task']}\n\nFiles:\n{context(spec['files'])}"}]
    usage, result = {"in": 0, "out": 0}, {"ok": False, "title": issue["title"], "italian": "", "log": "", "attempts": 0}
    for attempt in range(2):
        result["attempts"] = attempt + 1
        answer, u = ask(messages)
        usage["in"] += u.get("prompt_tokens", 0)
        usage["out"] += u.get("completion_tokens", 0)
        if m := re.search(r"^TITLE:\s*(.+)$", answer, re.M):
            result["title"] = m[1].strip()[:72]
        if m := re.search(r"^ITALIAN:\s*(.+)$", answer, re.M):
            result["italian"] = m[1].strip()
        subprocess.run(["git", "checkout", "--", "."])
        subprocess.run(["git", "clean", "-fdq", "-e", RESULT.name])
        errors = apply(answer)
        log = "\n".join(errors) if errors else checks(spec["tests"])
        result["log"] = log[-6000:]
        if not log:
            result["ok"] = True
            break
        messages += [{"role": "assistant", "content": answer},
                     {"role": "user", "content": f"That failed:\n{log[-6000:]}\nSend all corrected blocks again against the ORIGINAL files."}]
    result["usage"] = usage
    RESULT.write_text(json.dumps(result))
    return 0


def gh(path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def publish() -> int:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    repo, number = os.environ["GITHUB_REPOSITORY"], event["issue"]["number"]
    res = json.loads(RESULT.read_text()) if RESULT.exists() else {"ok": False, "log": "no result", "usage": {}}
    RESULT.unlink(missing_ok=True)
    u = res.get("usage") or {}
    marker = f"<!-- deepseek-usage {json.dumps({'in': u.get('in', 0), 'out': u.get('out', 0), 'task': number})} -->"
    if not res.get("ok"):
        gh(f"/repos/{repo}/issues/{number}/comments", "POST",
           {"body": f"{marker}\nDeepSeek did not make it in {res.get('attempts')} attempts.\n\n```\n{res.get('log', '')[-3000:]}\n```"})
        return 0
    branch = f"deepseek/issue-{number}"
    for cmd in (["git", "config", "user.name", "deepseek-worker"],
                ["git", "config", "user.email", "deepseek-worker@users.noreply.github.com"],
                ["git", "checkout", "-B", branch], ["git", "add", "-A"],
                ["git", "commit", "-q", "-m", f"{res['title']}\n\nDrafted by DeepSeek for #{number}.\n\nAggiornamento: {res.get('italian') or res['title']}"],
                ["git", "push", "-f", f"https://x-access-token:{os.environ['GITHUB_TOKEN']}@github.com/{repo}.git", branch]):
        subprocess.run(cmd, check=True)
    body = f"{marker}\nDrafted by DeepSeek for #{number} ({res.get('attempts')} attempts, {u.get('in', 0)} tokens in, {u.get('out', 0)} out). Checks passed. **Claude reviews before merging.**"
    try:
        pr = gh(f"/repos/{repo}/pulls", "POST", {"title": res["title"], "head": branch,
                                                   "base": event["repository"]["default_branch"], "body": body})
        note = f"PR ready for Claude's review: {pr['html_url']}"
    except urllib.error.HTTPError as exc:
        # The repository does not let Actions open pull requests (Settings >
        # Actions > General): the branch is pushed, Claude opens the PR.
        note = f"Branch `{branch}` pushed ({exc.code} opening the PR): Claude opens it and reviews."
    gh(f"/repos/{repo}/issues/{number}/comments", "POST", {"body": f"{marker}\n{note}"})
    return 0


if __name__ == "__main__":
    sys.exit({"generate": generate, "publish": publish}[sys.argv[1]]())
