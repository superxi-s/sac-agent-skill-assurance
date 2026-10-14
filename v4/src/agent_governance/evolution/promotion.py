from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..fingerprint import fingerprint
from ..models import ActionRequest, AuthoritySnapshot
from .evaluator import report_hash
from .lineage import atomic_json, read_json, registry_lock, safe_directory
from .models import EvolutionEvaluationReport, MutationScope, SkillCandidate, SkillLineageRecord
from .quality_gate import QualityConfig, decide
from .validator import package_hash, validate_candidate, validate_package


class SkillPromotionAdapter:
    """独立的本地 Skill registry；不写 V3 registry 或业务 Backend。

    evaluator 必须由维护者注入可信评测端，不接受请求中的自报成绩。
    本地文件 ACL、认证主体与审批持久化由部署方负责，不能运行不可信 Python 生成器。
    """

    def __init__(self, root: Path, *, owner_id: str, tenant_id: str,
                 candidates: dict[str, tuple[SkillCandidate, Path]],
                 evaluator: Callable[[SkillCandidate], EvolutionEvaluationReport],
                 config: QualityConfig = QualityConfig(), ttl_seconds: int = 300):
        if ttl_seconds <= 0:
            raise ValueError("审批窗口必须为正数")
        safe_directory(root)
        self.root = root
        self.owner_id, self.tenant_id = owner_id, tenant_id
        self.candidates = dict(candidates)
        self.evaluator, self.config = evaluator, config
        self.valid_until = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    @property
    def registry_path(self) -> Path:
        return self.root / "registry.json"

    def bootstrap(self, champion: Path) -> None:
        """仅维护者一次性初始化；不是候选生成接口。"""
        validate_package(champion)
        identity = package_hash(champion)
        with registry_lock(self.root):
            if self.registry_path.exists():
                raise ValueError("REGISTRY_ALREADY_INITIALIZED")
            directory = self.root / "versions" / identity
            directory.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(champion, directory)
            if package_hash(directory) != identity:
                raise ValueError("BOOTSTRAP_INTEGRITY_FAILED")
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            atomic_json(self.registry_path, {
                "revision": 0, "champion": identity, "previous": None,
                "versions": {identity: {"version": manifest["version"], "path": "versions/" + identity}},
                "lineage": [], "receipts": [],
            })

    def state(self) -> dict:
        value = read_json(self.registry_path)
        if set(value) != {"revision", "champion", "previous", "versions", "lineage", "receipts"}:
            raise ValueError("REGISTRY_SCHEMA_INVALID")
        if value["champion"] not in value["versions"]:
            raise ValueError("CHAMPION_NOT_FOUND")
        for identity, entry in value["versions"].items():
            if not re.fullmatch(r"[0-9a-f]{64}", identity) or entry["path"] != "versions/" + identity:
                raise ValueError("VERSION_PATH_INVALID")
            directory = self.root / entry["path"]
            validate_package(directory)
            if package_hash(directory) != identity:
                raise ValueError("VERSION_INTEGRITY_FAILED")
            if json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["version"] != entry["version"]:
                raise ValueError("VERSION_MANIFEST_MISMATCH")
        return value

    def _inspect(self, request: ActionRequest, state: dict) -> tuple[dict, bool]:
        if request.resource_type != "skill_candidate":
            raise ValueError("RESOURCE_TYPE_INVALID")
        if request.action == "promote_skill_candidate":
            if set(request.payload) != {"candidate_hash", "report_hash", "expected_champion"}:
                raise ValueError("PROMOTION_PAYLOAD_INVALID")
            candidate, directory = self.candidates[request.resource_id]
            changed = validate_candidate(self.root / state["versions"][state["champion"]]["path"],
                                         directory, candidate.parent_hash, MutationScope())
            if package_hash(directory) != candidate.candidate_hash or changed != candidate.changed_files:
                raise ValueError("CANDIDATE_DRIFT")
            report = self.evaluator(candidate)
            gate = decide(candidate, report, static_valid=True, config=self.config)
            expected = {"candidate_hash": candidate.candidate_hash, "report_hash": report_hash(report),
                        "expected_champion": state["champion"]}
            if request.payload != expected:
                raise ValueError("PROMOTION_BINDING_MISMATCH")
            return {**expected, "quality_config": self.config.model_dump(mode="json")}, gate.decision == "NEEDS_REVIEW"
        if request.action == "rollback_skill_version":
            if set(request.payload) != {"target_hash", "expected_champion"}:
                raise ValueError("ROLLBACK_PAYLOAD_INVALID")
            if request.resource_id != request.payload["target_hash"]:
                raise ValueError("ROLLBACK_RESOURCE_MISMATCH")
            if request.payload != {"target_hash": state["previous"], "expected_champion": state["champion"]}:
                raise ValueError("ROLLBACK_NOT_LAST_KNOWN_GOOD")
            if state["previous"] not in state["versions"]:
                raise ValueError("ROLLBACK_TARGET_MISSING")
            return dict(request.payload), True
        raise ValueError("ACTION_NOT_ALLOWED")

    def snapshot(self, request: ActionRequest) -> AuthoritySnapshot:
        state = self.state()
        facts, eligible = self._inspect(request, state)
        return AuthoritySnapshot(resource_type=request.resource_type, resource_id=request.resource_id,
            owner_id=self.owner_id, tenant_id=self.tenant_id, version=str(state["revision"]),
            status="PENDING_APPROVAL", validator_passed=eligible, valid_until=self.valid_until,
            facts={**facts, "registry_hash": fingerprint(state)})

    def assess(self, request: ActionRequest, authority: AuthoritySnapshot):
        return "REVIEW", ("EXPLICIT_HUMAN_APPROVAL_REQUIRED",)

    def execute(self, request: ActionRequest, expected: AuthoritySnapshot) -> str:
        with registry_lock(self.root):
            if self.snapshot(request) != expected:
                raise ValueError("REGISTRY_CAS_CONFLICT")
            state = self.state()
            self._inspect(request, state)
            parent = state["champion"]
            generation = state["revision"] + 1
            if request.action == "promote_skill_candidate":
                candidate, source = self.candidates[request.resource_id]
                report = self.evaluator(candidate)
                # 再绑定内容；不能依赖审批时的自报状态。
                if report_hash(report) != request.payload["report_hash"]:
                    raise ValueError("REPORT_DRIFT")
                current = state["versions"][parent]["version"]
                match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-dev)?", current)
                if not match:
                    raise ValueError("VERSION_INVALID")
                major, minor, patch = map(int, match.groups())
                used = {entry["version"] for entry in state["versions"].values()}
                version = f"{major}.{minor}.{patch + 1}"
                while version in used:
                    patch += 1
                    version = f"{major}.{minor}.{patch + 1}"
                stage = self.root / "staging" / candidate.candidate_id
                safe_directory(stage.parent)
                if stage.exists():
                    raise ValueError("STAGING_REQUIRES_RECONCILIATION")
                shutil.copytree(source, stage)
                if package_hash(stage) != candidate.candidate_hash:
                    raise ValueError("COPY_INTEGRITY_FAILED")
                manifest_path = stage / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["version"] = version
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
                                         encoding="utf-8", newline="\n")
                validate_package(stage)
                promoted = package_hash(stage)
                directory = self.root / "versions" / promoted
                if directory.exists():
                    raise ValueError("VERSION_DIRECTORY_EXISTS")
                # 发布前落盘所有新资产；registry 指针是最后的原子提交点。
                for file in stage.rglob("*"):
                    if file.is_file():
                        with file.open("r+b") as stream:
                            os.fsync(stream.fileno())
                stage.rename(directory)
                state["versions"][promoted] = {"version": version, "path": "versions/" + promoted}
                lineage = SkillLineageRecord(candidate_id=candidate.candidate_id, parent_hash=parent,
                    generation=generation, source_experiences=candidate.source_experiences,
                    candidate_hash=candidate.candidate_hash, report_hash=request.payload["report_hash"],
                    decision="PROMOTED", promoted_version=version, promoted_hash=promoted)
                state["previous"] = parent
            else:
                promoted = request.payload["target_hash"]
                lineage = SkillLineageRecord(candidate_id=fingerprint(request.resource_id),
                    parent_hash=parent, generation=generation, source_experiences=(),
                    candidate_hash=promoted, report_hash=fingerprint(request.payload),
                    decision="ROLLED_BACK", rollback_target=promoted)
                # 回滚不自动允许 redo；下一个正常晋级再设置 last-known-good。
                state["previous"] = None
            state["champion"], state["revision"] = promoted, generation
            receipt = fingerprint({"trace_id": request.trace_id, "generation": generation,
                                   "old": parent, "new": promoted, "action": request.action})
            state["receipts"].append(receipt)
            state["lineage"].append(lineage.model_dump(mode="json"))
            atomic_json(self.registry_path, state)
            return receipt
