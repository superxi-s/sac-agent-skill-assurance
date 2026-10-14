import hashlib
import json
import shutil
import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_governance.evolution.adapters.sac import read_observations, preserve_gate, SACStrongLLMGenerator
from agent_governance.evolution.candidate import build_candidate, DeterministicDemoGenerator
from agent_governance.evolution.evaluator import not_run, report_hash
from agent_governance.evolution.experience import ExperienceStore, mine
from agent_governance.evolution.models import (
    EvolutionObservation, EvolutionEvaluationReport, SuiteResult, MutationScope, FilePatch, PatchProposal,
)
from agent_governance.evolution.observation import record
from agent_governance.evolution.quality_gate import decide
from agent_governance.evolution.validator import package_hash, validate_package
from agent_governance.fingerprint import fingerprint

ROOT = Path(__file__).resolve().parents[1]


def observation(index=1, **kwargs):
    values = dict(observation_id=fingerprint(index), source_refs=("source:" + fingerprint(index),),
                  split="dev", outcome="failure", category="review")
    values.update(kwargs)
    return EvolutionObservation(**values)


def cluster():
    return mine(tuple(record(observation(i)) for i in range(3)))[0]


@pytest.fixture
def candidate(tmp_path):
    champion = tmp_path / "champion"
    shutil.copytree(ROOT / "skills" / "sac-plan-review", champion)
    experiences = (cluster(),)
    proposal = DeterministicDemoGenerator().propose(experiences)
    result = build_candidate(champion, tmp_path / "candidates", proposal, experiences)
    return champion, tmp_path / "candidates" / result.candidate_id, result


def complete(candidate, **kwargs):
    values = dict(candidate_hash=candidate.candidate_hash, parent_hash=candidate.parent_hash,
        configuration_hash=fingerprint("config"), status="COMPLETE",
        suites=tuple(SuiteResult(suite=suite, count=3, baseline_score=0.8,
                                 candidate_score=0.9, passed=True)
                     for suite in ("target", "regression", "heldout")),
        safety_regressions=0, block_overrides=0, false_successes=0,
        unauthorized_actions=0, schema_regressions=0, no_evidence_regressions=0)
    values.update(kwargs)
    return EvolutionEvaluationReport(**values)


def test_frozen_v3_characterization():
    hashes = json.loads((ROOT / "docs/evolution/v3_protected_hashes.json").read_text(encoding="utf-8"))
    for path, expected in hashes.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path


def test_observation_frozen():
    row = observation()
    with pytest.raises(ValidationError):
        row.outcome = "success"


def test_observation_forbids_raw_sensitive():
    with pytest.raises(ValidationError):
        observation(customer_id="private")


def test_observation_forbids_raw_source_path():
    with pytest.raises(ValidationError):
        observation(source_refs=("C:/private/file",))


def test_single_failure_not_admitted():
    assert not mine((record(observation()),))[0].admitted


def test_dedup_support_count(tmp_path):
    item = record(observation())
    store = ExperienceStore(tmp_path / "private")
    store.put(item)
    store.put(item)
    assert len(store.records()) == 1
    assert mine((item, item))[0].support_count == 1


def test_cluster_admission():
    assert cluster().support_count == 3
    assert cluster().admitted


def test_high_risk_near_miss_admitted():
    assert mine((record(observation(outcome="near_miss", high_risk=True)),))[0].admitted


def test_success_not_candidate_source():
    assert not mine(tuple(record(observation(i, outcome="success")) for i in range(4)))[0].admitted


@pytest.mark.parametrize("path", [
    "../runtime.py", "src/agent_governance/runtime.py", "registry.json",
    "tests/gold.json", ".hidden.md", "/tmp/a.md", "references/../a.md",
    "references/.hidden.md", "references/a.py", "C:/a.md", "references\\a.md",
    "manifest.json", "references//a.md",
])
def test_protected_patch_rejected(tmp_path, path):
    proposal = PatchProposal(patches=(FilePatch(path=path, content="说明"),), rationale="测试")
    with pytest.raises(ValueError):
        build_candidate(ROOT / "skills/sac-plan-review", tmp_path / "candidates", proposal, (cluster(),))


def test_custom_scope_cannot_allow_runtime(tmp_path):
    proposal = PatchProposal(patches=(FilePatch(path="runtime.py", content="说明"),), rationale="测试")
    with pytest.raises(ValueError):
        build_candidate(ROOT / "skills/sac-plan-review", tmp_path, proposal, (cluster(),),
                        MutationScope(allowed_files=("runtime.py",)))


def test_candidate_hash_and_champion_preserved(candidate):
    champion, directory, result = candidate
    assert package_hash(champion) == result.parent_hash
    assert package_hash(directory) == result.candidate_hash
    assert result.changed_files == ("references/review_checklist.md",)
    assert not (champion / result.changed_files[0]).exists()


def test_candidate_no_overwrite(candidate):
    champion, directory, result = candidate
    with pytest.raises(ValueError, match="已存在"):
        build_candidate(champion, directory.parent,
                        DeterministicDemoGenerator().propose((cluster(),)), (cluster(),))


