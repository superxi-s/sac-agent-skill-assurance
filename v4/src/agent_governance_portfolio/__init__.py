"""公开发行资源定位；不修改任何治理决策。"""

import os
from importlib.resources import files


def configure_assets():
    """显式保留调用方配置，否则使用 wheel 内的冻结资源。"""
    root = files("agent_governance_assets").joinpath("data", "skills")
    os.environ.setdefault("AGENT_GOVERNANCE_SKILLS_ROOT", str(root))
    return os.environ["AGENT_GOVERNANCE_SKILLS_ROOT"]


def verify():
    import json
    from pathlib import Path
    from agent_governance.registry import verify_v3_registry
    from agent_governance.sac_policy.loader import directory_sha256
    import agent_governance.sac_policy.loader as loader

    configure_assets()
    verify_v3_registry()
    root = Path(loader.__file__).parent
    registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    for skill in registry["skills"].values():
        for entry in skill["versions"].values():
            if directory_sha256(root / entry["path"]) != entry["sha256"]:
                raise ValueError("LEGACY_REGISTRY_INTEGRITY_FAILED")
    return {"REGISTRY_V3": "PASS", "REGISTRY_LEGACY": "PASS"}
