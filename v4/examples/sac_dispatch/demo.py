"""SAC 风险策略与最小合成候选示例，不连接真实服务。"""

from datetime import datetime, timezone
from threading import RLock

from agent_governance import ActionRequest, GovernanceRuntime, Policy, Principal
from agent_governance.adapters import SACDispatchAdapter
from agent_governance.sac_policy.synthetic import valid_replan
from agent_governance.fingerprint import fingerprint
from agent_governance.models import AuthoritySnapshot


class LocalSACFixtureBackend:
    """本地合成 Backend，保留 CAS 校验，不代表真实 HTTP E2E。"""

    def __init__(self):
        replan = valid_replan()
        self.state = AuthoritySnapshot(
            resource_type="dispatch_plan",
            resource_id="demo-plan-001",
            owner_id="demo-user-001",
            tenant_id="demo-team-001",
            version="2",
            status="PENDING_APPROVAL",
            validator_passed=True,
            valid_until=datetime(2099, 12, 31, tzinfo=timezone.utc),
            facts={
                "active_plan_id": "demo-active-001",
                "operating_date": "2026-09-07",
                "replan_result": replan,
            },
        )
        self.activations = 0
        self.lock = RLock()

    def read_candidate(self, candidate_id):
        if candidate_id != self.state.resource_id:
            raise KeyError(candidate_id)
        return self.state.model_copy(deep=True)

    def activate_compare_and_set(self, request, expected):
        with self.lock:
            if fingerprint(expected) != fingerprint(self.state):
                raise ValueError("SAC_BACKEND_COMPARE_AND_SET_REJECTED")
            decision, _ = Policy(
                "fixture-backend-v1", ("activate_dispatch_plan",)
            ).check(request, self.state, datetime.now(timezone.utc))
            if (
                decision == "BLOCK"
                or SACDispatchAdapter(self).assess(request, self.state)[0] == "BLOCK"
            ):
                raise ValueError("SAC_FIXTURE_BACKEND_AUTHORITY_REJECTED")
            self.activations += 1
            self.state = self.state.model_copy(
                update={"status": "ACTIVE", "version": "3"}
            )
            return "demo-receipt:demo-plan-001"


def main():
    backend = LocalSACFixtureBackend()
    adapter = SACDispatchAdapter(backend)
    runtime = GovernanceRuntime(adapter, Policy("3.0.0", (adapter.action,)))
    request = ActionRequest(
        principal=Principal(
            user_id="demo-user-001", tenant_id="demo-team-001", session_id="demo"
        ),
        action=adapter.action,
        resource_type=adapter.resource_type,
        resource_id="demo-plan-001",
        trace_id="sac-demo",
    )
    print("SAC 确定性策略与合成 Backend 示例；不连接真实 HTTP 服务。")
    print(runtime.evaluate(request).model_dump_json(indent=2, exclude={"authority"}))
    approval = runtime.approve(request, review_acknowledged=True)
    result = runtime.execute(request, approval.approval_id)
    print("执行成功。" if result.executed else "执行已阻断。")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
