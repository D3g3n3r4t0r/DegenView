"""Executable specification, NOT a production policy, store or AI adapter.

Inputs are normalized, trusted backend projections. Never accept them from a
browser or model. Storage/auth/leases/provenance must be implemented separately.
"""
from dataclasses import dataclass, replace
from typing import Literal


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    project_key: str
    scope: str
    request_hash: str
    created_at_ms: int
    valid_until_ms: int
    validated: bool = True
    dependencies_current: bool = True
    rights_current: bool = True
    revoked: bool = False


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    project_key: str
    scope: str
    generation: int
    cutoff_ms: int
    policy_id: str
    required_gates: tuple[str, ...]
    gates: tuple[tuple[str, str], ...]
    request_hash: str
    artifact: Artifact | None = None
    budget_available: bool = False


@dataclass(frozen=True)
class Dossier:
    snapshot_id: str
    project_key: str
    generation: int
    policy_id: str
    eligibility: Literal["blocked", "unknown", "eligible_for_research"]
    research: Literal["not_scheduled", "reused", "needs_analysis", "queued_budget"]
    reasons: tuple[str, ...]
    next_checks: tuple[str, ...]
    artifact_id: str | None
    # Eligibility for research never authorizes an order.
    execution_authorized: bool = False


def reuse_reasons(s: Snapshot) -> tuple[str, ...]:
    """Return every reason that prevents reuse, in a stable order."""
    a = s.artifact
    if a is None:
        return ("NO_ARTIFACT",)
    failures = (
        (a.project_key != s.project_key, "PROJECT_MISMATCH"),
        (a.scope != s.scope, "SCOPE_MISMATCH"),
        (a.request_hash != s.request_hash, "INPUT_CHANGED"),
        (not a.validated, "OUTPUT_UNVALIDATED"),
        (a.revoked, "REVOKED"),
        (not a.dependencies_current, "DEPENDENCY_INVALID"),
        (not a.rights_current, "RIGHTS_INVALID"),
        (a.created_at_ms > s.cutoff_ms, "FUTURE_ARTIFACT"),
        (a.valid_until_ms <= s.cutoff_ms, "EXPIRED"),
    )
    return tuple(reason for failed, reason in failures if failed)


def project(s: Snapshot) -> Dossier:
    """Pure deterministic projection: no model, network, clock or DB calls.

    Demonstration policy: mandatory gates first, optional engineering research
    second. Does not calculate the application's final score or rank a token.
    """
    if not all((s.snapshot_id, s.project_key, s.scope, s.policy_id, s.request_hash)):
        raise ValueError("missing identity/version")
    if s.generation < 0 or s.cutoff_ms < 0:
        raise ValueError("invalid generation/time")
    if not s.required_gates or len(set(s.required_gates)) != len(s.required_gates):
        raise ValueError("required gates must be nonempty and unique")
    gates = dict(s.gates)
    if len(gates) != len(s.gates) or set(gates) - set(s.required_gates):
        raise ValueError("duplicate or undeclared gate")
    if any(value not in {"pass", "fail", "unknown"} for value in gates.values()):
        raise ValueError("invalid gate status")
    failed = tuple(sorted(k for k in s.required_gates if gates.get(k) == "fail"))
    unknown = tuple(sorted(k for k in s.required_gates if gates.get(k, "unknown") == "unknown"))
    blockers = tuple("GATE_FAILED:" + k for k in failed)
    missing = tuple("GATE_UNKNOWN:" + k for k in unknown)
    invalid = reuse_reasons(s)
    if failed or unknown:
        eligibility = "blocked" if failed else "unknown"
        research = "not_scheduled"
        reasons = blockers + missing
        checks = tuple("RECHECK:" + k for k in failed + unknown)
    else:
        eligibility = "eligible_for_research"
        research = "reused" if not invalid else (
            "needs_analysis" if s.budget_available else "queued_budget"
        )
        reasons = ("INPUT_UNCHANGED",) if not invalid else invalid
        checks = () if not invalid else (
            ("VALIDATED_ANALYSIS",) if s.budget_available else ("BUDGET_AVAILABLE",)
        )
    return Dossier(
        s.snapshot_id, s.project_key, s.generation, s.policy_id,
        eligibility, research, reasons, checks,
        s.artifact.artifact_id if not invalid else None,
    )


def complete(s: Snapshot, job_generation: int, artifact: Artifact) -> Snapshot:
    """Model the publication guard; production needs an atomic DB CAS.

    Rejected artifacts may still be saved as historical by the caller.
    The reference does not persist either accepted or rejected artifacts.
    """
    if job_generation != s.generation:
        raise ValueError("STALE_GENERATION")
    candidate = replace(s, artifact=artifact)
    invalid = reuse_reasons(candidate)
    if invalid:
        raise ValueError(",".join(invalid))
    return candidate


def synthetic_journey() -> tuple[Dossier, ...]:
    """ALFA is fictitious; times and policy are test values, not live data."""
    s = Snapshot("s1", "solana:SYNTHETIC", "public_project", 1, 100,
                 "demo-only-v1", ("identity", "liquidity"),
                 (("identity", "pass"),), "synthetic-request-A")
    discovered = project(s)
    s = replace(s, snapshot_id="s2", gates=(("identity", "pass"), ("liquidity", "pass")))
    waiting = project(s)
    s = replace(s, snapshot_id="s3", budget_available=True)
    scheduled = project(s)
    a = Artifact("eng-A", s.project_key, s.scope, s.request_hash, 90, 200)
    s = complete(s, 1, a)
    analyzed = project(replace(s, snapshot_id="s4"))
    s = replace(s, snapshot_id="s5", generation=2, cutoff_ms=110,
                gates=(("identity", "pass"), ("liquidity", "fail")))
    suspended = project(s)
    # Independent engineering evidence is preserved, never a safety override.
    return discovered, waiting, scheduled, analyzed, suspended


if __name__ == "__main__":
    import json
    from dataclasses import asdict
    print(json.dumps({"synthetic": True, "runtime_trace": False,
                      "steps": [asdict(x) for x in synthetic_journey()]},
                     indent=2, ensure_ascii=False))
