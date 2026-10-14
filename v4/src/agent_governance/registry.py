import hashlib
import json
import os
from pathlib import Path


def package_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        if file.is_file():
            digest.update(file.relative_to(path).as_posix().encode() + b"\0")
            digest.update(file.read_bytes().replace(b"\r\n", b"\n"))
            digest.update(b"\0")
    return digest.hexdigest()


def verify_v3_registry(root: Path | None = None) -> dict[str, str]:
    root = root or Path(os.environ.get("AGENT_GOVERNANCE_SKILLS_ROOT", Path(__file__).resolve().parents[2] / "skills"))
    registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    hashes = {}
    for name in ("action-risk-gate", "action-review"):
        entry = registry["skills"][name]["versions"]["3.0.1"]
        if entry.get("lifecycle") not in {"ACTIVE", "ROLLBACK"}:
            raise ValueError("V3_PACKAGE_NOT_LOADABLE")
        path = (root / entry["path"]).resolve()
        if root.resolve() not in path.parents:
            raise ValueError("V3_PACKAGE_PATH_INVALID")
        actual = package_hash(path)
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if actual != entry["sha256"] or manifest["name"] != name or manifest["version"] != "3.0.1":
            raise ValueError("V3_PACKAGE_INTEGRITY_FAILED")
        hashes[name] = actual
    return hashes
