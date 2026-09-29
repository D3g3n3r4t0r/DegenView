"""Executable storage-contract tests; no application imports or network."""
import json
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
H = "a" * 64
J = "b" * 64


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript((ROOT / "contract.sql").read_text(encoding="utf-8"))
        self.db.execute("INSERT INTO source_revision VALUES (?,?,?,?,?,?,?)",
                        ("src1", "fixture", "internal", "unknown", 0, 10000, H))
        self.db.execute("INSERT INTO snapshot VALUES (?,?,?,?,?,?)",
                        ("s1", "solana:SyntheticCaseSensitive", 1000, H, "{}", "fixture-sha"))
        self.db.execute("INSERT INTO reference_case VALUES (?,?,?,?,?)",
                        ("c1", "s1", "verified_exploit", 8000, "rubric-v1"))

    def reject(self, sql, args, message=None):
        with self.assertRaises(sqlite3.IntegrityError) as cm:
            self.db.execute(sql, args)
        if message:
            self.assertIn(message, str(cm.exception))

    def test_future_evidence_is_rejected_but_cutoff_is_inclusive(self):
        insert = "INSERT INTO evidence VALUES (?,?,?,?,?,?)"
        self.reject(insert, ("e1", "s1", "src1", "family1", 1001, H), "FUTURE_EVIDENCE")
        self.db.execute(insert, ("e2", "s1", "src1", "family1", 1000, H))

    def test_evidence_requires_known_snapshot_and_source(self):
        self.reject("INSERT INTO evidence VALUES (?,?,?,?,?,?)",
                    ("e1", "missing", "src1", "family1", 1, H))
        self.reject("INSERT INTO evidence VALUES (?,?,?,?,?,?)",
                    ("e2", "s1", "missing", "family1", 1, H))

    def test_snapshot_cannot_be_rewritten_to_change_the_cutoff(self):
        self.reject("UPDATE snapshot SET decision_at_ms=? WHERE id=?", (2000, "s1"),
                    "IMMUTABLE_SNAPSHOT")

    def test_negative_requires_horizon_and_coverage(self):
        insert = "INSERT INTO reference_label VALUES (?,?,?,?,?,?,?,?)"
        self.reject(insert, ("l1", "c1", "negative", 7999, 1, None, None, "early"),
                    "IMMATURE_NEGATIVE")
        self.reject(insert, ("l2", "c1", "negative", 8000, 0, None, None, "gaps"),
                    "IMMATURE_NEGATIVE")
        self.db.execute(insert, ("l3", "c1", "negative", 8000, 1, None, None, "mature"))

    def test_unknown_does_not_need_a_mature_horizon(self):
        self.db.execute("INSERT INTO reference_label VALUES (?,?,?,?,?,?,?,?)",
                        ("l1", "c1", "unknown", 2000, 0, None, None, "missing data"))
        self.assertEqual(self.db.execute("SELECT status FROM reference_label").fetchone()[0], "unknown")

    def test_reviewer_cannot_submit_two_independent_votes(self):
        insert = "INSERT INTO annotation VALUES (?,?,?,?,?,?)"
        self.db.execute(insert, ("a1", "c1", "r1", "positive", "[]", 2000))
        self.reject(insert, ("a2", "c1", "r1", "negative", "[]", 2001))
        self.reject("UPDATE annotation SET verdict=? WHERE id=?", ("negative", "a1"),
                    "IMMUTABLE_ANNOTATION")

    def test_adjudicator_must_differ_from_reviewer(self):
        self.db.execute("INSERT INTO annotation VALUES (?,?,?,?,?,?)",
                        ("a1", "c1", "r1", "positive", "[]", 2000))
        self.reject("INSERT INTO reference_label VALUES (?,?,?,?,?,?,?,?)",
                    ("l1", "c1", "positive", 2001, 1, "r1", None, "self"),
                    "ADJUDICATOR_NOT_INDEPENDENT")

    def seed_policy(self, pid="p1", status="passed"):
        self.db.execute("INSERT INTO policy VALUES (?,?,?,?,?)", (pid, "gems", "research", H, "{}"))
        self.db.execute("INSERT INTO evaluation_run VALUES (?,?,?,?,?,?)",
                        ("run-" + pid, pid, H, J, status, "{}"))

    def approve(self, pid="p1"):
        self.db.execute("INSERT INTO approval VALUES (?,?,?,?,?,?,?)",
                        ("ok-" + pid, pid, "run-" + pid, H, "reviewer", "human", 9000))

    def test_ai_and_wrong_hash_cannot_approve(self):
        self.seed_policy()
        sql = "INSERT INTO approval VALUES (?,?,?,?,?,?,?)"
        self.reject(sql, ("a1", "p1", "run-p1", H, "agent", "ai", 9000))
        self.reject(sql, ("a2", "p1", "run-p1", J, "reviewer", "human", 9000),
                    "INVALID_APPROVAL")

    def test_inconclusive_run_is_not_promotable(self):
        self.seed_policy(status="inconclusive")
        self.reject("INSERT INTO approval VALUES (?,?,?,?,?,?,?)",
                    ("a1", "p1", "run-p1", H, "reviewer", "human", 9000),
                    "INVALID_APPROVAL")

    def test_slot_rejects_wrong_mode_and_second_active_policy(self):
        self.seed_policy()
        self.approve()
        sql = "INSERT INTO active_slot VALUES (?,?,?,?)"
        self.reject(sql, ("gems", "monitor", "p1", "ok-p1"), "SLOT_MISMATCH")
        self.db.execute(sql, ("gems", "research", "p1", "ok-p1"))
        self.seed_policy("p2")
        self.approve("p2")
        self.reject(sql, ("gems", "research", "p2", "ok-p2"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM active_slot").fetchone()[0], 1)

    def test_bundle_and_approval_cannot_mutate_after_review(self):
        self.seed_policy()
        self.approve()
        self.reject("UPDATE policy SET bundle_hash=? WHERE id=?", (J, "p1"), "IMMUTABLE_POLICY")
        self.reject("UPDATE approval SET actor_type=? WHERE id=?", ("ai", "ok-p1"), "IMMUTABLE_APPROVAL")
        self.reject("UPDATE evaluation_run SET status=? WHERE id=?", ("failed", "run-p1"), "IMMUTABLE_RUN")

    def test_source_unknown_is_explicit_and_bad_permission_rejected(self):
        self.assertEqual(self.db.execute("SELECT permission FROM source_revision").fetchone()[0], "unknown")
        self.reject("INSERT INTO source_revision VALUES (?,?,?,?,?,?,?)",
                    ("src2", "fixture", "redistribute", "probably", 0, None, None))

    def test_acceptance_catalog_is_unique_and_not_marked_done(self):
        catalog = json.loads((ROOT / "ACCEPTANCE.json").read_text(encoding="utf-8"))
        cases = catalog["cases"]
        self.assertEqual(len(cases), 29)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        self.assertEqual({c["id"].split("-")[0] for c in cases},
                         {f"A{i:02}" for i in range(1, 9)})
        self.assertTrue(all(c["status"] == "required_not_implemented" for c in cases))


if __name__ == "__main__":
    unittest.main(verbosity=2)
