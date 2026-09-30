"""Every browser module must parse as an ES module.

`node --check file.js` parses a .js file as CommonJS first and let a broken
regex in sheets.js through (`/^https:///` turned the rest of the line into a
comment). One syntax error in any module stops the whole import graph, so the
app shows its first paint and no tap does anything. Copying to .mjs forces the
module grammar the browser uses.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "static"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("path", sorted(FRONTEND.glob("onchain/*.js")), ids=lambda p: p.name)
def test_module_parses(path, tmp_path):
    copy = tmp_path / (path.stem + ".mjs")
    copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run([NODE, "--check", str(copy)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
