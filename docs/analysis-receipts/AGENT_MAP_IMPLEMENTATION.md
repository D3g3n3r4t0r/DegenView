# Agent map: implementation handoff to Claude

Base: a9b6b38c55fe1ee9eb00f4e5d2195f5ea15a91dc, 2026-09-30. Draft frontend implementation for review, not a deployment. The current branch already separates some activity/AI counters and has a spending cap; preserve that work.

## What this change actually implements

- Mounts a responsive, keyboard-accessible architecture map inside the existing Scout/Agent tab.
- Reuses the existing authenticated /api/agent and /api/agent/log polling. The map never calls a model or adds a network request.
- Filters the latest loaded activity window by exact chain+token (case preserved), not ticker. Unknown categories stay visible.
- Shows recorded notes, reported outcomes and checks using textContent. No raw model/source HTML is inserted.
- Shows global daily calls/tokens/estimated cost only in the all-project view. Missing usage stays unavailable; project selection never inherits global expenditure.
- Marks unavailable/stale updates; preserves data after failure. Does not reinterpret `working` as an active model job.
- Architecture edges are explicitly schematic, not verified causal links. Nodes with no backend contract are marked Not connected.

## Five requested capabilities: honest status

| Capability | Implemented here | Still required |
|---|---|---|
| Follow a crypto | Exact project filter over loaded events | Receipt-backed causal path through evidence and final decision |
| Why this score? | Node roles and recorded checks | Versioned policy contributions with actual input references |
| What would change the assessment? | Explicit unavailable state and architectural next step | Necessary/sufficient conditions computed by policy; no invented AI counterfactual |
| Why spend here? | Global recorded calls/tokens/estimated USD | Per-attempt purpose, project/decision correlation, alternative reuse and useful outcome |
| What changed? | Timestamped recent activity | Two immutable snapshots and deterministic diff |

Do not present this as the five complete features. The UI must keep those distinctions after integration. No fabricated safety state, source evidence, hypothesis, priority rationale or scheduled task.

## Runtime contracts for the next PRs

Reuse #365/#366 and the shared assurance store; no browser event store or second authority. Add a read-only, authorized project dossier/graph API carrying stable IDs, snapshot_id, receipt_id, policy_version, scope, data_as_of, coverage and cursor. Validate references server-side before exposing them. Associate attempts with logical tasks and decisions; usage unknown != zero. Preserve time cutoff and exact identity. Graph state must not grant execution permission.

The legacy global endpoints already expose activity to authenticated users. This patch does not expand access, but a tenant-specific graph must be scoped on the server, not by this client-side project filter. Do not add private chat or wallet evidence to the global feed. Project filter here is only a presentation filter, never an authorization control.

Current window: latest 60 events returned by parent view (model cap 300). Load earlier remains the existing activity-list operation and does not reconstruct complete project history. Shared timestamps are not deduplicated in the map. No archive/replay claims. Narrative or research events without project identity are excluded from a selected project, not guessed from text. A no-event state does not imply a module never ran.

## Review and integration checklist

1. Run `node --test frontend/tests/agent-map.test.mjs` and browser-module syntax checks (copy JS to .mjs as existing backend/tests/test_frontend_syntax.py does).
2. Review in actual Agent tab at 320px and desktop: node selection, project filter, no data, error/recovery, remount, keyboard and retained selection.
3. Check existing authentication and API response behavior; map adds no endpoint, no AI call, no scoring change.
4. Verify deployment/cache handling for the two new @onchain modules. Existing import-map prefix should resolve them; do not ship a missing asset.
5. Implement structured backend contracts in separate reviewable PRs; add endpoint/authorization/concurrency tests there. Only then replace Not connected and schematic edges with verified values.
6. Review #366 status against latest runtime: prior audit findings may already have partial fixes. This PR does not finish the cost audit.

Backend runtime is unchanged. Full backend suite and production integration must be verified by Claude before merge. Bacheca access from the terminal was blocked by network permissions; no issue has been marked resolved. User requested a code scaffold for Claude to review and implement; no DeepSeek automation, merge or deployment is triggered here.
