from pathlib import Path
from typing import Protocol, runtime_checkable
from .models import EvolutionEvaluationReport, SkillCandidate, SkillSnapshot, DistilledExperience, MutationScope, BoundPatchProposal
from .review_quality import ReviewQualityReport
from ..models import ActionRequest, AuthoritySnapshot


class EvaluationSource(Protocol):
    """由维护者绑定的可信评测端，不能取信候选提交的成绩。"""
    def __call__(self, candidate: SkillCandidate) -> EvolutionEvaluationReport: ...


@runtime_checkable
class EvolutionTarget(Protocol):
    def __call__(self, root: Path) -> SkillSnapshot: ...


@runtime_checkable
class ObservationSource(Protocol):
    def __call__(self) -> tuple[ReviewQualityReport, ...]: ...


@runtime_checkable
class ExperienceDistiller(Protocol):
    def __call__(self, state: dict, symptom: str, expected: str) -> DistilledExperience: ...


@runtime_checkable
class CandidateGenerator(Protocol):
    def __call__(self, provider, champion: SkillSnapshot, experiences: tuple[DistilledExperience, ...],
                 scope: MutationScope, previous_trials: tuple[str, ...] = ()) -> BoundPatchProposal: ...


@runtime_checkable
class EvolutionEvaluator(EvaluationSource, Protocol):
    pass


@runtime_checkable
class PromotionBackend(Protocol):
    def snapshot(self, request: ActionRequest) -> AuthoritySnapshot: ...
    def assess(self, request: ActionRequest, authority: AuthoritySnapshot): ...
    def execute(self, request: ActionRequest, expected: AuthoritySnapshot) -> str: ...
