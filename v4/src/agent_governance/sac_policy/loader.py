"""加载固定哈希的 Skill；加载或执行失败时默认阻断。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from pydantic import ValidationError

from .risk_models import RiskFinding, RiskReviewInput, RiskReviewResult, candidate_fingerprint


SKILL_NAME = "dispatch-plan-risk-review"
# 采用明确的 V1.1 风险策略版本，不接受隐式 latest。
DEFAULT_VERSION = "1.1.0"
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class SkillLoadError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        item for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    )
    if not files:
        raise SkillLoadError("Skill 包为空")
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        # 统一换行，保证跨平台哈希稳定。
        data = item.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


class LoadedSkill:
    def __init__(self, *, name: str, version: str, package_hash: str, entrypoint: Callable[..., Any]) -> None:
        self.name = name
        self.version = version
        self.package_hash = package_hash
        self.entrypoint = entrypoint


class SkillRegistry:
    def __init__(self, registry_path: Path | None = None) -> None:
        self.registry_path = registry_path or Path(__file__).with_name("registry.json")

    def load(self, name: str, version: str) -> LoadedSkill:
        if name != SKILL_NAME:
            raise SkillLoadError("未知 Skill")
        if version == "latest" or not _SEMVER.fullmatch(version):
            raise SkillLoadError("Skill 版本必须是明确的 SemVer")
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
            skill = registry["skills"][name]
            entry = skill["versions"][version]
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise SkillLoadError("Skill 版本未注册") from exc
        lifecycle = entry.get("lifecycle")
        if lifecycle not in {"ACTIVE", "ROLLBACK"}:
            raise SkillLoadError("Skill 生命周期状态不允许加载")
        package_path = (self.registry_path.parent / entry.get("path", "")).resolve()
        root = self.registry_path.parent.resolve()
        if root not in package_path.parents or not package_path.is_dir():
            raise SkillLoadError("Skill 包路径无效")
        actual_hash = directory_sha256(package_path)
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or actual_hash != expected_hash:
            raise SkillLoadError("Skill 包哈希不一致")
        manifest = self._manifest(package_path, name, version)
        module, function_name = manifest["entrypoint"].split(":", 1)
        module_path = (package_path / module).resolve()
        if package_path not in module_path.parents or not module_path.is_file() or module_path.suffix != ".py":
            raise SkillLoadError("Skill 入口无效")
        loaded_module = self._load_module(module_path, name, version, actual_hash)
        entrypoint = getattr(loaded_module, function_name, None)
        if not callable(entrypoint):
            raise SkillLoadError("Skill 入口不可调用")
        return LoadedSkill(name=name, version=version, package_hash=actual_hash, entrypoint=entrypoint)

    @staticmethod
    def _manifest(package_path: Path, name: str, version: str) -> dict[str, Any]:
        try:
            manifest = json.loads((package_path / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise SkillLoadError("Skill 清单无效") from exc
        required = {
            "schema_version": "skill-package-v1",
            "name": name,
            "version": version,
            "input_schema_version": "risk-review-input-v1",
            "output_schema_version": "risk-review-v1",
        }
        if any(manifest.get(key) != value for key, value in required.items()):
            raise SkillLoadError("Skill 清单与契约不一致")
        entrypoint = manifest.get("entrypoint")
        if not isinstance(entrypoint, str) or entrypoint.count(":") != 1:
            raise SkillLoadError("skill manifest entrypoint is invalid")
        return manifest

    @staticmethod
    def _load_module(path: Path, name: str, version: str, package_hash: str) -> ModuleType:
        module_name = f"_agent_skill_{name.replace('-', '_')}_{version.replace('.', '_')}_{package_hash[:12]}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise SkillLoadError("Skill 模块无法加载")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise SkillLoadError("Skill 模块执行失败") from exc
        return module


class DispatchRiskSkillRuntime:
    """固定版本的策略入口；所有故障返回结构化 BLOCK。"""

    def __init__(self, *, version: str | None = None, registry: SkillRegistry | None = None, recorder=None) -> None:
        self.version = version or os.environ.get("DISPATCH_RISK_SKILL_VERSION", DEFAULT_VERSION).strip()
        self.registry = registry or SkillRegistry()
        self.recorder = recorder

    def review(
        self,
        *,
        replan_result,
        authoritative_active_plan_id: str,
        expected_user_id: str,
        expected_operating_date: str,
        reviewed_at: str | None = None,
        trace_id: str = "",
    ) -> RiskReviewResult:
        timestamp = reviewed_at or utc_now()
        input_value = None
        try:
            input_value = RiskReviewInput(
                replan_result=replan_result,
                authoritative_active_plan_id=authoritative_active_plan_id,
                expected_user_id=expected_user_id,
                expected_operating_date=expected_operating_date,
                reviewed_at=timestamp,
            )
            loaded = self.registry.load(SKILL_NAME, self.version)
            raw = loaded.entrypoint(
                input_value.model_dump(mode="json"),
                skill_name=loaded.name,
                skill_version=loaded.version,
                skill_hash=loaded.package_hash,
            )
            result = RiskReviewResult.model_validate(raw)
        except (SkillLoadError, ValidationError, ValueError, TypeError, KeyError, OSError):
            result = self._fail_closed(input_value, timestamp)
        except Exception:
            result = self._fail_closed(input_value, timestamp)
        self._trace(result, trace_id)
        return result

    def verify_candidate(self, session, candidate: Any) -> bool:
        if not session.risk_candidate_fingerprint or not session.risk_skill_version or not session.risk_skill_hash:
            return False
        try:
            loaded = self.registry.load(SKILL_NAME, session.risk_skill_version)
            return loaded.package_hash == session.risk_skill_hash and candidate_fingerprint(candidate) == session.risk_candidate_fingerprint
        except Exception:
            return False

    def _fail_closed(self, input_value: RiskReviewInput | None, timestamp: str) -> RiskReviewResult:
        candidate = input_value.replan_result.candidate_plan if input_value is not None else None
        candidate_id = candidate.plan_id if candidate is not None else ""
        parent_id = (candidate.parent_plan_id or "") if candidate is not None else ""
        try:
            fingerprint = candidate_fingerprint(candidate) if candidate is not None else "unavailable"
        except Exception:
            fingerprint = "unavailable"
        seed = f"{SKILL_NAME}|{self.version}|{candidate_id}|{timestamp}|runtime-unavailable"
        review_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
        return RiskReviewResult(
            review_id=review_id,
            input_fingerprint="unavailable",
            candidate_fingerprint=fingerprint,
            skill_name=SKILL_NAME,
            skill_version=self.version or "unavailable",
            skill_hash="unavailable",
            candidate_plan_id=candidate_id,
            parent_plan_id=parent_id,
            decision="BLOCK",
            requires_second_confirmation=False,
            findings=[RiskFinding(
                code="SKILL_RUNTIME_UNAVAILABLE",
                category="RUNTIME",
                severity="BLOCKER",
                message="风险审核 Skill 无法安全加载或执行。",
                evidence={},
            )],
            reviewed_at=timestamp,
        )

    def _trace(self, result: RiskReviewResult, trace_id: str) -> None:
        if self.recorder:
            self.recorder.record(
                "SKILL",
                "dispatch_plan_risk_review",
                trace_id=trace_id,
                request_id=trace_id,
                correlation_id=trace_id,
                status="BLOCKED" if result.decision == "BLOCK" else "OK",
                failure_code="SKILL_RUNTIME_UNAVAILABLE" if any(f.code == "SKILL_RUNTIME_UNAVAILABLE" for f in result.findings) else None,
                metadata={
                    "review_id": result.review_id,
                    "skill_name": result.skill_name,
                    "skill_version": result.skill_version,
                    "skill_hash": result.skill_hash,
                    "decision": result.decision,
                    "finding_codes": [finding.code for finding in result.findings],
                },
            )
