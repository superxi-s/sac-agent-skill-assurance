"""SAC 候选计划的确定性风险判断。"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any


HARD_REASON_CODES = {
    "SOC_MIN_VIOLATION",
    "SOC_MAX_VIOLATION",
    "CHARGE_POWER_LIMIT",
    "DISCHARGE_POWER_LIMIT",
    "DISCHARGE_IN_NO_DISCHARGE_WINDOW",
    "RESERVE_SOC_VIOLATION",
    "TARGET_SOC_NOT_REACHED",
    "INSUFFICIENT_CHARGING_TIME",
    "ENERGY_BALANCE_VIOLATION",
    "SOC_CONTINUITY_VIOLATION",
}


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _finding(
    code: str,
    category: str,
    severity: str,
    message: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"code": code, "category": category, "severity": severity, "message": message, "evidence": evidence or {}}


def _expected_time(index: int) -> str:
    minutes = index * 15
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _finite_numbers(value: Any, path: str = "$") -> list[str]:
    bad: list[str] = []
    if isinstance(value, bool) or value is None:
        return bad
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            bad.append(path)
        return bad
    if isinstance(value, dict):
        for key, item in value.items():
            bad.extend(_finite_numbers(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            bad.extend(_finite_numbers(item, f"{path}[{index}]"))
    return bad


def review(payload: dict[str, Any], *, skill_name: str, skill_version: str, skill_hash: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    result = payload.get("replan_result") or {}
    policy = result.get("policy_result")
    candidate = result.get("candidate_plan")
    validation = result.get("validation_result")
    comparison = result.get("comparison")
    reviewed_at = payload.get("reviewed_at", "")

    missing = [name for name, value in (("policy_result", policy), ("candidate_plan", candidate), ("validation_result", validation), ("comparison", comparison)) if not isinstance(value, dict)]
    if missing:
        findings.append(_finding("REQUIRED_FACTS_MISSING", "GOVERNANCE", "BLOCKER", "候选审核所需的 Backend 事实不完整。", {"fields": missing}))
        policy = policy if isinstance(policy, dict) else {}
        candidate = candidate if isinstance(candidate, dict) else {}
        validation = validation if isinstance(validation, dict) else {}
        comparison = comparison if isinstance(comparison, dict) else {}

    bad_numbers = _finite_numbers(payload)
    if bad_numbers:
        findings.append(_finding("NON_FINITE_VALUE", "GOVERNANCE", "BLOCKER", "审核事实包含非有限数值。", {"paths": bad_numbers[:20]}))

    if policy.get("allowed") is not True or policy.get("status") != "ALLOWED":
        findings.append(_finding("POLICY_NOT_ALLOWED", "GOVERNANCE", "BLOCKER", "Backend policy 未允许该候选进入审批。", {"allowed": policy.get("allowed"), "status": policy.get("status")}))

    reason_codes = validation.get("reason_codes") or []
    if not isinstance(reason_codes, list):
        reason_codes = []
        findings.append(_finding("VALIDATION_REASON_INVALID", "FEASIBILITY", "BLOCKER", "Validation reason_codes 格式无效。"))
    normalized_codes = {str(code) for code in reason_codes}
    hard_codes = sorted(normalized_codes & HARD_REASON_CODES)
    soft_codes = sorted(code for code in normalized_codes if code.startswith("SOFT_"))
    unknown_codes = sorted(normalized_codes - HARD_REASON_CODES - set(soft_codes))
    if validation.get("feasible") is not True or validation.get("status") != "PASS" or hard_codes:
        findings.append(_finding("VALIDATION_NOT_PASS", "FEASIBILITY", "BLOCKER", "Backend 可行性校验未通过。", {"feasible": validation.get("feasible"), "status": validation.get("status"), "reason_codes": hard_codes}))
    if unknown_codes:
        findings.append(_finding("UNKNOWN_VALIDATION_REASON", "FEASIBILITY", "BLOCKER", "出现当前 Skill 版本无法识别的校验原因码。", {"reason_codes": unknown_codes}))
    if soft_codes:
        findings.append(_finding("SOFT_CONSTRAINT_VIOLATION", "FEASIBILITY", "WARNING", "候选存在软约束违例，需要用户知悉。", {"reason_codes": soft_codes}))

    candidate_id = str(candidate.get("plan_id") or "")
    parent_id = str(candidate.get("parent_plan_id") or "")
    root_id = str(candidate.get("root_sac_plan_id") or "")
    if candidate.get("status") != "PENDING_APPROVAL" or not isinstance(candidate.get("version"), int) or isinstance(candidate.get("version"), bool) or candidate.get("version", 0) < 1:
        findings.append(_finding("CANDIDATE_STATE_INVALID", "GOVERNANCE", "BLOCKER", "候选状态或计划版本不允许审批。", {"status": candidate.get("status"), "version": candidate.get("version")}))

    expected_user = payload.get("expected_user_id")
    expected_date = payload.get("expected_operating_date")
    authoritative_active = payload.get("authoritative_active_plan_id")
    identities = {
        "candidate_user_id": candidate.get("user_id"),
        "candidate_operating_date": candidate.get("operating_date"),
        "candidate_parent_plan_id": parent_id,
        "result_active_plan_id": result.get("current_active_plan_id"),
        "authoritative_active_plan_id": authoritative_active,
        "comparison_parent_plan_id": comparison.get("parent_plan_id"),
        "comparison_revised_plan_id": comparison.get("revised_plan_id"),
        "comparison_root_sac_plan_id": comparison.get("root_sac_plan_id"),
    }
    identity_ok = (
        candidate_id
        and parent_id
        and root_id
        and expected_user
        and expected_date
        and authoritative_active
        and candidate.get("user_id") == expected_user
        and candidate.get("operating_date") == expected_date
        and parent_id == result.get("current_active_plan_id") == authoritative_active == comparison.get("parent_plan_id")
        and candidate_id == comparison.get("revised_plan_id")
        and root_id == comparison.get("root_sac_plan_id")
    )
    if not identity_ok:
        findings.append(_finding("PLAN_IDENTITY_MISMATCH", "GOVERNANCE", "BLOCKER", "候选 scope、血缘或 Current ACTIVE 身份不一致。", identities))

    candidate_fcs = candidate.get("forecast_snapshot_id")
    candidate_rcs = candidate.get("runtime_constraint_snapshot_id")
    if not candidate_fcs or not candidate_rcs or candidate_fcs != result.get("forecast_snapshot_id") or candidate_rcs != result.get("runtime_constraint_snapshot_id"):
        findings.append(_finding("SNAPSHOT_ID_MISMATCH", "GOVERNANCE", "BLOCKER", "候选使用的预测或运行约束快照标识缺失或不一致。", {"forecast_snapshot_id": candidate_fcs, "runtime_constraint_snapshot_id": candidate_rcs}))

    valid_until = candidate.get("valid_until")
    try:
        expired = not isinstance(valid_until, str) or _parse_time(reviewed_at) >= _parse_time(valid_until)
    except (TypeError, ValueError):
        expired = True
    if expired:
        findings.append(_finding("CANDIDATE_EXPIRED", "GOVERNANCE", "BLOCKER", "候选有效期缺失、无效或已过期。", {"valid_until": valid_until}))

    schedule = candidate.get("schedule")
    schedule_ok = isinstance(schedule, list) and len(schedule) == 96
    if schedule_ok:
        by_index: dict[int, dict[str, Any]] = {}
        for point in schedule:
            if not isinstance(point, dict) or isinstance(point.get("index"), bool) or not isinstance(point.get("index"), int):
                schedule_ok = False
                break
            index = point["index"]
            if index in by_index:
                schedule_ok = False
                break
            by_index[index] = point
        schedule_ok = schedule_ok and set(by_index) == set(range(96)) and all(by_index[index].get("time") == _expected_time(index) for index in range(96))
    if not schedule_ok:
        findings.append(_finding("SCHEDULE_SHAPE_INVALID", "FEASIBILITY", "BLOCKER", "候选必须包含完整且唯一的 96 个 15 分钟调度点。"))

    parent_metrics = comparison.get("parent_metrics") if isinstance(comparison.get("parent_metrics"), dict) else {}
    revised_metrics = comparison.get("revised_metrics") if isinstance(comparison.get("revised_metrics"), dict) else {}
    delta = comparison.get("delta") if isinstance(comparison.get("delta"), dict) else {}
    metric_keys = ("daily_cost_eur", "saving_eur", "total_charge_kwh", "total_discharge_kwh")
    if any(not isinstance(metrics.get(key), (int, float)) or isinstance(metrics.get(key), bool) for metrics in (parent_metrics, revised_metrics) for key in metric_keys):
        findings.append(_finding("COMPARISON_METRICS_MISSING", "GOVERNANCE", "BLOCKER", "风险计算所需的父计划或候选指标缺失。"))
    else:
        parent_cost = float(parent_metrics["daily_cost_eur"])
        revised_cost = float(revised_metrics["daily_cost_eur"])
        computed_cost_delta = revised_cost - parent_cost
        reported_cost_delta = delta.get("daily_cost_eur")
        if not isinstance(reported_cost_delta, (int, float)) or isinstance(reported_cost_delta, bool) or not math.isclose(float(reported_cost_delta), computed_cost_delta, rel_tol=1e-6, abs_tol=1e-6):
            findings.append(_finding("COMPARISON_DELTA_MISMATCH", "GOVERNANCE", "BLOCKER", "Backend comparison 的成本差值与父/候选指标不一致。"))

        for metric_key in ("saving_eur", "total_charge_kwh", "total_discharge_kwh"):
            reported_delta = delta.get(metric_key)
            computed_delta = float(revised_metrics[metric_key]) - float(parent_metrics[metric_key])
            if not isinstance(reported_delta, (int, float)) or isinstance(reported_delta, bool) or not math.isclose(float(reported_delta), computed_delta, rel_tol=1e-6, abs_tol=1e-6):
                findings.append(_finding(
                    "COMPARISON_DELTA_MISMATCH",
                    "GOVERNANCE",
                    "BLOCKER",
                    "Backend comparison 的指标差值与父/候选指标不一致。",
                    {"metric": metric_key},
                ))
        cost_threshold = max(0.10, abs(parent_cost) * 0.05)
        if computed_cost_delta >= cost_threshold:
            findings.append(_finding("DAILY_COST_INCREASE", "ECONOMIC", "WARNING", "候选日成本增幅达到风险知悉阈值。", {"delta_eur": round(computed_cost_delta, 6), "threshold_eur": round(cost_threshold, 6)}))

        revised_saving = float(revised_metrics["saving_eur"])
        if revised_saving < 0:
            findings.append(_finding("NEGATIVE_SAVING", "ECONOMIC", "WARNING", "候选相对基线的节省金额为负。", {"saving_eur": revised_saving}))

        parent_throughput = float(parent_metrics["total_charge_kwh"]) + float(parent_metrics["total_discharge_kwh"])
        revised_throughput = float(revised_metrics["total_charge_kwh"]) + float(revised_metrics["total_discharge_kwh"])
        throughput_delta = revised_throughput - parent_throughput
        throughput_threshold = max(1.0, abs(parent_throughput) * 0.20)
        if throughput_delta >= throughput_threshold:
            findings.append(_finding("BATTERY_THROUGHPUT_INCREASE", "OPERATIONAL", "WARNING", "候选电池吞吐增幅达到风险知悉阈值。", {"delta_kwh": round(throughput_delta, 6), "threshold_kwh": round(throughput_threshold, 6)}))

    changed_windows = delta.get("changed_windows")
    if not isinstance(changed_windows, list) or any(not isinstance(item, dict) or isinstance(item.get("interval_count"), bool) or not isinstance(item.get("interval_count"), int) or item.get("interval_count", 0) <= 0 for item in (changed_windows or [])):
        findings.append(_finding("CHANGED_WINDOWS_INVALID", "GOVERNANCE", "BLOCKER", "changed_windows 结构无效。"))
    else:
        changed_intervals = sum(item["interval_count"] for item in changed_windows)
        if changed_intervals >= 16:
            findings.append(_finding("BROAD_SCHEDULE_CHANGE", "OPERATIONAL", "WARNING", "候选变更覆盖至少四小时的调度时段。", {"changed_intervals": changed_intervals, "threshold_intervals": 16}))

    candidate_fp = _fingerprint(candidate) if candidate else "unavailable"
    input_fp = _fingerprint(payload)
    has_blocker = any(item["severity"] == "BLOCKER" for item in findings)
    has_warning = any(item["severity"] == "WARNING" for item in findings)
    decision = "BLOCK" if has_blocker else "REVIEW" if has_warning else "PASS"
    review_seed = f"{skill_name}|{skill_version}|{skill_hash}|{input_fp}"
    review_id = hashlib.sha256(review_seed.encode("utf-8")).hexdigest()[:24]
    return {
        "schema_version": "risk-review-v1",
        "review_id": review_id,
        "input_fingerprint": input_fp,
        "candidate_fingerprint": candidate_fp,
        "skill_name": skill_name,
        "skill_version": skill_version,
        "skill_hash": skill_hash,
        "candidate_plan_id": candidate_id,
        "parent_plan_id": parent_id,
        "decision": decision,
        "requires_second_confirmation": decision == "REVIEW",
        "findings": findings,
        "reviewed_at": reviewed_at,
    }
