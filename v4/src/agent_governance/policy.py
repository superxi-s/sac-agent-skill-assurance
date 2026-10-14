from dataclasses import dataclass
from datetime import datetime

from .fingerprint import fingerprint
from .models import ActionRequest, AuthoritySnapshot, GateDecision


@dataclass(frozen=True)
class Policy:
    version: str
    allowed_actions: tuple[str, ...]
    approval_ttl_seconds: int = 300

    def __post_init__(self):
        if not self.version or not self.allowed_actions or self.approval_ttl_seconds <= 0:
            raise ValueError("必须提供策略版本、允许动作及正数有效期")

    @property
    def sha256(self) -> str:
        return fingerprint({"version": self.version, "allowed_actions": self.allowed_actions,
                            "approval_ttl_seconds": self.approval_ttl_seconds})

    def check(self, request: ActionRequest, authority: AuthoritySnapshot, now: datetime) -> tuple[GateDecision, tuple[str, ...]]:
        failures = []
        if request.action not in self.allowed_actions:
            failures.append("ACTION_NOT_ALLOWED")
        if (request.resource_type, request.resource_id) != (authority.resource_type, authority.resource_id):
            failures.append("RESOURCE_MISMATCH")
        if (request.principal.user_id, request.principal.tenant_id) != (authority.owner_id, authority.tenant_id):
            failures.append("IDENTITY_MISMATCH")
        if authority.status != "PENDING_APPROVAL":
            failures.append("INVALID_STATUS")
        if not authority.validator_passed:
            failures.append("VALIDATOR_REJECTED")
        if authority.valid_until <= now:
            failures.append("EXPIRED_AUTHORITY")
        return ("BLOCK", tuple(failures)) if failures else ("PASS", ())
