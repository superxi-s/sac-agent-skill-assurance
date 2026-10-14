from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

GateDecision = Literal["PASS", "REVIEW", "BLOCK"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Principal(StrictModel):
    user_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class AuthoritySnapshot(StrictModel):
    resource_type: str
    resource_id: str
    owner_id: str
    tenant_id: str
    version: str
    status: str
    validator_passed: bool
    valid_until: datetime
    facts: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("valid_until")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("权威快照的有效期必须包含时区")
        return value


class ActionRequest(StrictModel):
    principal: Principal
    action: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    authority_snapshot: AuthoritySnapshot | None = None
    context: dict[str, JsonValue] = Field(default_factory=dict)
    trace_id: str = Field(min_length=1)


class GateResult(StrictModel):
    decision: GateDecision
    reasons: tuple[str, ...] = ()
    authority: AuthoritySnapshot | None = None
    policy_hash: str
    trace_id: str


class ApprovalBinding(StrictModel):
    approval_id: str
    request_hash: str
    authority_hash: str
    authority_version: str
    policy_hash: str
    expires_at: datetime
    decision: GateDecision


class PreExecutionCheck(StrictModel):
    passed: bool
    reason: str
    trace_id: str


class ExecutionResult(StrictModel):
    executed: bool
    reason: str
    trace_id: str
    backend_receipt: str = ""


class Evidence(StrictModel):
    document_id: str = Field(min_length=1)
    source_anchor: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)


class EvidenceReview(StrictModel):
    decision: GateDecision
    status: Literal["EVIDENCE_AVAILABLE", "NO_EVIDENCE"]
    recommendation: str
    citations: tuple[Evidence, ...]
    explanation: str
