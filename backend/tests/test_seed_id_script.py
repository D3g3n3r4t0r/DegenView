"""scripts/seed_id.py: board ids that two parallel chats cannot both take.

The texts below reproduce 23/10: this branch added seed-0403l while the other
chat had already landed its own seed-0403l on main."""
import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "seed_id", Path(__file__).resolve().parents[2] / "scripts" / "seed_id.py")
seed_id = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seed_id)

ISSUES, RES, REP, HO = seed_id.ISSUES, seed_id.RESOLUTIONS, seed_id.REPLIES, seed_id.HANDOVER


def _issues(*entries):
    rows = "".join(f'    ("{sid}", "{title}",\n     "detail",\n     "media"),\n' for sid, title in entries)
    return f"_SEED = [\n{rows}]\n"


def _res(*entries):
    return json.dumps({sid: {"status": "risolto", "summary": s} for sid, s in entries}, indent=2, ensure_ascii=False) + "\n"


BASE = {
    ISSUES: _issues(("seed-0403l", "Their cluster limit"), ("seed-0402l", "Cantiere bars")),
    RES: _res(("seed-0403l", "limit removed"), ("seed-0402l", "bars")),
    REP: "{}\n",
    HO: "# 23/10 — cluster limit — `seed-0403l`\nold line\n",
}


def _work_after_rebase():
    """Both entries present, as after a clean rebase: the trap json.load hides."""
    res = BASE[RES].replace('{\n', '{\n  "seed-0403l": {\n    "status": "risolto",\n    "summary": "drag fixed"\n  },\n', 1)
    return {
        ISSUES: _issues(("seed-0403l", "Drawing drag"), ("seed-0403l", "Their cluster limit"), ("seed-0402l", "Cantiere bars")),
        RES: res,
        REP: "{}\n",
        HO: "- drag fix (`seed-0403l`): mine\n" + BASE[HO],
    }


def test_next_id_is_one_past_the_highest_number_of_any_letter():
    work = {ISSUES: _issues(("seed-0399g", "x")), RES: "{}", REP: "{}", HO: ""}
    assert seed_id.next_id(BASE, work, "l") == "seed-0404l"
    assert seed_id.next_id(BASE, work, "g") == "seed-0404g"


def test_a_clean_branch_has_no_collisions():
    work = dict(BASE)
    work[ISSUES] = _issues(("seed-0404l", "Drawing drag"), ("seed-0403l", "Their cluster limit"))
    assert seed_id.collisions(BASE, work) == []


def test_the_23_10_collision_is_caught_even_when_git_merges_cleanly():
    problems = seed_id.collisions(BASE, _work_after_rebase())
    assert any("two _SEED entries" in p for p in problems)
    assert any("key written twice" in p and RES in p for p in problems)


def test_a_stale_branch_reusing_a_landed_id_is_caught():
    work = {ISSUES: _issues(("seed-0403l", "Drawing drag")), RES: "{}", REP: "{}", HO: ""}
    assert any("origin/main already uses it" in p for p in seed_id.collisions(BASE, work))


def test_fix_moves_only_this_branchs_entry():
    work = _work_after_rebase()
    changed = seed_id.rename(BASE, work, "seed-0403l", "seed-0404l")
    merged = {**work, **changed}
    titles = seed_id.seed_titles(merged[ISSUES])
    assert ("seed-0404l", "Drawing drag") in titles
    assert ("seed-0403l", "Their cluster limit") in titles
    res = json.loads(merged[RES])
    assert res["seed-0404l"]["summary"] == "drag fixed"
    assert res["seed-0403l"]["summary"] == "limit removed"
    assert "`seed-0404l`): mine" in merged[HO]
    assert "cluster limit — `seed-0403l`" in merged[HO]       # their HANDOVER line untouched
    assert seed_id.collisions(BASE, merged) == []


def test_the_letter_comes_from_the_email_fingerprint():
    assert seed_id.letter_for_email("someone@example.com") == "l"
