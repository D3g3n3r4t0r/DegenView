# Deterministic gem/sniper research engine

This is executable code, not a DeepSeek task or prompt. Research, incident
archiving, metrics, selection and signal evaluation make **zero model calls**.
Base: `a58707731077e8d9dcee9827669e178d24f60095`. Separate from Agent-map PR #402.

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
It freezes the first observed gem eligibility and features, then records a
24-hour research window at most twice per hour. This initial collection window
is explicit and **cannot establish the merit of multi-day schedules**. Longer
point-in-time datasets in the same contract are accepted by the engine. Cases
are retained independently from alert-bar eviction; incidents have immutable
versions. An exported dataset is reproducible via its content hash.

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

## Approval and review for Claude

1. Run the full backend suite and inspect changes to both real and paper entry
   paths. Local focused tests do not cover the complete wallet stack.
2. Replay representative old positions and ensure their exits are unchanged.
3. Verify live `projects_db` fields and `launched_at` provenance, prospective
   collection, unknowns, token identity, and database growth on a staging volume.
4. Obtain adequate point-in-time history including failures. Run preregistered
   experiments; do not keep retuning after reading the holdout. A new search needs
   fresh holdout data. Check venue costs and false rejection rates manually.
5. Paper test and independently review the winning report. Install
   `backend/data/quant_approved.json` (persistent volume) with:
   `{"approved":true,"reviewer":"name","paper_run_id":"id","active_from":TIMESTAMP,"report":REPORT_OBJECT}`.
   The CLI never writes this file. Local operator approval is a trust boundary,
   not a cryptographic signature. Do not fabricate review or paper identifiers.
6. Verify fresh trend entries, repeated polls, rejected memes, expiry, missing
   market data, and exits before enabling real trading. Removing approval blocks
   eligibility for unpinned alerts; existing pinned policies continue exits.

The bounded live replay keeps up to 30,000 base candles (~104 days). Once the
original observation window rolls out it becomes unavailable rather than being
silently reset. Longer-lived execution needs a checkpointed incremental strategy
state; this PR does not pretend to provide unbounded lifetime replay. Fixed
strategy implementation hashes pin approvals, while open-position behavior on a
code upgrade must be checked operationally before deployment.

## Checks actually performed

35 tests passed on Python 3.12.14; Ruff E/F/W (excluding E501) and compilation
passed for changed Python files. One existing test importing the full FastAPI
`app.main` snapshot path was deselected locally because this is a selective
checkout; it remains in the repository test file for full CI. No tests were
deleted to hide that limitation.

Focused tests cover true candle close/open timing, partial/gapped candles, costs,
unknown eligibility, catastrophic events, timeframe pinning, deterministic search,
holdout isolation, memory versioning, false rejections, approval integrity, and
the two real strategy functions' prefix invariance. Integration tests execute the
exact selected functions via AST to avoid launching network-backed app singletons.
They are not a full backend/infrastructure test. No production dataset, real
wallet transaction, merge, or deployment was executed during authoring.

Bacheca read 30 September: unresolved DeepSeek reports include `508dc969`
(memory counts), `2c5d06bd` (gems without strategy results), `4f848dd5` (LP-lock
quality), and others. None marked resolved here. New request recorded under
`seed-quant-engine-20260930`; completion awaits review and operational validation.
