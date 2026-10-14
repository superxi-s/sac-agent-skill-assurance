"""强类型用户约束；归一化及可行性判断属于 Backend。"""
from typing import Literal
from pydantic import BaseModel, Field


class UserConstraint(BaseModel):
    constraint_type: Literal["target_soc_min", "reserve_soc_min", "no_discharge_window", "max_discharge_power"]
    hardness: Literal["hard", "soft"] = "hard"
    target_soc_min: float | None = Field(default=None, ge=0, le=1)
    target_time: str | None = None
    reserve_soc_min: float | None = Field(default=None, ge=0, le=1)
    effective_from: str | None = None
    effective_to: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    max_discharge_power_kw: float | None = Field(default=None, gt=0)


class UserConstraintSet(BaseModel):
    constraint_set_id: str
    user_id: str
    operating_date: str
    source: Literal["agent", "user", "system"] = "agent"
    constraints: list[UserConstraint] = Field(default_factory=list)
    created_at: str | None = None
    expires_at: str | None = None
