from datetime import datetime, timezone
from typing import Protocol

from ..sac_policy.v2_runtime import DispatchRiskGateV2Runtime
from ..models import ActionRequest, AuthoritySnapshot, GateDecision


class SACBackendAuthority(Protocol):
    def read_candidate(self, candidate_id: str) -> AuthoritySnapshot: ...
    def activate_compare_and_set(self, request: ActionRequest, expected: AuthoritySnapshot) -> str: ...


class SACDispatchAdapter:
    """SAC 场景适配；执行权始终属于 Backend。"""

    action = "activate_dispatch_plan"
    resource_type = "dispatch_plan"

    def __init__(self, backend: SACBackendAuthority, *, clock=None):
        self.backend = backend
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def snapshot(self, request: ActionRequest) -> AuthoritySnapshot:
        return self.backend.read_candidate(request.resource_id)

    def assess(self, request: ActionRequest, authority: AuthoritySnapshot) -> tuple[GateDecision, tuple[str, ...]]:
        if request.action != self.action or request.payload:
            return "BLOCK", ("SAC_ACTIVATION_HAS_NO_PLAN_MUTATION_PARAMETERS",)
        result = DispatchRiskGateV2Runtime().review(
            replan_result=authority.facts["replan_result"],
            authoritative_active_plan_id=str(authority.facts["active_plan_id"]),
            expected_user_id=request.principal.user_id,
            expected_operating_date=str(authority.facts["operating_date"]),
            reviewed_at=self.clock().isoformat(), trace_id=request.trace_id,
        )
        return result.decision, tuple(f.rule_code for f in result.findings)

    def execute(self, request: ActionRequest, expected: AuthoritySnapshot) -> str:
        # Skill 不自行写数据库或激活计划。
        return self.backend.activate_compare_and_set(request, expected)
