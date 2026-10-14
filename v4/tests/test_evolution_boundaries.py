import json
import os
import subprocess
import sys

import pytest

from agent_governance.evolution.adapters.sac import read_observations
from agent_governance.evolution.experience import ExperienceStore
from agent_governance.evolution.lineage import registry_lock
from agent_governance.evolution.observation import record
from agent_governance.evolution.validator import validate_package
from test_evolution import observation, ROOT, candidate


def test_private_row_without_split_not_auto_dev(tmp_path):
    path = tmp_path / "private.jsonl"
    path.write_text(json.dumps({"case_id": "demo", "task_success": False}), encoding="utf-8")
    with pytest.raises(ValueError, match="不得默认"):
        read_observations(path)


def test_unscoreable_not_false_failure(tmp_path):
    path = tmp_path / "private.jsonl"
    path.write_text(json.dumps({"case_id": "demo", "split": "dev", "scoreable": False,
                               "task_success": None}), encoding="utf-8")
    assert read_observations(path) == ()


def test_routing_failure_not_review_prompt_failure(tmp_path):
    path = tmp_path / "private.jsonl"
    path.write_text(json.dumps({"case_id": "demo", "split": "dev", "task_success": False,
        "category": "candidate_review", "task_decision": "candidate_review",
        "semantic_events": ["review_skill"], "error": {"intent_ok": False}}), encoding="utf-8")
    assert read_observations(path)[0].category == "routing"


def test_runtime_failure_not_review_prompt_failure(tmp_path):
    path = tmp_path / "private.jsonl"
    path.write_text(json.dumps({"case_id": "demo", "split": "dev", "task_success": False,
        "category": "candidate_review", "semantic_events": ["review_skill"],
        "error": {"status_ok": False}}), encoding="utf-8")
    assert read_observations(path)[0].category == "workflow"


def test_experience_tamper_detected(tmp_path):
    store = ExperienceStore(tmp_path)
    row = record(observation())
    store.put(row)
    path = tmp_path / (row.experience_id + ".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["outcome"] = "success"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="内容与 ID"):
        store.records()


def test_cross_process_registry_lock(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1",
               PYTHONIOENCODING="utf-8")
    code = ("import sys; from pathlib import Path; "
            "from agent_governance.evolution.lineage import registry_lock; "
            "ctx=registry_lock(Path(sys.argv[1])); ctx.__enter__()")
    with registry_lock(tmp_path):
        result = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
                                env=env, capture_output=True, text=True, encoding="utf-8")
        assert result.returncode != 0
        assert "REGISTRY_BUSY" in result.stderr


def test_hidden_directory_invalid(candidate):
    directory = candidate[1]
    (directory / ".hidden").mkdir()
    with pytest.raises(ValueError, match="隐藏"):
        validate_package(directory)


def test_core_no_domain_terms():
    import re
    root = ROOT / "src/agent_governance/evolution"
    forbidden = re.compile(r"\b(soc|battery|dispatch|plan|price|tariff)\b", re.I)
    for path in root.rglob("*.py"):
        if path.name == "sac.py":
            continue
        assert not forbidden.search(path.read_text(encoding="utf-8")), path
