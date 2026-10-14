"""纯合成基础设施闭环，不使用私下 SAC 数据，也不代表真实模型提升。"""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from agent_governance.evolution.feedback import ReviewFeedbackCollector
from agent_governance.evolution.models import EvolutionEvaluationReport, SuiteResult
from agent_governance.evolution.review_quality import (
    ReviewQualityScorer,
    SemanticReviewJudge,
)
from agent_governance.evolution.quality_gate import decide
from agent_governance.evolution.promotion import SkillPromotionAdapter
from agent_governance.evolution.validator import package_hash
from agent_governance.evolution.evaluator import report_hash
from agent_governance.fingerprint import fingerprint
from agent_governance.models import ActionRequest, Principal
from agent_governance.policy import Policy
from agent_governance.runtime import GovernanceRuntime


def explain(directory, identity, kind, decision):
    instruction = (directory / "prompt.md").read_text(encoding="utf-8")
    complete = kind != "target" or "逐项解释已有约束影响" in instruction
    text = "对象尚未执行，需按既有审批流程复核。" + (
        "已逐项解释约束影响。" if complete else ""
    )
    judge = SimpleNamespace(
        complete=lambda messages: SimpleNamespace(
            content=json.dumps(
                {
                    "review_complete": True,
                    "constraint_explanation": complete,
                    "confirmation_clear": True,
                }
            )
        )
    )
    result = {
        "review_id": identity,
        "gate_decision": decision,
        "full_review_status": "COMPLETE",
        "explanation_mode": "LLM",
        "user_explanation": text,
        "constraint_summary": [
            {"constraint_type": "constraint_limit", "requested_value": 1}
        ],
        "knowledge_status": "INSUFFICIENT",
        "knowledge_evidence": [],
        "citations": [],
    }
    return ReviewQualityScorer(
        b"synthetic-demo-only-key-at-least32", SemanticReviewJudge(judge)
    ).score(
        context={
            "expected_constraints": {"constraint_limit": 1},
            "execution_confirmed": False,
        },
        gate={"decision": decision},
        result=result,
        task_key=identity,
        candidate_key=identity,
        origin="synthetic",
        target_skill="generic-review",
        skill_hash=package_hash(directory),
        skill_version="0.1.0",
        split="evolution_dev",
    )


class SyntheticPatchProvider:
    def complete(self, messages):
        data = json.loads(messages[1]["content"])
        old = data["champion"]["prompt_content"]
        assert all(row["split"] == "evolution_dev" for row in data["experiences"])
        return SimpleNamespace(
            content=json.dumps(
                {
                    "parent_hash": data["champion"]["package_hash"],
                    "patches": [
                        {
                            "path": "prompt.md",
                            "original_hash": hashlib.sha256(old.encode()).hexdigest(),
                            "before": old,
                            "after": old + "逐项解释已有约束影响。",
                            "reason": "仅修合成遗漏",
                            "experience_ids": [
                                row["experience_id"] for row in data["experiences"]
                            ],
                        }
                    ],
                    "rationale": "仅合成基础设施示例",
                }
            )
        )


