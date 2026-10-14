"""校验公开入口标准及两套内部冻结注册表，不重算 registry。"""

from pathlib import Path
import re
import yaml
from agent_governance_portfolio import verify

root = Path(__file__).resolve().parents[1]
entries = list((root / "skill_packs").glob("*/SKILL.md"))
assert len(entries) == 3
for p in entries:
    content = p.read_text(encoding="utf-8")
    assert content.startswith("---\n"), p
    meta = yaml.safe_load(content.split("---", 2)[1])
    name, description = meta["name"], meta["description"]
    assert name == p.parent.name and len(name) <= 64
    assert re.fullmatch("[a-z0-9]+(?:-[a-z0-9]+)*", name)
    assert 0 < len(description) <= 1024 and "当" in description
    assert set(meta) <= {
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
        "allowed-tools",
    }
    assert (p.parent / "references/frozen_skill.md").is_file()
print({"SKILL_ENTRIES": len(entries), **verify()})
