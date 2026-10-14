from pydantic import BaseModel, Field

from .constants import PlanStatusV2

from .points import PlanSummary, SchedulePoint

class DispatchPlanV2(BaseModel):
    schema_version: str = "v2"
    plan_id: str
    user_id: str
    operating_date: str
    data_mode: str
    version: int = Field(ge=1)
    source: str
    status: PlanStatusV2
    root_sac_plan_id: str
    parent_plan_id: str | None = None
    constraint_set_id: str | None = None
    forecast_snapshot_id: str | None = None
    runtime_constraint_snapshot_id: str | None = None
    model_version: str | None = None
    created_at: str | None = None
    valid_until: str | None = None
    validated_at: str | None = None
    activated_at: str | None = None
    summary: PlanSummary
    schedule: list[SchedulePoint]

class PlanComparison(BaseModel):
    root_sac_plan_id: str
    parent_plan_id: str | None = None
    revised_plan_id: str
    target_time: str | None = None
    parent_metrics: dict = Field(default_factory=dict)
    revised_metrics: dict = Field(default_factory=dict)
    delta: dict = Field(default_factory=dict)
