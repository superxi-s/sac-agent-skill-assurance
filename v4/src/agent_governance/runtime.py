from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import uuid4

from .approval import InMemoryApprovalStore
from .fingerprint import fingerprint, request_fingerprint
from .models import ActionRequest, ApprovalBinding, AuthoritySnapshot, ExecutionResult, GateDecision, GateResult, PreExecutionCheck
from .policy import Policy
from .registry import verify_v3_registry
from .tracing import TraceRecorder


class DomainAdapter(Protocol):
    def snapshot(self, request: ActionRequest) -> AuthoritySnapshot: ...
    def assess(self, request: ActionRequest, authority: AuthoritySnapshot) -> tuple[GateDecision, tuple[str, ...]]: ...
    def execute(self, request: ActionRequest, expected: AuthoritySnapshot) -> str: ...


class GovernanceRuntime:
    def __init__(self, adapter: DomainAdapter, policy: Policy, *, store=None, clock=None, recorder=None):
        self.adapter = adapter
        self.policy = policy
        self.store = store or InMemoryApprovalStore()
        self.clock: Callable[[], datetime] = clock or (lambda: datetime.now(timezone.utc))
        self.recorder = recorder or TraceRecorder()

    def evaluate(self, request: ActionRequest) -> GateResult:
        authority = None
        skill_hashes = {}
        try:
            skill_hashes = verify_v3_registry()
            authority = self.adapter.snapshot(request).model_copy(deep=True)
            decision, reasons = self.policy.check(request, authority, self.clock())
            if decision != "BLOCK":
                decision, reasons = self.adapter.assess(request, authority)
                if decision not in {"PASS", "REVIEW", "BLOCK"}:
                    raise ValueError("适配器返回了无效决策")
        except Exception as exc:
            decision, reasons = "BLOCK", ("RUNTIME_UNAVAILABLE:" + type(exc).__name__,)
        result = GateResult(decision=decision, reasons=reasons, authority=authority,
                            policy_hash=fingerprint({"policy": self.policy.sha256, "skills": skill_hashes}), trace_id=request.trace_id)
        self.recorder.record(request.trace_id, "GATE", decision)
        return result

    def approve(self, request: ActionRequest, *, review_acknowledged: bool = False) -> ApprovalBinding:
        # 重新判断，不信任调用方自行提供的 GateResult。
        request = request.model_copy(deep=True)
        gate = self.evaluate(request)
        if gate.decision == "BLOCK" or gate.authority is None:
            raise ValueError("BLOCKED_ACTION")
        if gate.decision == "REVIEW" and not review_acknowledged:
            raise ValueError("REVIEW_ACK_REQUIRED")
        binding = ApprovalBinding(approval_id=uuid4().hex, request_hash=request_fingerprint(request),
            authority_hash=fingerprint(gate.authority), authority_version=gate.authority.version,
            policy_hash=gate.policy_hash, decision=gate.decision,
            expires_at=min(gate.authority.valid_until, self.clock() + timedelta(seconds=self.policy.approval_ttl_seconds)))
        self.store.put(binding)
        self.recorder.record(request.trace_id, "APPROVAL", "BOUND")
        return binding

    def _check(self, request: ActionRequest, binding: ApprovalBinding, gate: GateResult) -> None:
        if self.clock() >= binding.expires_at:
            raise ValueError("APPROVAL_EXPIRED")
        if binding.request_hash != request_fingerprint(request):
            raise ValueError("REQUEST_MISMATCH")
        if binding.policy_hash != gate.policy_hash:
            raise ValueError("POLICY_DRIFT")
        if gate.decision == "BLOCK" or gate.authority is None:
            raise ValueError("REVALIDATION_BLOCKED")
        if binding.authority_hash != fingerprint(gate.authority) or binding.authority_version != gate.authority.version:
            raise ValueError("AUTHORITY_DRIFT")
        if gate.decision != binding.decision:
            raise ValueError("DECISION_DRIFT")

    def precheck(self, request: ActionRequest, approval_id: str) -> PreExecutionCheck:
        try:
            self._check(request, self.store.get(approval_id), self.evaluate(request))
            return PreExecutionCheck(passed=True, reason="REVALIDATED", trace_id=request.trace_id)
        except Exception as exc:
            return PreExecutionCheck(passed=False, reason=str(exc), trace_id=request.trace_id)

    def execute(self, request: ActionRequest, approval_id: str) -> ExecutionResult:
        try:
            # 冻结嵌套参数，防止执行前复核期间被调用方修改。
            request = request.model_copy(deep=True)
            binding = self.store.get(approval_id)
            gate = self.evaluate(request)
            self._check(request, binding, gate)
            self.store.consume(approval_id)
            # Adapter 必须基于完整权威快照执行 CAS。
            receipt = self.adapter.execute(request, gate.authority)
            if not receipt:
                raise ValueError("MISSING_BACKEND_RECEIPT")
            result = ExecutionResult(executed=True, reason="EXECUTED", trace_id=request.trace_id, backend_receipt=receipt)
        except Exception as exc:
            result = ExecutionResult(executed=False, reason=str(exc), trace_id=request.trace_id)
        self.recorder.record(request.trace_id, "EXECUTION", result.reason)
        return result
