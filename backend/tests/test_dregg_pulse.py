from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

try:
    from app.trading.onchain import dregg_pulse
except ImportError:  # pragma: no cover
    _spec = importlib.util.spec_from_file_location(
        "dregg_pulse",
        Path(__file__).resolve().parents[1] / "app" / "trading" / "onchain" / "dregg_pulse.py",
    )
    assert _spec and _spec.loader
    dregg_pulse = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(dregg_pulse)  # type: ignore[union-attr]


def test_parse_size_md_extracts_nanodregg_metrics():
    sample = """# Size
| Metric | Value | Ceiling |
|---|---|---|
| Lean modules | 502 | 600 |
| Lean lines (Kernel) | 149055 | — |
| Rust lines | 21484 | 30000 |
| theorems | 6305 | — |
| sorry | 0 | 0 |
| partial defs (deployed) | 0 | 0 |
| conformance rows | 45 | — |
"""
    parsed = dregg_pulse._parse_size_md(sample)
    assert parsed["lean_modules"] == 502
    assert parsed["lean_lines"] == 149055
    assert parsed["lean_theorems"] == 6305
    assert parsed["lean_sorry"] == 0
    assert parsed["lean_partial"] == 0
    assert parsed["rust_lines"] == 21484
    assert parsed["conformance_rows"] == 45


def test_build_mainnet_roadmap_computes_three_phases():
    roadmap = dregg_pulse._build_mainnet_roadmap(
        dregg_pulse._BASELINE_TECH_TREE,
        dregg_pulse._BASELINE_HORIZON,
        dregg_pulse._BASELINE_SIZE_METRICS,
    )
    assert 55.0 <= roadmap["overall_weighted_pct"] <= 80.0
    assert 35.0 <= roadmap["overall_strict_pct"] <= 60.0
    phases = roadmap["phases"]
    assert len(phases) == 3
    assert phases[0]["eta_label"] == "1 – 2 mesi"
    assert phases[1]["eta_label"] == "3 – 4 mesi"
    assert phases[2]["eta_label"] == "6 – 9+ mesi"


def test_get_dregg_pulse_returns_complete_multi_repo_payload():
    data = asyncio.run(dregg_pulse.get_dregg_pulse(force=False))
    assert data["token"] == dregg_pulse.DREGG_MINT
    assert data["symbol"] == "DREGG"
    assert data["github_summary"]["repos_tracked"] == 8
    assert data["github_summary"]["total_commits_all_repos"] >= 16000
    assert data["nanodregg_ratchet"]["lean_theorems"] >= 6305
    assert data["nanodregg_ratchet"]["lean_sorry"] == 0
    assert len(data["repos"]) == 8
    assert len(data["contributors"]) >= 6
    assert len(data["mainnet_roadmap"]["phases"]) == 3
