from pydantic import BaseModel, Field

from .intervals import Decision, POINTS_PER_DAY

class SchedulePoint(BaseModel):
    """单个 15 分钟点的完整事实。"""

    index: int = Field(ge=0, le=POINTS_PER_DAY - 1)
    time: str  # HH:MM 本地时间
    load_kw: float
    pv_kw: float
    price_eur_kwh: float
    soc_before: float = Field(ge=0.0, le=1.0)
    raw_action: float
    decision: Decision
    power_kw: float
    soc_after: float = Field(ge=0.0, le=1.0)
    baseline_cost_eur: float
    optimized_cost_eur: float
    saving_eur: float
    reason_codes: list[str]

class PlanSummary(BaseModel):
    """当日汇总（与 schedule 逐点事实自洽）。"""

    initial_soc: float = Field(ge=0.0, le=1.0)
    final_soc: float = Field(ge=0.0, le=1.0)
    total_charge_kwh: float = Field(ge=0.0)
    total_discharge_kwh: float = Field(ge=0.0)
    baseline_cost_eur: float
    optimized_cost_eur: float
    saving_eur: float
