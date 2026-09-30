"""CLI: bounded, reproducible research on explicit historical data, never DeepSeek.

python -m app.trading.onchain.quant_research dataset.json --timeframes 300 900 3600
  --transitions 86400 259200 --train-end ... --validation-end ... --output report.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from app.trading.onchain.quant_engine import candidates, experiment, fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--timeframes", type=int, nargs="+", required=True)
    parser.add_argument("--transitions", type=int, nargs="*", default=[])
    parser.add_argument("--train-end", type=float, required=True)
    parser.add_argument("--validation-end", type=float, required=True)
    parser.add_argument("--commission", type=float, required=True, help="per-side fraction, e.g. .003")
    parser.add_argument("--slippage", type=float, required=True, help="per-side fraction, e.g. .01")
    parser.add_argument("--min-cases", type=int, default=20)
    parser.add_argument("--min-entries", type=int, default=10)
    parser.add_argument("--strategy", default="Lorenzo HF (minuti on-chain)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--incidents", type=Path, help="optional incident rows with point-in-time features and label_at")
    parser.add_argument("--pattern-rules", type=Path, help="JSON list of predeclared feature/threshold/direction hypotheses")
    parser.add_argument("--pattern-train-end", type=float)
    parser.add_argument("--pattern-validation-end", type=float)
    args = parser.parse_args()
    if args.dataset.stat().st_size > 100_000_000:
        parser.error("dataset exceeds 100 MB budget")
    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    policies = candidates(args.timeframes, args.transitions, args.strategy)
    patterns = None
    if bool(args.incidents) != bool(args.pattern_rules):
        parser.error("--incidents and --pattern-rules are required together")
    if args.incidents:
        from app.trading.onchain.quant_memory import validate_patterns
        if args.incidents.stat().st_size > 20_000_000 or args.pattern_rules.stat().st_size > 100_000:
            parser.error("incident input exceeds budget")
        incidents = json.loads(args.incidents.read_text(encoding="utf-8"))
        if not incidents or max(r["label_at"] for r in incidents) >= min(c["start"] for c in data):
            parser.error("incident rule validation must predate ALL strategy observations")
        if args.pattern_train_end is None or args.pattern_validation_end is None:
            parser.error("separate chronological pattern split boundaries are required")
        patterns = validate_patterns(incidents, json.loads(args.pattern_rules.read_text(encoding="utf-8")),
                                     train_end=args.pattern_train_end, validation_end=args.pattern_validation_end)
        if patterns["status"] != "review_required":
            parser.error("incident rule did not pass independent validation")
        rule = patterns["rule"]
        for c in data:
            value = (c.get("features") or {}).get(rule["feature"])
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                parser.error("pattern feature missing from point-in-time strategy dataset")
            c["risk_blocked"] = value <= rule["threshold"] if rule.get("direction", "le") == "le" else value >= rule["threshold"]
    report = experiment(data, policies, train_end=args.train_end, validation_end=args.validation_end,
                        commission=args.commission, slippage=args.slippage,
                        min_cases=args.min_cases, min_entries=args.min_entries)
    if patterns:
        report["patterns"] = patterns
    report["report_hash"] = fingerprint(report)
    # Reports never overwrite an earlier experiment or activate a strategy.
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2, allow_nan=False)
    print(json.dumps({"status": report["status"], "reason": report["reason"], "report": str(args.output), "llm_calls": 0}))


if __name__ == "__main__":
    main()
