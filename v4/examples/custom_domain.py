"""独立合成配额业务：确认、拒绝越权、提交时 CAS。"""

from datetime import datetime, timedelta, timezone
from threading import RLock
from agent_governance import ActionRequest, Principal, Policy, GovernanceRuntime
from agent_governance.models import AuthoritySnapshot
from agent_governance_portfolio import configure_assets


class QuotaAdapter:
    def __init__(self):
        self.lock = RLock()
        self.version = 1
        self.status = "PENDING_APPROVAL"
        self.deadline = datetime.now(timezone.utc) + timedelta(minutes=5)

    def snapshot(self, request):
        return AuthoritySnapshot(
            resource_type="quota",
            resource_id="synthetic-quota",
            owner_id="demo-user",
            tenant_id="demo-tenant",
            version=str(self.version),
            status=self.status,
            validator_passed=True,
            valid_until=self.deadline,
            facts={"quota": 10},
        )

    def assess(self, request, authority):
        if request.action != "update_quota" or request.payload != {"quota": 20}:
            return "BLOCK", ("INVALID_QUOTA",)
        return "REVIEW", ("EXPLICIT_CONFIRMATION",)

    def execute(self, request, expected):
        with self.lock:
            if self.snapshot(request) != expected:
                raise ValueError("CAS_CONFLICT")
            self.version += 1
            self.status = "APPLIED"
            return "synthetic-receipt-1"


def main() -> None:
    """合成环境验证越权拒绝、显式确认及重复写拒绝。"""
    configure_assets()
    adapter = QuotaAdapter()
    runtime = GovernanceRuntime(adapter, Policy("demo", ("update_quota",)))
    request = ActionRequest(
        principal=Principal(
            user_id="demo-user", tenant_id="demo-tenant", session_id="demo"
        ),
        action="update_quota",
        resource_type="quota",
        resource_id="synthetic-quota",
        payload={"quota": 20},
        trace_id="demo",
    )
    assert runtime.evaluate(request).decision == "REVIEW"
    wrong = request.model_copy(
        update={
            "principal": Principal(
                user_id="other-demo", tenant_id="demo-tenant", session_id="demo"
            )
        }
    )
    assert runtime.evaluate(wrong).decision == "BLOCK"
    approval = runtime.approve(request, review_acknowledged=True)
    assert runtime.execute(request, approval.approval_id).executed
    assert not runtime.execute(request, approval.approval_id).executed
    print("CUSTOM_DOMAIN_SYNTHETIC=PASS")


if __name__ == "__main__":
    main()
