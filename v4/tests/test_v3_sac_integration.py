from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from agent_governance import ActionRequest, GovernanceRuntime, Policy, Principal
from agent_governance.adapters import SACDispatchAdapter
from agent_governance.registry import verify_v3_registry
from agent_governance.sac_policy.v2_runtime import V2SkillRegistry


def make_sac():
    path = Path(__file__).resolve().parents[1] / "examples/sac_dispatch/demo.py"
    spec = spec_from_file_location("sac_example", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    backend = module.LocalSACFixtureBackend()
    adapter = SACDispatchAdapter(backend)
    request = ActionRequest(principal=Principal(user_id="demo-user-001", tenant_id="demo-team-001", session_id="demo-session-sac"),
        action=adapter.action, resource_type=adapter.resource_type, resource_id="demo-plan-001", trace_id="sac-integration")
    return backend, request, GovernanceRuntime(adapter, Policy("3.0.0", (adapter.action,)))


def test_registry_hashes():
    assert len(verify_v3_registry()) == 2
    registry = V2SkillRegistry()
    for name, version in (("dispatch-plan-risk-review", "1.1.0"), ("dispatch-plan-risk-gate", "2.0.0")):
        assert len(registry.load(name, version)[2]) == 64


def test_sac_pass_uses_original_v2_and_backend_execution():
    backend, request, runtime = make_sac()
    assert runtime.evaluate(request).decision == "PASS"
    approval = runtime.approve(request)
    assert runtime.execute(request, approval.approval_id).executed
    assert backend.activations == 1


@pytest.mark.parametrize("violation", ["validator", "active_drift", "schedule", "expired", "policy"])
def test_sac_original_block_semantics(violation):
    backend, request, runtime = make_sac()
    facts = backend.state.model_dump()["facts"]
    replan = facts["replan_result"]
    if violation == "validator":
        replan["validation_result"].update(feasible=False, status="FAIL")
    elif violation == "active_drift":
        facts["active_plan_id"] = "demo-active-other"
    elif violation == "schedule":
        replan["candidate_plan"]["schedule"].pop()
    elif violation == "expired":
        replan["candidate_plan"]["valid_until"] = "2020-01-01T00:00:00Z"
    else:
        replan["policy_result"]["allowed"] = False
    backend.state = backend.state.model_copy(update={"facts": facts})
    assert runtime.evaluate(request).decision == "BLOCK"
    assert backend.activations == 0


def test_sac_active_drift_after_approval():
    backend, request, runtime = make_sac()
    approval = runtime.approve(request)
    facts = backend.state.model_dump()["facts"]
    facts["active_plan_id"] = "demo-active-other"
    backend.state = backend.state.model_copy(update={"facts": facts})
    assert not runtime.execute(request, approval.approval_id).executed
    assert backend.activations == 0
