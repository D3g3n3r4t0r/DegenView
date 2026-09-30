# Claude: review and apply PR #408

User request: Codex implemented the code; minimize remaining application work. User subsequently authorized Claude to continue what remains. Do not recreate the architecture or turn this back into a prompt-only plan.

## Starting point
Use branch `codex/deterministic-gem-engine-2026-09-30`, PR #408. This commit integrates main at b0e83d5, preserving #409 resolutions and #410 Scout cube. It includes the Agent map code from #402: do not separately cherry-pick #402 over this integration.

Already implemented: deterministic bounded chronological research, durable versioned outcomes and closed candles, prospective 1/7/30-day windows, gem-only trend entry gate, authenticated local evidence API, Agent map plus quantitative panel, persisted signal consumption, serialized trading ticks, paper-only approval, fresh-quote gating and tests.

## Minimal review sequence
1. Check out this branch and run the new Quantitative engine checks workflow. Commands are in that workflow; final local results are 47 Python + 8 Node tests passed and full-backend Ruff passed.
2. Run the full backend suite on Linux with the repository's dependencies. The local Windows restricted-network attempt produced 1438 passed / 23 failed / 1 skipped. Check the two non-network failures: test_agent_log::test_ai_calls_and_tokens_stay_apart_from_notes (negative Unix timestamp on Windows) and test_deepseek_review::test_the_project_rules_go_along (rules text expectation). The other 21 involve live chain/quote dependencies. No tests were deleted or marked skipped to hide this.
3. Review API authorization, current production gem fields and birth provenance; verify collector persistence on a staging volume. Verify exit behavior for existing positions and manual reconciliation of uncertain real attempts. Confirm one backend worker owns the trading loop; the tick guard is process-local.
4. Confirm Agent mounts correctly with actual authenticated APIs, including disconnected/error states. The local browser check used explicitly labelled fixtures. Full score contribution/counterfactual receipt visualization remains outside this completed map integration.
5. Only then consider merge/deploy. Missing quant_approved.json intentionally blocks NEW entries. Collection works without approval; never invent a winning policy to bypass the gate.
6. Collect enough real point-in-time history, preregister costs and chronological split boundaries, run the CLI, independently review the report, then authorize PAPER mode. REAL approval needs an actual paper_run_id and venue-specific execution validation.

## Known follow-ups (do not mistake these for validated results)
- Durable replay avoids rolling-window eviction, but full-history CPU/disk usage grows. Benchmark before large-scale operation; incremental checkpointing is not implemented.
- Current simulator covers proportional commission/slippage, not gas, transfer taxes, market impact or portfolio interactions. Missing/dead-token candle coverage can block validation rather than fabricate fills.
- No deployer-family grouping/confidence intervals: project-level train/validation/test isolation is implemented, not a complete statistical research platform.
- Existing approved tokens keep their pinned policy; approval replacement blocks their new entries until a deliberate migration. Preserve exits when planning migration.
- Quant panel report refresh currently rebuilds report disclosure rows, so an open disclosure may close on polling; polish if needed.
- Review outage exits in paper mode: missing signal history must not be reported as a verified fill. The real path requests an exit through existing execution guards.
- No production dataset or server policy was touched. No DeepSeek call is introduced by these modules or their UI refresh.

See QUANT_ENGINE.md for data contract and CLI examples. Keep this PR draft until review is complete; do not state that the full suite or profitability passed.
