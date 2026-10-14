from .models import EvolutionEvaluationReport, SkillCandidate
from ..fingerprint import fingerprint


def not_run(candidate: SkillCandidate, configuration: dict, reason: str) -> EvolutionEvaluationReport:
    return EvolutionEvaluationReport(candidate_hash=candidate.candidate_hash,
        parent_hash=candidate.parent_hash, configuration_hash=fingerprint(configuration),
        status="NOT_RUN", reason=reason)


def report_hash(report: EvolutionEvaluationReport) -> str:
    return fingerprint(report.model_dump(mode="json"))
