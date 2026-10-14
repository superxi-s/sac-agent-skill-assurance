import pytest
from agent_governance.evolution.split import ReviewSplitAssigner
from agent_governance.evolution.feedback import HumanReviewFeedback, ReviewFeedbackCollector
from agent_governance.evolution.review_quality import SemanticReviewJudge
from agent_governance.fingerprint import fingerprint
from test_review_feedback import failed, quality


def test_stable_anonymous_split():
    assigner = ReviewSplitAssigner()
    rows = [assigner.assign(fingerprint(i)) for i in range(100)]
    assert rows == [ReviewSplitAssigner().assign(fingerprint(i)) for i in range(100)]
    assert set(rows) == {"evolution_dev", "regression", "protected_heldout"}
    with pytest.raises(ValueError):
        assigner.assign("原始身份")


@pytest.mark.parametrize("partition", ["regression", "protected_heldout"])
def test_non_development_reports_never_become_experience(tmp_path, partition):
    collector = ReviewFeedbackCollector(tmp_path)
    for i in range(3):
        report = failed(str(i), split=partition)
        assert collector.collect(report) == ()
        assert collector.human_feedback(HumanReviewFeedback(review_id=report.review_id,
            status="CORRECTED", correction_type="confirmation_clarity")) == ()
    with collector.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    assert collector.states() == ()


def test_development_aggregates_features(tmp_path):
    collector = ReviewFeedbackCollector(tmp_path)
    for i in range(3):
        collector.collect(failed(str(i), split="evolution_dev"))
    state = collector.states()[0]
    assert state["state"] == "CANDIDATE_READY" and state["support_count"] == 3
    assert state["missing_dimensions"] == ["unsupported_success_claim"]
    assert state["observed_patterns"] == ["review.unsupported_success_claim"]


@pytest.mark.parametrize("kind", ["constraint_explanation", "candidate_comparison", "cost_benefit",
    "soc_explanation", "evidence_grounding", "confirmation_clarity", "other"])
def test_explicit_human_correction_types(tmp_path, kind):
    collector = ReviewFeedbackCollector(tmp_path)
    row = quality(split="evolution_dev")
    collector.collect(row)
    result = collector.human_feedback(HumanReviewFeedback(review_id=row.review_id,
        status="NEEDS_CLARIFICATION", correction_type=kind))
    assert bool(result) == (kind != "other")


@pytest.mark.parametrize("mode", ["SELF_JUDGE", "INDEPENDENT_JUDGE"])
def test_judge_mode_recorded(mode):
    from types import SimpleNamespace
    provider = SimpleNamespace(complete=lambda messages: SimpleNamespace(content='{"confirmation_clear":true}'))
    report = quality(judge=SemanticReviewJudge(provider, mode=mode))
    assert report.judge_mode == mode


def test_regression_quarantines_old_development_support(tmp_path):
    collector = ReviewFeedbackCollector(tmp_path)
    for i in range(3):
        collector.collect(failed(str(i), split="evolution_dev"))
    assert collector.states()[0]["support_count"] == 3
    collector.collect(failed("0", split="regression"))
    assert collector.states()[0]["support_count"] == 2


def test_generator_receives_verifiable_original_hashes():
    import hashlib
    import json
    from agent_governance.evolution.dev1 import propose, snapshot
    from agent_governance.evolution.models import MutationScope
    from test_dev1 import experience, proposal
    from test_evolution import ROOT
    from types import SimpleNamespace
    root = ROOT / "skills/sac-plan-review"
    row = experience()
    class Provider:
        def complete(self, messages):
            data = json.loads(messages[1]["content"])
            assert data["original_file_hashes"]["prompt.md"] == hashlib.sha256((root / "prompt.md").read_bytes()).hexdigest()
            return SimpleNamespace(content=proposal(root, row).model_dump_json())
    assert propose(Provider(), snapshot(root), (row,), MutationScope()).patches


def test_narrow_scope_preserves_unchanged_package_assets(tmp_path):
    from agent_governance.evolution.dev1 import apply_bound_patch
    from agent_governance.evolution.models import MutationScope
    from test_dev1 import experience, proposal
    from test_evolution import ROOT, cluster
    root = ROOT / "skills/sac-plan-review"
    row = experience()
    scope = MutationScope(allowed_files=("prompt.md",), allow_references=False)
    result, _ = apply_bound_patch(root, tmp_path, proposal(root, row), (row,), (cluster(),), scope)
    assert result.changed_files == ("prompt.md",)


def test_narrow_scope_still_forbids_other_asset_mutation(tmp_path):
    from agent_governance.evolution.candidate import build_candidate
    from agent_governance.evolution.models import MutationScope, PatchProposal, FilePatch
    from test_evolution import ROOT, cluster
    with pytest.raises(ValueError, match="可变边界"):
        build_candidate(ROOT / "skills/sac-plan-review", tmp_path,
            PatchProposal(patches=(FilePatch(path="SKILL.md", content="不允许修改"),), rationale="测试"),
            (cluster(),), MutationScope(allowed_files=("prompt.md",), allow_references=False))