@pytest.mark.parametrize("content", [
    "mode: read_only\nsteps: [write_registry]",
    "mode: execute\nsteps: [summarize_constraints]",
    "mode: read_only\nsteps: [summarize_constraints]\ncommand: python",
    "!!python/object/apply:os.system ['echo test']",
])
def test_indirect_write_workflow_rejected(tmp_path, content):
    proposal = PatchProposal(patches=(FilePatch(path="workflow.yaml", content=content),), rationale="测试")
    with pytest.raises(Exception):
        build_candidate(ROOT / "skills/sac-plan-review", tmp_path, proposal, (cluster(),))


@pytest.mark.parametrize("content", ["C:\\Users\\demo", "/mnt/data/private", "sk-" + "x" * 20])
def test_sensitive_patch_rejected(tmp_path, content):
    proposal = PatchProposal(patches=(FilePatch(path="prompt.md", content=content),), rationale="测试")
    with pytest.raises(ValueError):
        build_candidate(ROOT / "skills/sac-plan-review", tmp_path, proposal, (cluster(),))


def test_symlink_rejected(tmp_path):
    champion = tmp_path / "champion"
    shutil.copytree(ROOT / "skills/sac-plan-review", champion)
    link = champion / "references"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        outside = tmp_path / "outside"
        outside.mkdir()
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True,
                       capture_output=True)
    with pytest.raises(ValueError):
        validate_package(champion)


def test_not_run_cannot_promote(candidate):
    result = candidate[2]
    report = not_run(result, {"same_configuration": True}, "缺少真实候选注入入口")
    gate = decide(result, report, static_valid=True)
    assert gate.decision == "REJECTED"
    assert gate.report_hash == report_hash(report)
    assert "EVALUATION_NOT_RUN" in gate.reasons


@pytest.mark.parametrize("field", [
    "safety_regressions", "block_overrides", "false_successes",
    "unauthorized_actions", "schema_regressions", "no_evidence_regressions",
])
def test_safety_regression_rejected(candidate, field):
    report = complete(candidate[2], **{field: 1})
    assert decide(candidate[2], report, static_valid=True).decision == "REJECTED"


def test_needs_review_never_auto_promote(candidate):
    report = complete(candidate[2])
    assert decide(candidate[2], report, static_valid=True).decision == "NEEDS_REVIEW"


def test_negative_transfer_rejected(candidate):
    report = complete(candidate[2], suites=(
        SuiteResult(suite="target", count=3, baseline_score=0.8, candidate_score=0.9, passed=True),
        SuiteResult(suite="regression", count=3, baseline_score=0.9, candidate_score=0.8, passed=True),
        SuiteResult(suite="heldout", count=3, baseline_score=0.9, candidate_score=0.9, passed=True),
    ))
    assert "NEGATIVE_TRANSFER" in decide(candidate[2], report, static_valid=True).reasons


def test_complete_requires_three_suites(candidate):
    with pytest.raises(ValidationError):
        complete(candidate[2], suites=())


def test_not_run_cannot_claim_zero_safety(candidate):
    with pytest.raises(ValidationError):
        EvolutionEvaluationReport(candidate_hash=candidate[2].candidate_hash,
            parent_hash=candidate[2].parent_hash, configuration_hash=fingerprint("x"),
            status="NOT_RUN", safety_regressions=0)


def test_report_binding(candidate):
    report = complete(candidate[2], candidate_hash=fingerprint("other"))
    assert "REPORT_BINDING_MISMATCH" in decide(candidate[2], report, static_valid=True).reasons


def test_sac_private_adapter_redacts_and_excludes_heldout(tmp_path):
    data = [
        {"case_id": "private-case", "split": "calibration", "category": "candidate_review",
         "task_decision": "candidate_review", "task_success": False, "trajectory_valid": False,
         "query": "真实业务隐私", "user_id": "private"},
        {"case_id": "blind", "split": "blind", "task_success": False, "query": "保留测试内容"},
    ]
    path = tmp_path / "private.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in data), encoding="utf-8")
    rows = read_observations(path)
    assert len(rows) == 1
    assert rows[0].outcome == "failure" and rows[0].category == "review"
    assert "真实业务隐私" not in rows[0].model_dump_json()
    assert "private-case" not in rows[0].model_dump_json()


def test_generator_context_only_admitted_aggregates():
    row = cluster()
    keys = set(row.model_dump())
    assert not keys.intersection({"heldout", "query", "path", "trace", "case_content"})
    assert DeterministicDemoGenerator().propose((row,)).patches


def test_strong_llm_reuses_protocol_and_no_tools():
    class Provider:
        def complete(self, messages, tools=None):
            assert tools is None
            assert "不可信业务数据" in messages[0]["content"]
            assert "heldout" not in messages[1]["content"]
            return type("Response", (), {"content": '{"patches":[{"path":"prompt.md","content":"只读说明"}],"rationale":"说明"}',
                                         "tool_calls": []})()
    assert SACStrongLLMGenerator(Provider()).propose((cluster(),)).patches


def test_gate_override_rejected():
    with pytest.raises(ValueError):
        preserve_gate("BLOCK", {"gate_decision": "PASS"})
    assert preserve_gate("BLOCK", {"gate_decision": "BLOCK"})["gate_decision"] == "BLOCK"
