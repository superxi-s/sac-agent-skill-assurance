import json
from pathlib import Path

from .models import SkillSnapshot
from .scope import files
from .validator import package_hash, validate_package


def snapshot(root: Path) -> SkillSnapshot:
    """读取已验证的 Champion 资产；不写入业务或注册表。"""
    validate_package(root)
    assets = files(root)
    manifest = json.loads(assets["manifest.json"])
    return SkillSnapshot(skill_name=manifest["name"], version=manifest["version"],
        package_hash=package_hash(root), skill_content=assets["SKILL.md"].decode("utf-8"),
        prompt_content=assets["prompt.md"].decode("utf-8"),
        reference_content=tuple((name, data.decode("utf-8")) for name, data in assets.items()
                                if name.startswith("references/")))
