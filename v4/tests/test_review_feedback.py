import copy
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agent_governance.evolution.feedback import HumanReviewFeedback, ReviewFeedbackCollector, observe_safely
from agent_governance.evolution.review_quality import ReviewQualityScorer, SemanticReviewJudge, asserted, ReviewEvaluationReport
from agent_governance.evolution.dev1 import snapshot, BoundPatchProposal, BoundFilePatch
from agent_governance.fingerprint import fingerprint
from test_evolution import ROOT


KEY = b"synthetic-anonymization-key-32bytes"


def quality(case="synthetic-1", *, context=None, result=None, gate="PASS", judge=None, **changes):
    response = {"review_id": case, "gate_decision": gate, "full_review_status": "COMPLETE",
                "recommended_action": "CONFIRM", "knowledge_status": "NOT_REQUIRED", "knowledge_evidence": [],
                "citations": [], "user_explanation": "候选仍待审批，未执行激活；没有可用外部知识证据。",
                "explanation_mode": "LLM", "constraint_summary": [], "plan_delta_summary": {}}
    response.update(result or {})
    values = dict(context=context or {}, gate={"decision": gate}, result=response, task_key=case,
                  candidate_key=case, origin="synthetic", skill_hash=fingerprint("skill"), skill_version="1.0.0", target_skill="review")
    values.update(changes)
    return ReviewQualityScorer(KEY, judge).score(**values)


def failed(case="synthetic-1", **changes):
    return quality(case, result={"user_explanation": "已激活。"}, **changes)


def test_gate_decision_consistent():
    assert quality().decision_consistent is True


def test_block_execution_claim_is_observation_not_permission():
    result = quality(gate="BLOCK", result={"user_explanation": "可以直接执行。"})
    assert result.decision_consistent is False
    assert "review.decision_inconsistent" in result.skill_fixable_signatures


def test_structured_comparison_missing_is_not_prompt_failure():
    result = quality(context={"expected_delta": {"cost_delta": 2.0}})
    assert result.candidate_comparison is False
    assert result.cost_benefit_explanation is False
    assert not result.skill_fixable_signatures


def test_structured_constraint_missing_is_not_prompt_failure():
    result = quality(context={"expected_constraints": {"reserve_soc_min": 0.4}})
    assert result.constraint_explanation is False
    assert not result.skill_fixable_signatures


def test_citation_claim_without_evidence():
    report = quality(result={"user_explanation": "根据手册 [cite:missing]，该操作符合要求。"})
    assert report.citation_supported is False and report.evidence_grounded is False
    assert "review.citation_unsupported" in report.skill_fixable_signatures


def test_supported_evidence_and_no_evidence_abstention():
    supported = quality(result={"knowledge_status": "AVAILABLE", "knowledge_evidence": [
        {"document_id": "synthetic-document", "citation": "cite:synthetic"}],
        "citations": ["cite:synthetic"], "user_explanation": "根据手册 [cite:synthetic]，仍需审批。"})
    assert supported.evidence_grounded and supported.citation_supported
    abstain = quality(result={"knowledge_status": "INSUFFICIENT"})
    assert abstain.evidence_grounded and abstain.citation_supported
    assert abstain.overall_status == "PARTIAL"


@pytest.mark.parametrize("text,wrong", [
    ("已激活。", True), ("未激活。", False), ("不表示已经激活。", False),
    ("审批后将执行成功。", False), ("不能声称“已激活”。", False), ("未激活，但修改成功。", True),
])
def test_claim_negation_and_condition_boundaries(text, wrong):
    assert quality(result={"user_explanation": text}).unsupported_success_claim is wrong


def test_semantic_judge_uses_existing_provider_and_failure_is_optional():
    class Provider:
        def complete(self, messages):
            assert "只读" in messages[0]["content"]
            return SimpleNamespace(content='{"confirmation_clear": false}', tool_calls=[])
    report = quality(judge=SemanticReviewJudge(Provider()))
    assert report.semantic_status == "PASS" and report.confirmation_clear is False
    assert "review.confirmation_unclear" in report.skill_fixable_signatures
    class Broken:
        def complete(self, messages):
            raise TimeoutError("synthetic failure")
    report = quality(judge=SemanticReviewJudge(Broken()))
    assert report.semantic_status == "FAILED" and report.decision_consistent is True


def test_semantic_judge_cannot_brush_structural_failure_green():
    class Provider:
        def complete(self, messages):
            return SimpleNamespace(content='{"candidate_comparison": true}', tool_calls=[])
    report = quality(context={"expected_delta": {"cost_delta": 1.0}}, judge=SemanticReviewJudge(Provider()))
    assert report.candidate_comparison is False


def test_same_case_retries_do_not_accumulate_support(tmp_path):
    collector = ReviewFeedbackCollector(tmp_path)
    original = failed()
    collector.collect(original)
    retried = original.model_copy(update={"review_id": fingerprint("different-review-run")})
    collector.collect(retried)
    assert collector.states()[0]["support_count"] == 1
    assert collector.states()[0]["state"] == "INSUFFICIENT_EVIDENCE"


