import hashlib
import json
import re
from pathlib import Path

import yaml

from .models import MutationScope
from .scope import allowed, files


def package_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for name, content in files(root).items():
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def validate_content(name: str, data: bytes, scope: MutationScope) -> None:
    if len(data) > scope.max_file_bytes:
        raise ValueError("文件超出大小限制")
    text = data.decode("utf-8")
    if re.search(r"(?i)(sk-[a-z0-9]{16,}|AKIA[A-Z0-9]{16}|-----BEGIN.*PRIVATE KEY|[A-Z]:[\\/]|/mnt/data|/home/|/Users/|/tmp/)", text):
        raise ValueError("禁止密钥或开发者绝对路径")
    if name == "manifest.json":
        manifest = json.loads(text)
        if (set(manifest) != {"name", "version", "read_only", "permissions"} or
                not isinstance(manifest["name"], str) or not isinstance(manifest["version"], str) or
                manifest["read_only"] is not True or manifest["permissions"] != ["read"]):
            raise ValueError("manifest 必须声明严格只读契约")
    if name == "SKILL.md":
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise ValueError("SKILL 缺少 frontmatter")
        header = yaml.safe_load(text.split("---", 2)[1])
        if not isinstance(header, dict) or set(header) != {"name", "description"}:
            raise ValueError("SKILL frontmatter 无效")
        if not all(isinstance(value, str) and value for value in header.values()):
            raise ValueError("SKILL frontmatter 必须为非空字符串")
    if name == "workflow.yaml":
        config = yaml.safe_load(text)
        if not isinstance(config, dict) or set(config) != {"mode", "steps"} or config["mode"] != "read_only":
            raise ValueError("工作流必须为只读说明")
        safe_steps = {"summarize_constraints", "summarize_validator", "explain_risk", "cite_evidence"}
        if not isinstance(config["steps"], list) or not config["steps"] or any(step not in safe_steps for step in config["steps"]):
            raise ValueError("工作流不能引入可执行步骤或间接写入")


def validate_package(root: Path, scope: MutationScope = MutationScope()) -> None:
    assets = files(root)
    if not {"SKILL.md", "prompt.md", "manifest.json", "workflow.yaml"} <= assets.keys():
        raise ValueError("候选资产不完整")
    if sum(map(len, assets.values())) > scope.max_package_bytes:
        raise ValueError("包超出大小限制")
    for name, data in assets.items():
        # scope 限制补丁可修改表面，不删除完整包中未改变的合法资产。
        # 包内文件仍受固定白名单、只读内容、大小和路径检查约束。
        if name != "manifest.json" and not allowed(name, MutationScope()):
            raise ValueError("禁止候选文件：" + name)
        validate_content(name, data, scope)


def validate_candidate(champion: Path, candidate: Path, parent_hash: str, scope: MutationScope) -> tuple[str, ...]:
    validate_package(champion, scope)
    validate_package(candidate, scope)
    if package_hash(champion) != parent_hash:
        raise ValueError("Champion 哈希漂移")
    before, after = files(champion), files(candidate)
    changed = tuple(sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name)))
    if not changed or any(not allowed(name, scope) for name in changed):
        raise ValueError("空补丁或保护表面变更")
    return changed
