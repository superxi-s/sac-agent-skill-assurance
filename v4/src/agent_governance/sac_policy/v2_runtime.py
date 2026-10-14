from __future__ import annotations

import hashlib


import json


from datetime import datetime, timezone

from pathlib import Path

from typing import Any, Literal

from pydantic import BaseModel, Field

from .loader import SkillLoadError, candidate_fingerprint, directory_sha256

GateStage = Literal["PRE_APPROVAL", "PRE_ACTIVATION"]

GateDecision = Literal["PASS", "REVIEW", "BLOCK"]

RiskLevel = Literal["low", "medium", "high", "critical"]

class RiskFindingV2(BaseModel):
    rule_code: str
    severity: Literal["INFO", "WARNING", "BLOCKER"]
    source: str
    message: str
    observed: dict[str, Any] = Field(default_factory=dict)
    threshold: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

class GateResultV2(BaseModel):
    schema_version: Literal["dispatch-plan-risk-gate-v2"] = "dispatch-plan-risk-gate-v2"
    review_id: str
    skill_name: Literal["dispatch-plan-risk-gate"] = "dispatch-plan-risk-gate"
    skill_version: str
    skill_hash: str
    stage: GateStage
    decision: GateDecision
    risk: RiskLevel
    findings: list[RiskFindingV2] = Field(default_factory=list)
    candidate_plan_id: str = ""
    candidate_fingerprint: str = ""
    authority_snapshot: dict[str, Any] = Field(default_factory=dict)
    allowed_next_actions: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    policy_version: str = "v1.1-reused"
    policy_hash: str = ""
    trace_id: str = ""
    evaluated_at: str

class V2SkillRegistry:
    """加载明确版本的 SAC 策略包，不绕过完整性检查。"""

    def __init__(self, registry_path: Path | None = None) -> None:
        self.registry_path = registry_path or Path(__file__).with_name("registry.json")

    def load(self, name: str, version: str) -> tuple[dict[str, Any], Path, str]:
        if not name or not version or version == "latest":
            raise SkillLoadError("必须指定明确的 Skill 版本")
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            entry = data["skills"][name]["versions"][version]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SkillLoadError("Skill 版本未注册") from exc
        if entry.get("lifecycle") not in {"ACTIVE", "ROLLBACK"}:
            raise SkillLoadError("Skill 生命周期状态不允许加载")
        path = (self.registry_path.parent / str(entry.get("path") or "")).resolve()
        if self.registry_path.parent.resolve() not in path.parents or not path.is_dir():
            raise SkillLoadError("Skill 包路径无效")
        actual = directory_sha256(path)
        if actual != entry.get("sha256"):
            raise SkillLoadError("Skill 包哈希不一致")
        try:
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise SkillLoadError("Skill 清单无效") from exc
        if manifest.get("name") != name or manifest.get("version") != version or manifest.get("schema_version") != "skill-package-v1":
            raise SkillLoadError("Skill 清单与契约不一致")
        return manifest, path, actual

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _family(code: str) -> str:
    if code.startswith("VALIDATION") or code.startswith("UNKNOWN_VALIDATION"):
        return "VAL"
    if "EXPIRED" in code or "SNAPSHOT" in code:
        return "FRESH"
    if "IDENTITY" in code or "LINEAGE" in code:
        return "LINEAGE"
    if "SCHEDULE" in code:
        return "STRUCT"
    if "COST" in code or "SAVING" in code:
        return "ECON"
    if "THROUGHPUT" in code or "WINDOW" in code:
        return "OPS"
    return "INTEGRITY"