def test_same_signature_three_cases_trigger_synthetic_only(tmp_path):
    collector = ReviewFeedbackCollector(tmp_path)
    for i in range(3):
        collector.collect(failed(f"synthetic-{i}"))
    states = collector.states()
    assert states[0]["state"] == "CANDIDATE_READY" and states[0]["support_count"] == 3
    assert states[0]["origin"] == "synthetic" and collector.states(origin="live") == ()


def test_different_signatures_and_versions_never_merge(tmp_path):
    collector = ReviewFeedbackCollector(tmp_path)
    collector.collect(failed("synthetic-1"))
    collector.collect(quality("synthetic-2", gate="BLOCK", result={"user_explanation": "可以直接执行。"}))
    collector.collect(failed("synthetic-3", skill_hash=fingerprint("other-skill"), skill_version="2.0.0"))
    assert all(row["state"] == "INSUFFICIENT_EVIDENCE" for row in collector.states())


def test_human_clarification_and_business_reject_are_distinct(tmp_path):
    collector = ReviewFeedbackCollector(tmp_path)
    report = quality()
    collector.collect(report)
    assert collector.human_feedback(HumanReviewFeedback(review_id=report.review_id, status="REJECTED")) == ()
    feedback = HumanReviewFeedback(review_id=report.review_id, status="NEEDS_CLARIFICATION", correction_type="confirmation_clear")
    assert collector.human_feedback(feedback)[0]["support_count"] == 1
    assert collector.human_feedback(feedback)[0]["support_count"] == 1


def test_persisted_feedback_has_no_raw_text_or_id(tmp_path):
    report = failed("synthetic-private-user-and-device")
    collector = ReviewFeedbackCollector(tmp_path)
    collector.collect(report)
    assert "synthetic-private-user-and-device" not in report.model_dump_json()
    assert b"synthetic-private-user-and-device" not in collector.database.read_bytes()


def test_exception_observation_logs_type_only(caplog):
    def broken():
        raise ValueError("synthetic-sensitive-detail")
    assert observe_safely(broken) is None
    assert "ValueError" in caplog.text and "synthetic-sensitive-detail" not in caplog.text


def test_heldout_does_not_enter_experience(tmp_path):
    collector = ReviewFeedbackCollector(tmp_path)
    assert collector.collect(failed(split="heldout")) == ()
    assert collector.states() == ()


def test_later_heldout_copy_quarantines_existing_support(tmp_path):
    collector = ReviewFeedbackCollector(tmp_path)
    for i in range(3):
        collector.collect(failed(f"synthetic-{i}"))
    assert collector.states()[0]["state"] == "CANDIDATE_READY"
    collector.collect(failed("synthetic-1").model_copy(
        update={"split": "heldout", "review_id": fingerprint("heldout-run")}))
    assert collector.states()[0]["support_count"] == 2
    assert collector.states()[0]["state"] == "INSUFFICIENT_EVIDENCE"


def test_replay_anonymous_reports_deduplicates(tmp_path):
    source = tmp_path / "anonymous.jsonl"
    source.write_text(failed().model_dump_json() + "\n" + failed().model_dump_json(), encoding="utf-8")
    completed = subprocess.run([sys.executable, "-m", "agent_governance.evolution.replay_feedback",
                                str(source), "--private-output", str(tmp_path / "output")],
                               capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["states"][0]["support_count"] == 1


def test_ready_candidate_only_calls_champion_aware_path(tmp_path):
    import hashlib
    champion_root = ROOT / "skills/sac-plan-review"
    champion = snapshot(champion_root)
    collector = ReviewFeedbackCollector(tmp_path / "private")
    for i in range(3):
        collector.collect(failed(f"synthetic-{i}", target_skill=champion.skill_name,
                                 skill_version=champion.version, skill_hash=champion.package_hash))
    class Provider:
        def complete(self, messages):
            data = json.loads(messages[1]["content"])
            assert data["champion"]["package_hash"] == champion.package_hash
            exp = data["experiences"][0]
            old = champion.prompt_content
            patch = BoundPatchProposal(parent_hash=champion.package_hash, patches=(BoundFilePatch(
                path="prompt.md", original_hash=hashlib.sha256(old.encode()).hexdigest(), before=old,
                after=old + "\n再次说明候选尚未执行。", reason="合成边界测试", experience_ids=(exp["experience_id"],)),), rationale="合成补丁")
            return SimpleNamespace(content=patch.model_dump_json(), tool_calls=[])
    candidate, _ = collector.generate_ready(collector.states()[0]["bucket"], champion_root,
                                            tmp_path / "sandbox", Provider(), source_skill_hash=champion.package_hash)
    assert candidate.changed_files == ("prompt.md",)
    assert snapshot(champion_root).package_hash == champion.package_hash


def test_multidimensional_report_cannot_claim_unrun_metrics():
    with pytest.raises(ValueError, match="未执行"):
        ReviewEvaluationReport(candidate_hash=fingerprint("c"), parent_hash=fingerprint("p"),
            configuration_hash=fingerprint("config"), status="NOT_RUN", general_regression_accuracy=1.0)
