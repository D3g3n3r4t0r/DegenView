"""The PR reviewer's own logic (.github/scripts/deepseek_review.py)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("deepseek_review", ROOT / ".github/scripts/deepseek_review.py")
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)


def test_data_and_binary_files_are_left_out():
    diff = ("diff --git a/app.py b/app.py\n+x = 1\n"
            "\ndiff --git a/backend/app/data/resolutions.json b/backend/app/data/resolutions.json\n+{}\n"
            "\ndiff --git a/logo.png b/logo.png\nBinary files differ\n"
            "\ndiff --git a/ui.js b/ui.js\n+y()\n")
    out = dr.trimmed_diff(diff)
    assert "app.py" in out and "ui.js" in out
    assert "resolutions.json" not in out and "logo.png" not in out


def test_a_long_diff_is_cut_and_says_so():
    out = dr.trimmed_diff("diff --git a/a.py b/a.py\n" + "+" * (dr.MAX_DIFF + 500))
    assert len(out) < dr.MAX_DIFF + 100 and out.endswith("too long ...]")


def test_without_a_key_it_skips_quietly(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert dr.main() == 0


def test_the_project_rules_go_along(monkeypatch):
    monkeypatch.chdir(ROOT)
    rules = dr.rules()
    assert "trend-following" in rules and "Consumo di token" not in rules
    assert "Com'è andata" in rules


def test_an_empty_answer_posts_nothing(monkeypatch):
    class R:
        def __init__(self, body):
            self.b = body

        def read(self):
            return __import__("json").dumps(self.b).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(dr.urllib.request, "urlopen",
                        lambda *a, **k: R({"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}))
    import pytest
    with pytest.raises(RuntimeError, match="empty answer"):
        dr.ask({"title": "t", "body": ""}, "diff")