def run(root):
    champion = root / "champion"
    champion.mkdir()
    for name, text in {
        "SKILL.md": "---\nname: generic-review\ndescription: 合成只读解释示例。\n---\n只解释已有事实。",
        "manifest.json": json.dumps(
            {
                "name": "generic-review",
                "version": "0.1.0",
                "read_only": True,
                "permissions": ["read"],
            }
        ),
        "workflow.yaml": "mode: read_only\nsteps: [summarize_constraints]\n",
        "prompt.md": "解释已有事实，不声称已执行。",
    }.items():
        (champion / name).write_text(text, encoding="utf-8", newline="\n")
    collector = ReviewFeedbackCollector(root / "feedback")
    for i in range(3):
        collector.collect(explain(champion, f"fault-{i}", "target", "PASS"))
    state = next(
        row
        for row in collector.states(origin="synthetic")
        if row["state"] == "CANDIDATE_READY"
    )
    candidate, _ = collector.generate_ready(
        state["bucket"],
        champion,
        root / "candidates",
        SyntheticPatchProvider(),
        source_skill_hash=package_hash(champion),
    )
    directory = root / "candidates" / candidate.candidate_id
    suites = []
    counters = {
        k: 0
        for k in (
            "safety_regressions",
            "block_overrides",
            "false_successes",
            "unauthorized_actions",
            "schema_regressions",
            "no_evidence_regressions",
        )
    }
    for kind in ("target", "regression", "heldout"):
        original, changed = [], []
        for i, decision in enumerate(("PASS", "REVIEW", "BLOCK")):
            before = explain(champion, f"{kind}-{i}", kind, decision)
            after = explain(directory, f"{kind}-{i}", kind, decision)
            original.append(before.overall_status != "FAIL")
            changed.append(after.overall_status != "FAIL")
            counters["block_overrides"] += int(
                decision == "BLOCK" and not after.decision_consistent
            )
            counters["false_successes"] += int(after.unsupported_success_claim)
            counters["schema_regressions"] += int(not after.decision_consistent)
            counters["no_evidence_regressions"] += int(
                not after.evidence_grounded or not after.citation_supported
            )
        suites.append(
            SuiteResult(
                suite=kind,
                count=3,
                baseline_score=sum(original) / 3,
                candidate_score=sum(changed) / 3,
                passed=all(changed),
            )
        )
    report = EvolutionEvaluationReport(
        candidate_hash=candidate.candidate_hash,
        parent_hash=candidate.parent_hash,
        configuration_hash=fingerprint("synthetic-generic-v1"),
        status="COMPLETE",
        suites=tuple(suites),
        **counters,
    )
    gate = decide(candidate, report, static_valid=True)
    assert gate.decision == "NEEDS_REVIEW"
    adapter = SkillPromotionAdapter(
        root / "staging",
        owner_id="demo-reviewer",
        tenant_id="demo-tenant",
        candidates={candidate.candidate_id: (candidate, directory)},
        evaluator=lambda row: report,
    )
    adapter.bootstrap(champion)
    runtime = GovernanceRuntime(
        adapter,
        Policy(
            version="development-staging",
            allowed_actions=("promote_skill_candidate", "rollback_skill_version"),
        ),
    )
    principal = Principal(
        user_id="demo-reviewer", tenant_id="demo-tenant", session_id="demo-session"
    )
    request = ActionRequest(
        principal=principal,
        action="promote_skill_candidate",
        resource_type="skill_candidate",
        resource_id=candidate.candidate_id,
        trace_id="demo-promotion",
        payload={
            "candidate_hash": candidate.candidate_hash,
            "report_hash": report_hash(report),
            "expected_champion": adapter.state()["champion"],
        },
    )
    assert not runtime.execute(request, "no-approval").executed
    approval = runtime.approve(request, review_acknowledged=True)
    execution = runtime.execute(request, approval.approval_id)
    assert execution.executed
    state_after = adapter.state()
    promoted_hash = state_after["champion"]
    promoted = adapter.root / state_after["versions"][promoted_hash]["path"]
    assert package_hash(promoted) == promoted_hash
    assert (
        explain(promoted, "post-promotion", "target", "BLOCK").overall_status != "FAIL"
    )
    rollback = ActionRequest(
        principal=principal,
        action="rollback_skill_version",
        resource_type="skill_candidate",
        resource_id=state_after["previous"],
        trace_id="demo-rollback",
        payload={
            "target_hash": state_after["previous"],
            "expected_champion": promoted_hash,
        },
    )
    rollback_approval = runtime.approve(rollback, review_acknowledged=True)
    rolled = runtime.execute(rollback, rollback_approval.approval_id)
    final = adapter.state()
    assert rolled.executed and final["champion"] == candidate.parent_hash
    assert len(final["lineage"]) == 2 and len(final["receipts"]) == 2
    return {
        "scope": "SYNTHETIC_INFRASTRUCTURE_ONLY",
        "feedback": 3,
        "candidate_ready": True,
        "candidate_hash": candidate.candidate_hash,
        "gate": gate.decision,
        "approval": {
            "approval_mode": "DEVELOPMENT_STAGING",
            "approval_id": approval.approval_id,
        },
        "promotion": "PASS",
        "promoted_hash": promoted_hash,
        "post_promotion_smoke": "PASS",
        "rollback": "PASS",
        "parent_restored": final["champion"] == candidate.parent_hash,
        "lineage_count": len(final["lineage"]),
    }


if __name__ == "__main__":
    print("仅合成基础设施示例：模型可以提出 Skill 修改，但不能决定自己上线。")
    with TemporaryDirectory(prefix="governed-evolution-") as temporary:
        print(json.dumps(run(Path(temporary)), ensure_ascii=False, indent=2))
