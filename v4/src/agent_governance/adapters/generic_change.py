from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from ..fingerprint import fingerprint
from ..models import ActionRequest, AuthoritySnapshot, GateDecision
from ..policy import Policy


class GenericChangeAdapter:
    """本地参考 Backend，不是生产配置服务。"""

    action = "update_configuration"
    resource_type = "configuration"

    def __init__(self, *, owner_id="demo-user-001", tenant_id="demo-team-001", resource_id="demo-config-001"):
        self.state = AuthoritySnapshot(resource_type=self.resource_type, resource_id=resource_id,
            owner_id=owner_id, tenant_id=tenant_id, version="1", status="PENDING_APPROVAL",
            validator_passed=True, valid_until=datetime.now(timezone.utc) + timedelta(hours=1))
        self.applied: list[dict] = []
        self._lock = RLock()

    def snapshot(self, request: ActionRequest) -> AuthoritySnapshot:
        with self._lock:
            return self.state.model_copy(deep=True)

    def assess(self, request: ActionRequest, authority: AuthoritySnapshot) -> tuple[GateDecision, tuple[str, ...]]:
        if request.action != self.action or set(request.payload) != {"max_workers"}:
            return "BLOCK", ("UNSUPPORTED_PARAMETERS",)
        value = request.payload["max_workers"]
        if type(value) is not int or not 1 <= value <= 64:
            return "BLOCK", ("WORKERS_OUT_OF_RANGE",)
        return ("REVIEW", ("HIGH_CAPACITY_CHANGE",)) if value > 32 else ("PASS", ())

    def execute(self, request: ActionRequest, expected: AuthoritySnapshot) -> str:
        with self._lock:
            if fingerprint(self.state) != fingerprint(expected):
                raise ValueError("BACKEND_COMPARE_AND_SET_REJECTED")
            decision, _ = Policy("demo-backend-v1", (self.action,)).check(request, self.state, datetime.now(timezone.utc))
            if decision == "BLOCK":
                raise ValueError("BACKEND_AUTHORITY_REJECTED")
            if self.assess(request, self.state)[0] == "BLOCK":
                raise ValueError("BACKEND_VALIDATION_REJECTED")
            self.applied.append(dict(request.payload))
            self.state = self.state.model_copy(update={"version": str(int(self.state.version) + 1), "status": "APPLIED"})
            return "local-change:" + uuid4().hex
