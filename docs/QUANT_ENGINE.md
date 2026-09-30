# Deterministic gem/sniper research engine

This is executable code, not a DeepSeek task or prompt. Research, incident
archiving, metrics, selection and signal evaluation make **zero model calls**.
Integration base: `b0e83d5d053e379ab8c5c86dea8c2433440ac7f6`. Includes the Agent map from #402 and preserves the Scout cube from main.

## What changes

* `quant_engine.py`: bounded search of fixed intervals and increasing two-stage
  schedules. Age transition boundaries are explicit research inputs, not defaults
  for trading. The replay accepts up to six stages for future preregistered grids.
* Uses the existing Lorenzo / Lorenzo HF implementations and spot-only conversion.
  No replacement trend indicator. Signal on a completed candle, execution at the
  following available base candle open, costs both ways. No entry just because an
  alert exists or a trend was already active before observation.
* Timeframe switches occur while flat. An open trade retains its entry interval.
* Chronological train / validation / untouched-test cohorts, whole projects kept
  separate and crossing windows purged. Winner chosen on train only; validation
  may select the fixed baseline instead. Holdout can reject, never pick another
  winner. Progressive winner must beat its fixed baseline on holdout too. Slippage
  is doubled in a separate stress run. These gates are not statistical proof of
  profitability; the result is `review_required`, never automatic activation.
* `quant_memory.py`: records public outcomes before the journal prunes them, with
  deduplicated append-only versions in the existing `observatory.sqlite3` file.
  Price crashes and missing pools remain **suspected incidents**, not proven fraud.
  Non-incidents and unknowns are retained too. Historical import time is honest.
* Patterns require support, incident lift and a maximum healthy-project rejection
  rate, separately on train/validation/test. Pattern validation must precede the
  entire strategy dataset. The selected filter is applied in the strategy replay
  too: rejected tokens keep cash, rather than disappearing from the denominator.
* `quant_runtime.py`: verified report + explicit local approval + paper run reference
  required. Current gem qualification, non-meme name filter, non-missing liquidity
  and fresh market data are checked before new entries. Unknown pattern features
  block an entry. A CEX listing does not bypass these rules.
* Autotrader real and paper entry paths both use this gate. Existing positions
  without a quant policy retain legacy exits. New positions retain their selected
  policy; future approvals do not rewrite it. Missing/stale quant evidence causes
  real positions to request an exit through the existing order machinery.

**Deployment changes new-entry behavior:** without `quant_approved.json`, new
autotrader entries stop. This is intentional: do not merge/deploy without reviewing
that migration. Discovery feeds and historical meme alerts remain available for
research; this PR filters execution rather than deleting their history. It does
not complete the Agent-map UI, change wallet sizing, or bypass execution controls.

## Reproducible runs

From `backend`, Python 3.12 with the repository dependencies:

```sh
python -m app.trading.onchain.quant_memory cases cases.json
python -m app.trading.onchain.quant_memory incidents incidents.json
python -m app.trading.onchain.quant_research cases.json \
  --timeframes 300 900 3600 --transitions 86400 259200 \
  --train-end TRAIN_TIMESTAMP --validation-end VALIDATION_TIMESTAMP \
  --commission 0.003 --slippage 0.01 --output run-001.json
```

The numbers above are **example experiment inputs**, not recommended or validated
parameters. Set costs to the venue and size under test. All timestamps are Unix
seconds UTC. `--strategy` selects either existing trend implementation. The output
file is created exclusively; an old experiment cannot be accidentally overwritten.
Reports contain dataset hash, source-strategy hash, full candidate grid, costs,
split boundaries, metrics, missing coverage, chosen policy and report checksum.
Code changes invalidate approvals. CPU limits: 32 policies, 2,000 independent
projects, 30,000 candles/project, 250,000 candles/run. Indicators reused across
candidates in a run; no unbounded combinatorial or random search.

For patterns add `--incidents incidents.json --pattern-rules rules.json` and
separate `--pattern-train-end` / `--pattern-validation-end` boundaries. A rules
file is a list such as `[{"feature":"liq","threshold":10000,"direction":"le"}]`.
That threshold is an example hypothesis only. Labels must be known before every
strategy observation; overlapping periods are refused. The report cannot install
a pattern itself.

## Historical contract and collection

