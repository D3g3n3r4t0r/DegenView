"""Site languages (16/10): English default, dictionaries in static/i18n/."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "frontend"
LANG_DIR = ROOT / "static" / "i18n"


def _langs_in_js() -> dict[str, str]:
    src = (ROOT / "static" / "i18n.js").read_text()
    body = re.search(r"const LANGS = \{([^}]*)\}", src).group(1)
    return dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", body))


def test_english_is_default_and_every_other_language_has_a_file():
    langs = _langs_in_js()
    assert "en" in langs
    for code in langs:
        if code != "en":
            assert (LANG_DIR / f"{code}.json").exists(), code


def test_dictionaries_are_valid():
    for f in LANG_DIR.glob("*.json"):
        data = json.loads(f.read_text())
        assert data["lang"] == f.stem
        assert data["strings"], f
        for k, v in data["strings"].items():
            assert k == " ".join(k.split()), f"key not normalised: {k!r}"
            assert isinstance(v, str) and v
        for pat, rep in data.get("patterns", []):
            re.compile(pat)   # JS and Python agree on the subset we use
            assert isinstance(rep, str)


def test_engine_loads_before_the_app():
    html = (ROOT / "index.html").read_text()
    assert html.index("/static/i18n.js") < html.index("/static/app.js")
