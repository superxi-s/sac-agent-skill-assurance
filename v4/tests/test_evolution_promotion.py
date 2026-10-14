from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_governance.evolution.promotion import SkillPromotionAdapter
from agent_governance.evolution.evaluator import not_run, report_hash
from agent_governance.evolution.lineage import atomic_json
from agent_governance.models import ActionRequest, Principal
from agent_governance.policy import Policy
from agent_governance.runtime import GovernanceRuntime
from test_evolution import candidate, complete


@pytest.fixture
def setup(candidate, tmp_path):
    _, directory, result = candidate
    report = complete(result)
    adapter = SkillPromotionAdapter(tmp_path / "private_registry", owner_id="demo-reviewer",
        tenant_id="demo-tenant", candidates={result.candidate_id: (result, directory)},
        evaluator=lambda row: report)
    adapter.bootstrap(candidate[0])
    runtime = GovernanceRuntime(adapter, Policy(version="evolution-dev",
        allowed_actions=("promote_skill_candidate", "rollback_skill_version")))
    request = ActionRequest(principal=Principal(user_id="demo-reviewer", tenant_id="demo-tenant",
        session_id="demo-session"), action="promote_skill_candidate", resource_type="skill_candidate",
        resource_id=result.candidate_id, trace_id="demo-promotion", payload={
            "candidate_hash": result.candidate_hash, "report_hash": report_hash(report),
            "expected_champion": adapter.state()["champion"]})
    return runtime, adapter, request, candidate


def approve(runtime, request):
    return runtime.approve(request, review_acknowledged=True).approval_id


def test_requires_explicit_review(setup):
    runtime, adapter, request, _ = setup
    assert runtime.evaluate(request).decision == "REVIEW"
    with pytest.raises(ValueError, match="REVIEW_ACK_REQUIRED"):
        runtime.approve(request)


def test_no_approval_cannot_execute(setup):
    runtime, adapter, request, _ = setup
    assert not runtime.execute(request, "nonexistent").executed
    assert adapter.state()["revision"] == 0


def test_promote_receipt_and_lineage(setup):
    runtime, adapter, request, original = setup
    result = runtime.execute(request, approve(runtime, request))
    assert result.executed and result.backend_receipt
    state = adapter.state()
    assert state["revision"] == 1 and len(state["lineage"]) == 1
    assert state["lineage"][0]["candidate_hash"] == original[2].candidate_hash
    assert state["lineage"][0]["decision"] == "PROMOTED"
    assert state["versions"][state["champion"]]["version"] == "0.1.1"
    assert state["previous"] == original[2].parent_hash


def test_replay_blocked(setup):
    runtime, adapter, request, _ = setup
    approval = approve(runtime, request)
    assert runtime.execute(request, approval).executed
    assert not runtime.execute(request, approval).executed
    assert adapter.state()["revision"] == 1


def test_candidate_drift_after_approval(setup):
    runtime, adapter, request, original = setup
    approval = approve(runtime, request)
    (original[1] / "prompt.md").write_text("候选已改变", encoding="utf-8")
    assert not runtime.execute(request, approval).executed
    assert adapter.state()["revision"] == 0


def test_report_drift_after_approval(setup):
    runtime, adapter, request, original = setup
    approval = approve(runtime, request)
    adapter.evaluator = lambda row: complete(row, reason="报告发生变化")
    assert not runtime.execute(request, approval).executed
    assert adapter.state()["revision"] == 0


def test_champion_drift_after_approval(setup):
    runtime, adapter, request, _ = setup
    approval = approve(runtime, request)
    state = adapter.state()
    state["revision"] += 1
    atomic_json(adapter.registry_path, state)
    assert not runtime.execute(request, approval).executed


def test_concurrent_promotion_single_winner(setup):
    runtime, adapter, request, _ = setup
    approvals = [approve(runtime, request) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda approval: runtime.execute(request, approval), approvals))
    assert sum(row.executed for row in results) == 1
    assert adapter.state()["revision"] == 1
    assert len(adapter.state()["receipts"]) == 1


def rollback_request(adapter, request):
    state = adapter.state()
    return ActionRequest(principal=request.principal, action="rollback_skill_version",
        resource_type="skill_candidate", resource_id=state["previous"], trace_id="demo-rollback",
        payload={"target_hash": state["previous"], "expected_champion": state["champion"]})


def test_governed_rollback_last_known_good(setup):
    runtime, adapter, request, original = setup
    assert runtime.execute(request, approve(runtime, request)).executed
    rollback = rollback_request(adapter, request)
    with pytest.raises(ValueError, match="REVIEW_ACK_REQUIRED"):
        runtime.approve(rollback)
    result = runtime.execute(rollback, approve(runtime, rollback))
    assert result.executed and result.backend_receipt
    state = adapter.state()
    assert state["champion"] == original[2].parent_hash and state["revision"] == 2
    assert state["lineage"][-1]["decision"] == "ROLLED_BACK"
    assert not runtime.execute(rollback, "nonexistent").executed


def test_stale_rollback_blocked(setup):
    runtime, adapter, request, _ = setup
    assert runtime.execute(request, approve(runtime, request)).executed
    rollback = rollback_request(adapter, request)
    approval = approve(runtime, rollback)
    state = adapter.state()
    state["revision"] += 1
    atomic_json(adapter.registry_path, state)
    assert not runtime.execute(rollback, approval).executed


def test_not_run_blocks_approval(setup):
    runtime, adapter, request, _ = setup
    adapter.evaluator = lambda row: not_run(row, {}, "真实评测未执行")
    assert runtime.evaluate(request).decision == "BLOCK"
    assert adapter.state()["revision"] == 0


def test_wrong_owner_blocked(setup):
    runtime, adapter, request, _ = setup
    forged = request.model_copy(update={"principal": Principal(user_id="other", tenant_id="demo-tenant",
                                                             session_id="demo")})
    assert runtime.evaluate(forged).decision == "BLOCK"


def test_registry_reopen(setup):
    runtime, adapter, request, _ = setup
    assert runtime.execute(request, approve(runtime, request)).executed
    reopened = SkillPromotionAdapter(adapter.root, owner_id=adapter.owner_id, tenant_id=adapter.tenant_id,
                                     candidates=adapter.candidates, evaluator=adapter.evaluator)
    assert reopened.state() == adapter.state()


def test_failure_before_atomic_replace_keeps_champion(setup, monkeypatch):
    runtime, adapter, request, _ = setup
    approval = approve(runtime, request)
    before = adapter.registry_path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("合成故障：提交点前中断")
    monkeypatch.setattr("agent_governance.evolution.lineage.os.replace", fail)
    assert not runtime.execute(request, approval).executed
    assert adapter.registry_path.read_bytes() == before
    assert adapter.state()["revision"] == 0