class DispatchRiskGateV2Runtime:
    name = "dispatch-plan-risk-gate"
    version = "2.0.0"

    def __init__(self, *, registry: V2SkillRegistry | None = None, legacy_runtime: Any | None = None, recorder: Any | None = None) -> None:
        self.registry = registry or V2SkillRegistry()
        self.legacy_runtime = legacy_runtime
        self.recorder = recorder

    def _loaded(self) -> tuple[dict[str, Any], Path, str]:
        return self.registry.load(self.name, self.version)

    def review(self, *, replan_result: Any, authoritative_active_plan_id: str, expected_user_id: str, expected_operating_date: str, reviewed_at: str | None = None, trace_id: str = "") -> GateResultV2:
        """审批前复用 V1.1 确定性策略语义。"""
        manifest, _path, package_hash = self._loaded()
        from .loader import DispatchRiskSkillRuntime
        legacy = self.legacy_runtime or DispatchRiskSkillRuntime(recorder=None)
        legacy_result = legacy.review(replan_result=replan_result, authoritative_active_plan_id=authoritative_active_plan_id, expected_user_id=expected_user_id, expected_operating_date=expected_operating_date, reviewed_at=reviewed_at, trace_id=trace_id)
        findings = [RiskFindingV2(rule_code=_family(item.code) + ":" + item.code, severity=item.severity, source="V1_1_POLICY", message=item.message, observed=dict(item.evidence)) for item in legacy_result.findings]
        decision = legacy_result.decision
        result = GateResultV2(review_id=hashlib.sha256(f"{package_hash}|{legacy_result.review_id}|PRE_APPROVAL".encode()).hexdigest()[:24], skill_version=self.version, skill_hash=package_hash, stage="PRE_APPROVAL", decision=decision, risk="critical" if decision == "BLOCK" else "medium" if decision == "REVIEW" else "low", findings=findings, candidate_plan_id=legacy_result.candidate_plan_id, candidate_fingerprint=legacy_result.candidate_fingerprint, authority_snapshot={"active_plan_id": authoritative_active_plan_id, "expected_user_id": expected_user_id, "operating_date": expected_operating_date}, allowed_next_actions=[] if decision == "BLOCK" else (["ACKNOWLEDGE", "CONFIRM"] if decision == "REVIEW" else ["CONFIRM"]), blocked_actions=["ACTIVATE"] if decision == "BLOCK" else [], policy_version=str(manifest.get("policy_version") or "v1.1-reused"), policy_hash=str(manifest.get("policy_hash") or package_hash), trace_id=trace_id, evaluated_at=reviewed_at or _now())
        self._trace(result)
        return result

    def preactivate(self, *, session: Any, candidate: Any, current_active_plan_id: str, trace_id: str = "") -> GateResultV2:
        """调用 Backend 前进行确定性复核。"""
        manifest, _path, package_hash = self._loaded()
        now = _now(); findings: list[RiskFindingV2] = []
        fp = candidate_fingerprint(candidate)
        c = candidate.model_dump(mode="json") if hasattr(candidate, "model_dump") else dict(candidate)
        if c.get("status") != "PENDING_APPROVAL":
            findings.append(RiskFindingV2(rule_code="LIFE:CANDIDATE_NOT_PENDING", severity="BLOCKER", source="BACKEND", message="候选不再处于待审批状态。", observed={"status": c.get("status")}))
        if c.get("parent_plan_id") != session.expected_active_plan_id or current_active_plan_id != session.expected_active_plan_id:
            findings.append(RiskFindingV2(rule_code="LINEAGE:ACTIVE_DRIFT", severity="BLOCKER", source="BACKEND", message="候选血缘或当前 ACTIVE 已漂移。", observed={"parent": c.get("parent_plan_id"), "expected": session.expected_active_plan_id, "current": current_active_plan_id}))
        if fp != session.risk_candidate_fingerprint:
            findings.append(RiskFindingV2(rule_code="INTEGRITY:FINGERPRINT_MISMATCH", severity="BLOCKER", source="GATE", message="候选指纹与审批记录不一致。"))
        if getattr(session, "risk_skill_hash", "") != package_hash:
            findings.append(RiskFindingV2(rule_code="VERSION:POLICY_HASH_DRIFT", severity="BLOCKER", source="GATE", message="已确认的 Gate 策略哈希不再匹配。"))
        decision: GateDecision = "BLOCK" if findings else "PASS"
        result = GateResultV2(review_id=hashlib.sha256(f"{package_hash}|{getattr(session, 'risk_review_id', '')}|PRE_ACTIVATION|{now}".encode()).hexdigest()[:24], skill_version=self.version, skill_hash=package_hash, stage="PRE_ACTIVATION", decision=decision, risk="critical" if findings else "low", findings=findings, candidate_plan_id=str(c.get("plan_id") or ""), candidate_fingerprint=fp, authority_snapshot={"active_plan_id": current_active_plan_id, "session_expected_active": session.expected_active_plan_id, "candidate_status": c.get("status")}, allowed_next_actions=["ACTIVATE"] if decision == "PASS" else [], blocked_actions=[] if decision == "PASS" else ["ACTIVATE"], policy_version=str(manifest.get("policy_version") or "v1.1-reused"), policy_hash=str(manifest.get("policy_hash") or package_hash), trace_id=trace_id, evaluated_at=now)
        self._trace(result)
        return result

    def verify_candidate(self, session: Any, candidate: Any) -> bool:
        try:
            _manifest, _path, package_hash = self._loaded()
            return bool(session.risk_candidate_fingerprint and session.risk_skill_hash == package_hash and candidate_fingerprint(candidate) == session.risk_candidate_fingerprint)
        except Exception:
            return False

    def _trace(self, result: GateResultV2) -> None:
        if self.recorder:
            self.recorder.record("SKILL", "dispatch_plan_risk_gate_v2", trace_id=result.trace_id, request_id=result.trace_id, correlation_id=result.trace_id, status="BLOCKED" if result.decision == "BLOCK" else "OK", metadata={"candidate_plan_id": result.candidate_plan_id, "stage": result.stage, "decision": result.decision, "policy_version": result.policy_version, "policy_hash": result.policy_hash, "finding_codes": [f.rule_code for f in result.findings]})