Each case has `chain`, `token`, `feed: "engine_5m_mixed_v1"`, `born`, `start`, `end`,
`gem_eligible`, `eligibility_at`, `features`, and `bars`. Candle rows are
`[open_timestamp, open, high, low, close, volume]`, sorted, unique, finite and
aligned to 300 seconds. Eligibility must have been recorded by start. Token birth
is evidence about token/pool age, not alert time. Missing birth is unavailable.
An optional `untradeable_at` is a known failure event; do not derive it from future
prices. It pessimistically wipes any position still held at that event.

The collector runs from `alert_track._refresh_system`, independent of approval.
It freezes first observed eligibility and features, then collects explicit 1/7/30-day research windows. These are observation horizons, NOT trading-timeframe defaults. Only complete windows are exported by the CLI; partial windows cannot validate a policy. Closed candles are stored separately with first-observed versions retained, surviving rolling buffers and restarts. An exported dataset is reproducible via its content hash.

Do not backfill yesterday's gem eligibility from today's ranking. Legacy records
without contemporaneous proof cannot become valid training cases. First imports
will often be insufficient. Unknown/gapped/dead-token histories stay visible as
unavailable; *any unavailable cases in a cohort block approval*, so excluding
dead tokens does not silently improve the reported usable cohort.

The existing feed combines sampled prices with vendor candles. It is not a full
tick/execution feed; this identity is recorded and enforced in approvals. Real
fills, gas, liquidity impact, transfer taxes and sellability need a venue-specific
execution/paper audit. The replay models proportional commission/slippage only,
not a portfolio, gas model, confidence interval, or a guarantee against rugs.
Label availability and source quality require review. Correlated deployers across
different tokens are not yet grouped: project-level isolation alone is weaker.

## Apply and review

The integration is already coded in PR #408. Start with [CLAUDE_QUANT_HANDOFF.md](CLAUDE_QUANT_HANDOFF.md). No production policy was activated.

Export a completed horizon using `python -m app.trading.onchain.quant_memory cases cases.json --horizon-days 7` (1, 7 or 30). Research automatically stores its immutable report in SQLite for the Agent UI, as well as the exclusive JSON output file.

A reviewed manifest on the persistent volume uses:
`{"approved":true,"reviewer":"actual reviewer","mode":"paper","active_from":TIMESTAMP,"report":REPORT_OBJECT}`.
Paper mode cannot authorize real entries. Real mode additionally requires an actual `paper_run_id`. Research does not install this file. Operator approval is not a cryptographic signature. Removing or replacing approval blocks new entries under the old report while its pinned exit stream continues. Code/strategy mismatches fail closed.

Live replay uses durable history rather than the 30,000-bar rolling buffer. It caches evaluation within an unchanged closed candle. CPU and disk usage still grow with history: benchmark and add checkpointed incremental state before large-scale, long-lived operation. Research budgets remain unchanged.

## Integration details

Authenticated read-only routes: `GET /api/agent/quant`, `/project?chain=...&token=...`, `/reports/{sha256}`. Queries never trigger a backtest, model call or order. The Agent tab distinguishes outcome projects from immutable versions, partial from completed windows, and research from approval. Report absence and interrupted updates are shown explicitly. Project selection shows the most recent 100 observations.

The map from #402 displays recorded activity and schematic architecture links. It does NOT yet provide a complete receipt-backed score explanation, counterfactual or causal decision graph. Unconnected nodes remain explicitly marked.

Autotrader consumes each policy/project signal once using persistent high-water marks, permits a later trend entry, and serializes overlapping ticks. Real attempts are persisted before awaiting an order; uncertain attempts require manual reconciliation rather than automatic resubmission. Existing legacy positions retain legacy exits. Approval can authorize paper-only evaluation before real review. Entry quotes and signals must be fresh.

## Verification at handoff

- Final focused Python suite: **47 passed** (quant engine, integration, observatory/API, autotrader and simulated wallet).
- Map Node suite: **8 passed**.
- Ruff over the complete backend: **passed**, E/F/W excluding E501.
- Full backend attempt before the final small quote/pruning changes: **1438 passed, 23 failed, 1 skipped**. 21 failures are network-dependent chain/quote tests in the restricted environment; two are existing Windows timestamp and rules-text expectations. This is NOT a green full suite; rerun in Linux CI/staging.
- Browser verified map rendering, quantitative panel and project selection with clearly labelled local test fixtures, not production data.
- New GitHub workflow runs focused tests, map tests and backend lint without DeepSeek credentials.

No live research dataset was evaluated, no winner or profitability established, and no wallet transaction, merge or deployment performed.
