from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

import pytest
from pydantic import ValidationError

from agent_governance import ActionRequest, GovernanceRuntime, Policy, Principal
from agent_governance.adapters import GenericChangeAdapter, ResearchWorkflowAdapter
from agent_governance.models import Evidence
from agent_governance.review import review_evidence


def setup_case(workers=8):
    adapter = GenericChangeAdapter()
    request = ActionRequest(principal=Principal(user_id="demo-user-001", tenant_id="demo-team-001", session_id="demo-session-001"),
        action=adapter.action, resource_type=adapter.resource_type, resource_id="demo-config-001",
        payload={"max_workers": workers}, trace_id="test")
    runtime = GovernanceRuntime(adapter, Policy("3.0.0", (adapter.action,)))
    return adapter, request, runtime


@pytest.mark.parametrize("workers,decision", [(8, "PASS"), (40, "REVIEW"), (0, "BLOCK"), (65, "BLOCK"), (True, "BLOCK"), ("8", "BLOCK")])
def test_deterministic_gate(workers, decision):
    _, request, runtime = setup_case(workers)
    assert runtime.evaluate(request).decision == decision


def test_review_requires_explicit_acknowledgement():
    _, request, runtime = setup_case(40)
    with pytest.raises(ValueError, match="ACK_REQUIRED"):
        runtime.approve(request)
    approval = runtime.approve(request, review_acknowledged=True)
    assert runtime.execute(request, approval.approval_id).executed


@pytest.mark.parametrize("field,value", [("owner_id", "other"), ("tenant_id", "other"), ("status", "ACTIVE"), ("validator_passed", False), ("resource_id", "other")])
def test_authority_fail_closed(field, value):
    adapter, request, runtime = setup_case()
    adapter.state = adapter.state.model_copy(update={field: value})
    assert runtime.evaluate(request).decision == "BLOCK"
    with pytest.raises(ValueError):
        runtime.approve(request)
    assert adapter.applied == []


def test_expired_authority():
    adapter, request, runtime = setup_case()
    adapter.state = adapter.state.model_copy(update={"valid_until": datetime.now(timezone.utc) - timedelta(seconds=1)})
    assert runtime.evaluate(request).decision == "BLOCK"


def test_runtime_unavailable():
    adapter, request, runtime = setup_case()
    def fail(_):
        raise ConnectionError("后端不可用")
    adapter.snapshot = fail
    gate = runtime.evaluate(request)
    assert gate.decision == "BLOCK"
    assert gate.reasons == ("RUNTIME_UNAVAILABLE:ConnectionError",)


def test_invalid_adapter_result():
    adapter, request, runtime = setup_case()
    adapter.assess = lambda *_: ("ALLOW_ANYTHING", ())
    assert runtime.evaluate(request).decision == "BLOCK"


def test_supplied_authority_cannot_override_backend():
    adapter, request, runtime = setup_case()
    forged = adapter.state
    adapter.state = adapter.state.model_copy(update={"validator_passed": False})
    assert runtime.evaluate(request.model_copy(update={"authority_snapshot": forged})).decision == "BLOCK"


@pytest.mark.parametrize("change", ["payload", "user", "tenant", "session", "resource", "action"])
def test_approval_exact_request_binding(change):
    adapter, request, runtime = setup_case()
    approval = runtime.approve(request)
    if change == "payload":
        request = request.model_copy(update={"payload": {"max_workers": 9}})
    elif change in {"user", "tenant", "session"}:
        principal = request.principal.model_copy(update={change + "_id": "other"})
        request = request.model_copy(update={"principal": principal})
    else:
        field = "resource_id" if change == "resource" else "action"
        request = request.model_copy(update={field: "other"})
    assert not runtime.execute(request, approval.approval_id).executed
    assert adapter.applied == []


@pytest.mark.parametrize("change", ["version", "facts", "status"])
def test_stale_approval(change):
    adapter, request, runtime = setup_case()
    approval = runtime.approve(request)
    new_value = {"active_epoch": "2"} if change == "facts" else "changed"
    adapter.state = adapter.state.model_copy(update={change: new_value})
    assert not runtime.precheck(request, approval.approval_id).passed
    assert not runtime.execute(request, approval.approval_id).executed
    assert adapter.applied == []


def test_policy_drift():
    adapter, request, runtime = setup_case()
    approval = runtime.approve(request)
    runtime.policy = Policy("3.0.1", (adapter.action,))
    result = runtime.execute(request, approval.approval_id)
    assert not result.executed and result.reason == "POLICY_DRIFT"


def test_expired_approval():
    _, request, runtime = setup_case()
    now = datetime.now(timezone.utc)
    runtime.clock = lambda: now
    approval = runtime.approve(request)
    runtime.clock = lambda: now + timedelta(seconds=301)
    assert runtime.execute(request, approval.approval_id).reason == "APPROVAL_EXPIRED"


