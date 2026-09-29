-- Contract prototype only. Not a production migration.
PRAGMA foreign_keys = ON;
CREATE TABLE source_revision (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  purpose TEXT NOT NULL CHECK(purpose IN ('internal','retain_raw','send_to_model','redistribute','train')),
  permission TEXT NOT NULL CHECK(permission IN ('allowed','denied','unknown')),
  checked_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER,
  terms_hash TEXT,
  CHECK(expires_at_ms IS NULL OR expires_at_ms > checked_at_ms)
);
CREATE TABLE snapshot (
  id TEXT PRIMARY KEY,
  project_key TEXT NOT NULL,
  decision_at_ms INTEGER NOT NULL CHECK(decision_at_ms >= 0),
  input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
  input_json TEXT NOT NULL,
  code_sha TEXT NOT NULL
);
CREATE TABLE evidence (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES snapshot(id),
  source_revision_id TEXT NOT NULL REFERENCES source_revision(id),
  source_family_id TEXT NOT NULL,
  received_at_ms INTEGER NOT NULL CHECK(received_at_ms >= 0),
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64)
);
CREATE TRIGGER no_future_evidence BEFORE INSERT ON evidence
WHEN NEW.received_at_ms > (SELECT decision_at_ms FROM snapshot WHERE id=NEW.snapshot_id)
BEGIN SELECT RAISE(ABORT,'FUTURE_EVIDENCE'); END;
CREATE TRIGGER snapshot_no_update BEFORE UPDATE ON snapshot
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_SNAPSHOT'); END;
CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE reference_case (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES snapshot(id),
  target TEXT NOT NULL CHECK(target IN ('market_drawdown_80','liquidity_drop_80','source_unavailable','verified_exploit','project_quality','executable_return')),
  horizon_end_ms INTEGER NOT NULL,
  rubric_version TEXT NOT NULL
);
CREATE TABLE annotation (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES reference_case(id),
  reviewer_id TEXT NOT NULL,
  verdict TEXT NOT NULL CHECK(verdict IN ('positive','negative','unknown','censored','disputed')),
  evidence_json TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  UNIQUE(case_id,reviewer_id)
);
CREATE TRIGGER annotation_no_update BEFORE UPDATE ON annotation
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ANNOTATION'); END;
CREATE TABLE reference_label (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES reference_case(id),
  status TEXT NOT NULL CHECK(status IN ('positive','negative','unknown','censored','disputed')),
  available_at_ms INTEGER NOT NULL,
  coverage_sufficient INTEGER NOT NULL CHECK(coverage_sufficient IN (0,1)),
  adjudicator_id TEXT,
  supersedes TEXT REFERENCES reference_label(id),
  rationale TEXT NOT NULL
);
CREATE TRIGGER mature_negative BEFORE INSERT ON reference_label
WHEN NEW.status='negative' AND (
  NEW.coverage_sufficient=0 OR
  NEW.available_at_ms < (SELECT horizon_end_ms FROM reference_case WHERE id=NEW.case_id))
BEGIN SELECT RAISE(ABORT,'IMMATURE_NEGATIVE'); END;
CREATE TRIGGER independent_adjudicator BEFORE INSERT ON reference_label
WHEN NEW.adjudicator_id IS NOT NULL AND EXISTS(
  SELECT 1 FROM annotation WHERE case_id=NEW.case_id AND reviewer_id=NEW.adjudicator_id)
BEGIN SELECT RAISE(ABORT,'ADJUDICATOR_NOT_INDEPENDENT'); END;
CREATE TRIGGER label_no_update BEFORE UPDATE ON reference_label
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_LABEL'); END;
CREATE TABLE policy (
  id TEXT PRIMARY KEY,
  product_surface TEXT NOT NULL,
  decision_mode TEXT NOT NULL CHECK(decision_mode IN ('research','monitor','execution_support')),
  bundle_hash TEXT NOT NULL CHECK(length(bundle_hash)=64),
  manifest_json TEXT NOT NULL
);
CREATE TABLE evaluation_run (
  id TEXT PRIMARY KEY,
  policy_id TEXT NOT NULL REFERENCES policy(id),
  manifest_hash TEXT NOT NULL CHECK(length(manifest_hash)=64),
  dataset_hash TEXT NOT NULL CHECK(length(dataset_hash)=64),
  status TEXT NOT NULL CHECK(status IN ('passed','failed','inconclusive','invalid')),
  report_json TEXT NOT NULL
);
CREATE TABLE approval (
  id TEXT PRIMARY KEY,
  policy_id TEXT NOT NULL REFERENCES policy(id),
  run_id TEXT NOT NULL REFERENCES evaluation_run(id),
  bundle_hash TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  actor_type TEXT NOT NULL CHECK(actor_type='human'),
  created_at_ms INTEGER NOT NULL
);
CREATE TRIGGER matching_approval BEFORE INSERT ON approval
WHEN NEW.bundle_hash != (SELECT bundle_hash FROM policy WHERE id=NEW.policy_id)
 OR NOT EXISTS(SELECT 1 FROM evaluation_run
   WHERE id=NEW.run_id AND policy_id=NEW.policy_id AND status='passed')
BEGIN SELECT RAISE(ABORT,'INVALID_APPROVAL'); END;
CREATE TABLE active_slot (
  product_surface TEXT NOT NULL,
  decision_mode TEXT NOT NULL,
  policy_id TEXT NOT NULL REFERENCES policy(id),
  approval_id TEXT NOT NULL REFERENCES approval(id),
  PRIMARY KEY(product_surface,decision_mode)
);
CREATE TRIGGER valid_slot_insert BEFORE INSERT ON active_slot
WHEN NOT EXISTS(SELECT 1 FROM policy p JOIN approval a ON a.policy_id=p.id
 WHERE p.id=NEW.policy_id AND a.id=NEW.approval_id
 AND p.product_surface=NEW.product_surface AND p.decision_mode=NEW.decision_mode)
BEGIN SELECT RAISE(ABORT,'SLOT_MISMATCH'); END;
CREATE TRIGGER valid_slot_update BEFORE UPDATE ON active_slot
WHEN NOT EXISTS(SELECT 1 FROM policy p JOIN approval a ON a.policy_id=p.id
 WHERE p.id=NEW.policy_id AND a.id=NEW.approval_id
 AND p.product_surface=NEW.product_surface AND p.decision_mode=NEW.decision_mode)
BEGIN SELECT RAISE(ABORT,'SLOT_MISMATCH'); END;
CREATE TRIGGER policy_no_update BEFORE UPDATE ON policy
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_POLICY'); END;
CREATE TRIGGER approval_no_update BEFORE UPDATE ON approval
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_APPROVAL'); END;
CREATE TRIGGER run_no_update BEFORE UPDATE ON evaluation_run
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RUN'); END;
-- Authorization, label evidence sufficiency, full state transitions, canonical
-- hashes and rights enforcement must be checked in the future service layer.
-- Retention/deletion requires a separate authorized tombstone workflow.
