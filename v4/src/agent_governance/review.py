from .models import Evidence, EvidenceReview, GateResult


def review_evidence(gate: GateResult, evidence: tuple[Evidence, ...] = (), explanation: str = "") -> EvidenceReview:
    recommendation = {"BLOCK": "DO_NOT_EXECUTE", "REVIEW": "REQUIRE_EXPLICIT_REVIEW", "PASS": "REQUEST_HUMAN_APPROVAL"}[gate.decision]
    return EvidenceReview(decision=gate.decision, status="EVIDENCE_AVAILABLE" if evidence else "NO_EVIDENCE",
                          recommendation=recommendation, citations=evidence, explanation=explanation)