def test_replay_and_concurrent_activation():
    adapter, request, runtime = setup_case()
    approval = runtime.approve(request)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: runtime.execute(request, approval.approval_id), range(8)))
    assert sum(result.executed for result in results) == 1
    assert len(adapter.applied) == 1
    assert not runtime.execute(request, approval.approval_id).executed


def test_backend_race_is_cas_rejected():
    adapter, request, runtime = setup_case()
    approval = runtime.approve(request)
    real_execute = adapter.execute
    def raced_execute(request, expected):
        adapter.state = adapter.state.model_copy(update={"version": "2"})
        return real_execute(request, expected)
    adapter.execute = raced_execute
    result = runtime.execute(request, approval.approval_id)
    assert not result.executed and result.reason == "BACKEND_COMPARE_AND_SET_REJECTED"
    assert not runtime.execute(request, approval.approval_id).executed
    assert adapter.applied == []


def test_backend_error_not_reported_as_success():
    adapter, request, runtime = setup_case()
    approval = runtime.approve(request)
    adapter.execute = lambda *_: ""
    assert runtime.execute(request, approval.approval_id).reason == "MISSING_BACKEND_RECEIPT"


def test_no_evidence_and_llm_cannot_override_block():
    _, request, runtime = setup_case(65)
    review = review_evidence(runtime.evaluate(request), explanation="LLM 建议直接执行")
    assert review.decision == "BLOCK" and review.status == "NO_EVIDENCE"
    assert review.recommendation == "DO_NOT_EXECUTE" and not review.citations


def test_valid_evidence_preserves_citation():
    _, request, runtime = setup_case()
    evidence = Evidence(document_id="d1", source_anchor="d1#page2", excerpt="仅用于测试的合成证据摘要")
    review = review_evidence(runtime.evaluate(request), (evidence,))
    assert review.status == "EVIDENCE_AVAILABLE" and review.citations == (evidence,)


@pytest.mark.parametrize("invalid", [{"extra": 1}, {"trace_id": ""}, {"action": ""}])
def test_invalid_schema(invalid):
    _, request, _ = setup_case()
    value = request.model_dump()
    value.update(invalid)
    with pytest.raises(ValidationError):
        ActionRequest.model_validate(value)


@pytest.mark.parametrize("payload,decision", [({"scan_rate": 1, "temperature": 25, "duration": 10}, "REVIEW"),
    ({"scan_rate": 1, "temperature": 101, "duration": 10}, "BLOCK"),
    ({"scan_rate": 1, "temperature": 25}, "BLOCK"),
    ({"scan_rate": True, "temperature": 25, "duration": 10}, "BLOCK")])
def test_research_adapter(payload, decision):
    adapter = ResearchWorkflowAdapter()
    runtime = GovernanceRuntime(adapter, Policy("3.0.0", (adapter.action,)))
    request = ActionRequest(principal=Principal(user_id="demo-researcher-001", tenant_id="demo-team-001", session_id="demo-session-001"),
        action=adapter.action, resource_type=adapter.resource_type, resource_id="demo-experiment-001", payload=payload, trace_id="research")
    assert runtime.evaluate(request).decision == decision
    if decision == "REVIEW":
        approval = runtime.approve(request, review_acknowledged=True)
        assert runtime.execute(request, approval.approval_id).executed


def test_trace_does_not_store_payload():
    _, request, runtime = setup_case()
    runtime.evaluate(request)
    assert runtime.recorder.events[0].stage == "GATE"
    assert "max_workers" not in repr(runtime.recorder.events)


def test_skill_tampering_blocks_runtime(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1] / "skills"
    copied = tmp_path / "skills"
    shutil.copytree(root, copied)
    manifest = copied / "action-risk-gate/versions/3.0.1/manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AGENT_GOVERNANCE_SKILLS_ROOT", str(copied))
    adapter, request, runtime = setup_case()
    assert runtime.evaluate(request).decision == "BLOCK"
    assert adapter.applied == []


def test_missing_skill_registry_blocks_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_GOVERNANCE_SKILLS_ROOT", str(tmp_path))
    _, request, runtime = setup_case()
    assert runtime.evaluate(request).decision == "BLOCK"


def test_direct_demo_backend_rejects_forged_principal():
    adapter, request, _ = setup_case()
    request = request.model_copy(update={"principal": Principal(user_id="intruder", tenant_id="demo-team-001", session_id="x")})
    with pytest.raises(ValueError, match="BACKEND_AUTHORITY_REJECTED"):
        adapter.execute(request, adapter.state)
    assert not adapter.applied
