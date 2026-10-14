import hashlib
import json

import pytest

from agent_governance.evolution.dev1 import (
    DistilledExperience, snapshot, propose, BoundFilePatch, BoundPatchProposal, apply_bound_patch,
)
from agent_governance.evolution.adapters.sac import SACReviewBridge
from agent_governance.evolution.models import MutationScope
from agent_governance.fingerprint import fingerprint
from test_evolution import ROOT, cluster, candidate
from test_evolution_promotion import setup, approve


def experience(**changes):
    values = dict(experience_id=fingerprint("experience"), target_skill="review",
        failure_signature="missing_summary", symptom="说明不完整", expected_behavior="完整说明已有事实",
        observed_behavior="遗漏已有事实", root_cause="遗漏说明要求",
        recommended_mutation_scope=("prompt.md",), support_count=3,
        source_refs=("source:" + fingerprint("source"),), actionable=True)
    values.update(changes)
    return DistilledExperience(**values)


def proposal(champion, row, original_hash=None):
    old = (champion / "prompt.md").read_bytes()
    return BoundPatchProposal(parent_hash=snapshot(champion).package_hash,
        patches=(BoundFilePatch(path="prompt.md", original_hash=original_hash or hashlib.sha256(old).hexdigest(),
            before=old.decode(), after=old.decode() + "\n请逐项检查遗漏。", reason="完善解释",
            experience_ids=(row.experience_id,)),), rationale="最小补丁")


def test_champion_context_visible_to_generator():
    champion = snapshot(ROOT / "skills/sac-plan-review")
    row = experience()
    class Provider:
        def complete(self, messages):
            data = json.loads(messages[1]["content"])
            assert data["champion"]["prompt_content"] == champion.prompt_content
            assert data["experiences"][0]["expected_behavior"] == row.expected_behavior
            assert "heldout" not in data
            assert "当前 Skill" in messages[0]["content"]
            return type("R", (), {"content": proposal(ROOT / "skills/sac-plan-review", row).model_dump_json(),
                                 "tool_calls": []})()
    assert propose(Provider(), champion, (row,), MutationScope()).parent_hash == champion.package_hash


@pytest.mark.parametrize("changes", [{"actionable": False}, {"split": "heldout"}])
def test_generator_rejects_ineligible_experience(changes):
    class Provider:
        def complete(self, messages):
            raise AssertionError("不应调用 provider")
    with pytest.raises(ValueError):
        propose(Provider(), snapshot(ROOT / "skills/sac-plan-review"), (experience(**changes),), MutationScope())


def test_bound_patch_applies_and_records_diff(tmp_path):
    champion = ROOT / "skills/sac-plan-review"
    row = experience()
    result, diffs = apply_bound_patch(champion, tmp_path, proposal(champion, row), (row,), (cluster(),))
    assert result.changed_files == ("prompt.md",)
    assert "+请逐项检查遗漏。" in diffs[0]


def test_bound_patch_rejects_stale_original_hash(tmp_path):
    champion = ROOT / "skills/sac-plan-review"
    row = experience()
    with pytest.raises(ValueError, match="原文件 hash"):
        apply_bound_patch(champion, tmp_path, proposal(champion, row, fingerprint("wrong")), (row,), (cluster(),))


def test_bound_patch_rejects_missing_experience(tmp_path):
    champion = ROOT / "skills/sac-plan-review"
    row = experience()
    with pytest.raises(ValueError, match="准入经验"):
        apply_bound_patch(champion, tmp_path, proposal(champion, row), (), (cluster(),))


class ResponseProvider:
    def __init__(self, tool_calls=()):
        self.calls = []
        self.tool_calls = tool_calls
    def complete(self, messages):
        self.calls.append(messages)
        return type("R", (), {"content": "说明：未执行操作。", "tool_calls": self.tool_calls})()


class CapturingRuntime:
    def review(self, context, gate, **kwargs):
        payload = {"citations": [], "gate_decision": gate["decision"], "authoritative_facts": {}}
        return {"gate_decision": gate["decision"], "user_explanation": kwargs["llm_explainer"](payload)}


def test_default_injection_preserves_original_prompt():
    provider = ResponseProvider()
    bridge = SACReviewBridge(CapturingRuntime(), object(), provider, "原生产 Prompt")
    result = bridge.review({"review_question": "审核"}, {"decision": "BLOCK"})
    assert provider.calls[0][0]["content"] == "原生产 Prompt"
    assert result["gate_decision"] == "BLOCK"


def test_explicit_override_changes_only_explanation():
    provider = ResponseProvider()
    bridge = SACReviewBridge(CapturingRuntime(), object(), provider, "原生产 Prompt")
    champion = snapshot(ROOT / "skills/sac-plan-review")
    gate = {"decision": "BLOCK"}
    result = bridge.review({"review_question": "审核"}, gate, review_skill_override=champion)
    assert champion.prompt_content in provider.calls[0][0]["content"]
    assert result["gate_decision"] == gate["decision"] == "BLOCK"
    assert result["evolution_skill_hash"] == champion.package_hash


def test_review_tool_calls_never_execute():
    provider = ResponseProvider(tool_calls=("write",))
    bridge = SACReviewBridge(CapturingRuntime(), object(), provider, "原生产 Prompt")
    with pytest.raises(ValueError, match="不能调用工具"):
        bridge.review({}, {"decision": "BLOCK"})


def test_override_cannot_mutate_callers_context():
    class Runtime:
        def review(self, context, gate, **kwargs):
            context["nested"]["value"] = 2
            return {"gate_decision": gate["decision"]}
    context = {"nested": {"value": 1}}
    SACReviewBridge(Runtime(), object(), None, "原生产 Prompt").review(context, {"decision": "PASS"})
    assert context["nested"]["value"] == 1


def test_gate_override_rejected():
    class Runtime:
        def review(self, context, gate, **kwargs):
            gate["decision"] = "PASS"
            return {"gate_decision": "PASS"}
    with pytest.raises(ValueError, match="覆盖 Gate"):
        SACReviewBridge(Runtime(), object(), None, "原生产 Prompt").review({}, {"decision": "BLOCK"})


def test_lineage_records_promoted_hash(setup):
    runtime, adapter, request, _ = setup
    assert runtime.execute(request, approve(runtime, request)).executed
    state = adapter.state()
    assert state["lineage"][-1]["promoted_hash"] == state["champion"]
