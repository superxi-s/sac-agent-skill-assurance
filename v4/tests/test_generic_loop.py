import json
import os
from pathlib import Path
import subprocess
import sys

from agent_governance.evolution.snapshot import snapshot
from agent_governance.evolution.candidate import propose
from agent_governance.evolution.experience import distill_cluster
from agent_governance.evolution.protocols import EvolutionTarget, CandidateGenerator, ExperienceDistiller


def test_formal_functions_match_protocols_and_compatibility():
    from agent_governance.evolution import dev1
    assert dev1.snapshot is snapshot and dev1.propose is propose
    assert isinstance(snapshot, EvolutionTarget)
    assert isinstance(propose, CandidateGenerator)
    assert isinstance(distill_cluster, ExperienceDistiller)


def test_generic_example_executes_full_governed_loop():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run([sys.executable, "examples/skill_evolution/demo.py"], cwd=root,
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout[result.stdout.index("{"):])
    assert receipt["scope"] == "SYNTHETIC_INFRASTRUCTURE_ONLY"
    assert receipt["feedback"] == 3 and receipt["gate"] == "NEEDS_REVIEW"
    assert receipt["promotion"] == receipt["rollback"] == "PASS"
    assert receipt["parent_restored"] and receipt["lineage_count"] == 2
