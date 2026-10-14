from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SourceRef = Annotated[str, StringConstraints(pattern=r"^source:[0-9a-f]{64}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvolutionObservation(FrozenModel):
    observation_id: Digest
    source_refs: tuple[SourceRef, ...] = Field(min_length=1)
    split: Literal["train", "dev"]
    outcome: Literal["success", "failure", "human_correction", "near_miss"]
    category: Literal["review", "routing", "parameters", "workflow", "evidence", "infrastructure", "unknown"]
    tags: tuple[Literal["task_failed", "trajectory_failed", "forbidden_operation", "missing_step", "infra_error"], ...] = ()
    high_risk: bool = False


class ExperienceRecord(FrozenModel):
    experience_id: Digest
    observation_id: Digest
    category: str
    outcome: str
    source_refs: tuple[SourceRef, ...]
    split: Literal["train", "dev"]
    high_risk: bool


class ExperienceCluster(FrozenModel):
    cluster_id: Digest
    category: str
    outcome: str
    observation_ids: tuple[Digest, ...]
    source_refs: tuple[SourceRef, ...]
    support_count: int = Field(ge=1)
    admitted: bool
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def unique_support(self):
        if len(set(self.observation_ids)) != self.support_count:
            raise ValueError("support_count 必须等于独立观察数")
        return self


class MutationScope(FrozenModel):
    allowed_files: tuple[str, ...] = ("SKILL.md", "prompt.md", "workflow.yaml")
    allow_references: bool = True
    max_file_bytes: int = Field(default=32768, gt=0)
    max_package_bytes: int = Field(default=262144, gt=0)


class FilePatch(FrozenModel):
    path: str
    content: str


class PatchProposal(FrozenModel):
    patches: tuple[FilePatch, ...] = Field(min_length=1)
    rationale: str


class SkillCandidate(FrozenModel):
    candidate_id: Digest
    parent_hash: Digest
    candidate_hash: Digest
    source_experiences: tuple[Digest, ...] = Field(min_length=1)
    changed_files: tuple[str, ...] = Field(min_length=1)


class SuiteResult(FrozenModel):
    suite: Literal["target", "regression", "heldout"]
    count: int = Field(ge=1)
    baseline_score: float = Field(ge=0, le=1)
    candidate_score: float = Field(ge=0, le=1)
    passed: bool


class EvolutionEvaluationReport(FrozenModel):
    candidate_hash: Digest
    parent_hash: Digest
    configuration_hash: Digest
    status: Literal["COMPLETE", "NOT_RUN"]
    suites: tuple[SuiteResult, ...] = ()
    safety_regressions: int | None = Field(default=None, ge=0)
    block_overrides: int | None = Field(default=None, ge=0)
    false_successes: int | None = Field(default=None, ge=0)
    unauthorized_actions: int | None = Field(default=None, ge=0)
    schema_regressions: int | None = Field(default=None, ge=0)
    no_evidence_regressions: int | None = Field(default=None, ge=0)
    reason: str = ""

    @model_validator(mode="after")
    def completed_is_complete(self):
        fields = ("safety_regressions", "block_overrides", "false_successes",
                  "unauthorized_actions", "schema_regressions", "no_evidence_regressions")
        if self.status == "COMPLETE":
            if len(self.suites) != 3 or {s.suite for s in self.suites} != {"target", "regression", "heldout"}:
                raise ValueError("完整报告需要三个互不重复的评测集合")
            if any(getattr(self, field) is None for field in fields):
                raise ValueError("完整报告不能省略安全事实统计")
        elif self.suites or any(getattr(self, field) is not None for field in fields):
            raise ValueError("未运行不能冒充评分或安全零违规")
        return self


class EvolutionGateResult(FrozenModel):
    decision: Literal["REJECTED", "NEEDS_REVIEW"]
    reasons: tuple[str, ...]
    report_hash: Digest


class SkillLineageRecord(FrozenModel):
    candidate_id: Digest
    parent_hash: Digest
    generation: int = Field(ge=1)
    source_experiences: tuple[Digest, ...]
    candidate_hash: Digest
    report_hash: Digest
    decision: Literal["REJECTED", "NEEDS_REVIEW", "PROMOTED", "ROLLED_BACK"]
    promoted_version: str | None = None
    promoted_hash: Digest | None = None
    rollback_target: Digest | None = None


class DistilledExperience(FrozenModel):
    experience_id: Digest
    target_skill: str
    failure_signature: str
    symptom: str
    expected_behavior: str
    observed_behavior: str
    root_cause: str
    recommended_mutation_scope: tuple[str, ...]
    support_count: int = Field(ge=1)
    source_refs: tuple[SourceRef, ...] = Field(min_length=1)
    actionable: bool
    split: str = "dev"
    affected_constraints: tuple[str, ...] = ()
    missing_dimensions: tuple[str, ...] = ()
    observed_patterns: tuple[str, ...] = ()


class SkillSnapshot(FrozenModel):
    skill_name: str
    version: str
    package_hash: Digest
    skill_content: str
    prompt_content: str
    reference_content: tuple[tuple[str, str], ...] = ()


class BoundFilePatch(FrozenModel):
    path: str
    original_hash: Digest
    before: str
    after: str
    reason: str
    experience_ids: tuple[Digest, ...] = Field(min_length=1)


class BoundPatchProposal(FrozenModel):
    parent_hash: Digest
    patches: tuple[BoundFilePatch, ...] = Field(min_length=1)
    rationale: str
