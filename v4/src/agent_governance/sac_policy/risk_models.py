"""SAC 确定性计划风险判断的数据模型。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from .schemas.plans import DispatchPlanV2
from .schemas.replanning import ReplanResult


RiskDecision = Literal["PASS", "REVIEW", "BLOCK"]
RiskSeverity = Literal["INFO", "WARNING", "BLOCKER"]


class RiskReviewInput(BaseModel):
    schema_version: Literal["risk-review-input-v1"] = "risk-review-input-v1"
    replan_result: ReplanResult
    authoritative_active_plan_id: str = Field(min_length=1)
    expected_user_id: str = Field(min_length=1)
    expected_operating_date: str = Field(min_length=10, max_length=10)
    reviewed_at: str = Field(min_length=1)


class RiskFinding(BaseModel):
    code: str = Field(min_length=1)
    category: Literal["RUNTIME", "FEASIBILITY", "GOVERNANCE", "ECONOMIC", "OPERATIONAL"]
    severity: RiskSeverity
    message: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class RiskReviewResult(BaseModel):
    schema_version: Literal["risk-review-v1"] = "risk-review-v1"
    review_id: str = Field(min_length=1)
    input_fingerprint: str = Field(min_length=1)
    candidate_fingerprint: str = Field(min_length=1)
    skill_name: str = Field(min_length=1)
    skill_version: str = Field(min_length=1)
    skill_hash: str = Field(min_length=1)
    candidate_plan_id: str = ""
    parent_plan_id: str = ""
    decision: RiskDecision
    requires_second_confirmation: bool
    findings: list[RiskFinding] = Field(default_factory=list)
    reviewed_at: str = Field(min_length=1)


def canonical_fingerprint(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def candidate_fingerprint(candidate: DispatchPlanV2 | dict[str, Any] | Any) -> str:
    if isinstance(candidate, BaseModel):
        payload = candidate.model_dump(mode="json")
    elif isinstance(candidate, dict):
        payload = candidate
    elif hasattr(candidate, "model_dump"):
        payload = candidate.model_dump(mode="json")
    else:
        raise TypeError("候选必须符合 DispatchPlanV2 数据结构")
    return canonical_fingerprint(payload)

