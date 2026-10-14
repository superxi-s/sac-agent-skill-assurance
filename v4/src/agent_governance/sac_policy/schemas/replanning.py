from typing import Literal

from pydantic import BaseModel, Field

from .constants import PolicyCode

from .constraints import UserConstraintSet

from .plans import DispatchPlanV2, PlanComparison

class PolicyResult(BaseModel):
    allowed: bool
    status: PolicyCode
    reason_code: str | None = None
    retry_after_seconds: int = Field(default=0, ge=0)
    daily_replan_remaining: int | None = None
    daily_activation_remaining: int | None = None

class ValidationResult(BaseModel):
    feasible: bool
    status: Literal["PASS", "FAIL"]
    reason_codes: list[str] = Field(default_factory=list)
    violations: list[dict] = Field(default_factory=list)
    target_soc: float | None = Field(default=None, ge=0, le=1)
    estimated_target_soc: float | None = Field(default=None, ge=0, le=1)
    max_reachable_soc: float | None = Field(default=None, ge=0, le=1)
    recommended_target_soc: float | None = Field(default=None, ge=0, le=1)
    recommended_target_time: str | None = None

class ReplanResult(BaseModel):
    request_id: str
    policy_result: PolicyResult
    current_active_plan_id: str | None = None
    candidate_plan: DispatchPlanV2 | None = None
    validation_result: ValidationResult | None = None
    comparison: PlanComparison | None = None
    effective_constraint_set: UserConstraintSet | None = None
    forecast_snapshot_id: str | None = None
    runtime_constraint_snapshot_id: str | None = None
    error: dict | None = None
