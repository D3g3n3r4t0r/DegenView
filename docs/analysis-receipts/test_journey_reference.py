"""Specification tests only: these do not test the application runtime."""
import unittest
from dataclasses import replace
from journey_reference import Artifact, Snapshot, complete, project, synthetic_journey


class JourneyTests(unittest.TestCase):
    def setUp(self):
        self.a = Artifact("a", "solana:AbC", "public_project", "hash-A", 10, 100)
        self.s = Snapshot("s", "solana:AbC", "public_project", 2, 50,
                          "demo-v1", ("identity", "liquidity"),
                          (("identity", "pass"), ("liquidity", "pass")),
                          "hash-A", self.a, True)

    def test_synthetic_journey(self):
        steps = synthetic_journey()
        self.assertEqual([x.eligibility for x in steps],
                         ["unknown", "eligible_for_research", "eligible_for_research",
                          "eligible_for_research", "blocked"])
        self.assertEqual([x.research for x in steps],
                         ["not_scheduled", "queued_budget", "needs_analysis", "reused", "not_scheduled"])
        self.assertEqual(steps[-1].artifact_id, "eng-A")
        self.assertTrue(all(not x.execution_authorized for x in steps))

    def test_missing_gate_is_unknown(self):
        d = project(replace(self.s, gates=(("identity", "pass"),)))
        self.assertEqual(d.eligibility, "unknown")
        self.assertIn("GATE_UNKNOWN:liquidity", d.reasons)

    def test_valid_ai_cannot_override_failed_gate(self):
        d = project(replace(self.s, gates=(("identity", "pass"), ("liquidity", "fail"))))
        self.assertEqual(d.eligibility, "blocked")
        self.assertEqual(d.research, "not_scheduled")

    def test_scope_project_and_input_are_exact(self):
        for field, value, reason in (("scope", "tenant:1", "SCOPE_MISMATCH"),
                                      ("project_key", "solana:abc", "PROJECT_MISMATCH"),
                                      ("request_hash", "hash-B", "INPUT_CHANGED")):
            with self.subTest(field=field):
                d = project(replace(self.s, artifact=replace(self.a, **{field: value})))
                self.assertIsNone(d.artifact_id)
                self.assertIn(reason, d.reasons)

    def test_expiry_boundary_and_future_artifact(self):
        for a, reason in ((replace(self.a, valid_until_ms=50), "EXPIRED"),
                          (replace(self.a, created_at_ms=51), "FUTURE_ARTIFACT")):
            self.assertIn(reason, project(replace(self.s, artifact=a)).reasons)

    def test_revocation_rights_and_dependencies(self):
        for field, value, reason in (("revoked", True, "REVOKED"),
                                      ("rights_current", False, "RIGHTS_INVALID"),
                                      ("dependencies_current", False, "DEPENDENCY_INVALID"),
                                      ("validated", False, "OUTPUT_UNVALIDATED")):
            with self.subTest(field=field):
                self.assertIn(reason, project(replace(self.s, artifact=replace(self.a, **{field: value}))).reasons)

    def test_late_completion_cannot_replace_current(self):
        with self.assertRaisesRegex(ValueError, "STALE_GENERATION"):
            complete(self.s, 1, self.a)
        self.assertEqual(self.s.generation, 2)

    def test_current_generation_still_requires_valid_inputs(self):
        with self.assertRaisesRegex(ValueError, "INPUT_CHANGED"):
            complete(self.s, 2, replace(self.a, request_hash="old"))

    def test_budget_wait_does_not_mean_bad_project(self):
        d = project(replace(self.s, artifact=None, budget_available=False))
        self.assertEqual((d.eligibility, d.research), ("eligible_for_research", "queued_budget"))

    def test_reuse_does_not_require_budget(self):
        self.assertEqual(project(replace(self.s, budget_available=False)).research, "reused")

    def test_bad_gate_contract_rejected(self):
        for gates in ((("identity", "pass"), ("identity", "fail")),
                      (("identity", "probably"),), (("undeclared", "pass"),)):
            with self.assertRaises(ValueError):
                project(replace(self.s, gates=gates))
        with self.assertRaises(ValueError):
            project(replace(self.s, required_gates=()))

    def test_projection_deterministic_and_preserves_input(self):
        before = self.s
        self.assertEqual(project(self.s), project(self.s))
        self.assertEqual(self.s, before)


if __name__ == "__main__":
    unittest.main()
