import math

from ..models import ActionRequest, AuthoritySnapshot, GateDecision
from .generic_change import GenericChangeAdapter


class ResearchWorkflowAdapter(GenericChangeAdapter):
    """仅为适配示例，未接入真实 XRD/SEM 或设备。"""

    action = "update_experiment_parameters"
    resource_type = "experiment_run"

    def __init__(self):
        super().__init__(owner_id="demo-researcher-001", resource_id="demo-experiment-001")

    def assess(self, request: ActionRequest, authority: AuthoritySnapshot) -> tuple[GateDecision, tuple[str, ...]]:
        limits = {"scan_rate": (0.01, 10), "temperature": (0, 100), "duration": (1, 120)}
        if request.action != self.action or set(request.payload) != set(limits):
            return "BLOCK", ("UNSUPPORTED_EXPERIMENT_PARAMETERS",)
        for field, (lower, upper) in limits.items():
            value = request.payload[field]
            if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
                return "BLOCK", ("DEMO_LIMIT_EXCEEDED:" + field,)
        return "REVIEW", ("RESEARCH_DEMO_REQUIRES_REVIEW",)
