from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata
import zipfile

from pydantic import Field
from .models import FrozenModel, Digest
from ..fingerprint import fingerprint


class ReviewFailureAttribution(FrozenModel):
    canonical_case_id: Digest
    source_ref: Digest
    target_skill: str = "review"
    failure_signature: str
    attribution_layer: str
    symptom: str
    expected_behavior: str
    observed_behavior: str
    root_cause: str
    review_skill_fixable: bool | None
    confidence: float = Field(ge=0, le=1)
    notes: tuple[str, ...] = ()
    partition: str


EXCLUDED_DIRECTORIES = {".git", "node_modules", "__pycache__", ".pytest_cache",
                        "corpus", "processed", "qdrant_database", "05_chunks", "06_indexes"}
EXTENSIONS = {".json", ".jsonl", ".md", ".log", ".txt", ".csv"}
SIGNAL = re.compile(r"eval|review|badcase|trajectory|trace|report|hitl|blind|failure|rca|regression|gold", re.I)


def discover(root: Path):
    """遍历全部历史路径，明确登记归档成员，不展开到公开目录。"""
    import os
    for folder, directories, names in os.walk(root):
        directories[:] = sorted(d for d in directories if d not in EXCLUDED_DIRECTORIES
                                and not d.startswith((".venv", "venv", ".")) and not d.endswith(".egg-info"))
        for name in sorted(names):
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            if name.startswith(".env") or not SIGNAL.search(relative):
                continue
            if path.suffix.lower() in EXTENSIONS:
                yield relative, path.read_bytes(), path
            elif path.suffix.lower() == ".zip":
                # 外层归档仍登记，成员分别清点，复制件不重复计独立案例。
                yield relative, None, path
                try:
                    with zipfile.ZipFile(path) as archive:
                        for item in sorted(archive.infolist(), key=lambda i: i.filename):
                            member = item.filename
                            if (not item.is_dir() and Path(member).suffix.lower() in EXTENSIONS
                                    and SIGNAL.search(relative + "/" + member)):
                                yield relative + "::" + member, archive.read(item), path
                except (OSError, zipfile.BadZipFile):
                    yield relative + "::ARCHIVE_READ_ERROR", b"", path


def case_identifier(row):
    for key in ("case_id", "CASE_ID", "test_case_id"):
        value = row.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    if isinstance(row.get("id"), (str, int)) and any(
        key in row for key in ("expected", "expected_intent", "query", "question", "PASS")
    ):
        return str(row["id"])
    return None


def extract_rows(value):
    if isinstance(value, list):
        for item in value:
            yield from extract_rows(item)
    elif isinstance(value, dict):
        if case_identifier(value) is not None:
            yield value
        else:
            for child in value.values():
                if isinstance(child, (dict, list)):
                    yield from extract_rows(child)


def parse_rows(name, raw):
    suffix = Path(name.split("::")[-1]).suffix.lower()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
    if suffix == ".jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif suffix == ".json":
        values = json.loads(text)
    elif suffix == ".csv":
        values = list(csv.DictReader(io.StringIO(text)))
    else:
        return [], text
    return list(extract_rows(values)), text


def family(name, row):
    lowered = name.lower()
    if "semantic_events" in row or "required_events" in row or "required_steps" in row or "trajectory" in lowered:
        return "trajectory:v1"
    if "TURN2_QUERY" in row or "USER_QUERY" in row or "TASK_DECISION" in row:
        return "review_e2e"
    if "EXPLANATION_TEXT" in row:
        return "review_llm"
    if "expected_skill" in row:
        return "skill_trigger"
    if "scenario" in row and "expected" in row:
        return "security"
    if "expected_tool" in row or "initial_state" in row or "actual_tools" in row:
        return "agent_task"
    if "RAW_EVIDENCE_COUNT" in row or "EXPECTED_RAG_TRIGGER" in row:
        return "evidence"
    if "expected_parse_status" in row:
        return "parser"
    if "expected_intent" in row or "primary_intent" in row:
        return "intent"
    # 对无法证明同族的案例保守隔离；不凭同一个短 ID 合并不同数据集。
    return "other:" + re.sub(r"(run\d+|merged|rerun|final|clean)", "", Path(name.split("::")[-1]).stem.lower())


def canonical_id(name, row):
    identifier = unicodedata.normalize("NFKC", case_identifier(row) or "").strip().casefold()
    return fingerprint({"family": family(name, row), "id": identifier})


def partition(name, row):
    split = str(row.get("split") or "").lower()
    if split in {"blind", "heldout", "test", "frozen_test"} or re.search(r"blind|held.out|frozen", name, re.I):
        return "audit_only"
    if split in {"calibration", "dev", "train"}:
        return "dev" if split == "calibration" else split
    return "unassigned"


def verdict(row):
    for key in ("PASS", "passed", "pass", "task_success"):
        if isinstance(row.get(key), bool):
            return row[key]
    if isinstance(row.get("trajectory_valid"), bool):
        return row["trajectory_valid"]
    if "actual_skill" in row and "expected_skill" in row:
        return row["actual_skill"] == row["expected_skill"]
    if "actual" in row and "expected" in row:
        return row["actual"] == row["expected"]
    return None


def review_signal(name, row=None, text=""):
    if row is None:
        return bool(re.search(r"review|审查|审阅|候选方案|风险解释|candidate_review", name + "\n" + text, re.I))
    values = [row.get(k, "") for k in ("category", "CATEGORY", "task_decision", "TASK_DECISION",
                                       "skill", "expected_skill", "required_milestones")]
    response = row.get("response") or {}
    result = response.get("result") if isinstance(response, dict) else {}
    full = result.get("full_review") if isinstance(result, dict) else {}
    return bool(full or row.get("EXPLANATION_TEXT") or "review_skill" in row.get("semantic_events", [])
                or re.search(r"review|审查|风险解释", " ".join(map(str, values)), re.I)
                or re.search(r"review", name, re.I))


def attribution(name, row, source_hash):
    case = canonical_id(name, row)
    common = dict(canonical_case_id=case, source_ref=source_hash, partition=partition(name, row))
    error = row.get("error") if isinstance(row.get("error"), dict) else {}
    response = row.get("response")
    response = response if isinstance(response, dict) else {}
    response_result = response.get("result")
    response_result = response_result if isinstance(response_result, dict) else {}
    full = response_result.get("full_review")
    full = full if isinstance(full, dict) else {}
    reason = str(row.get("FAIL_REASON") or row.get("root_cause") or row.get("first_failed_stage") or "")
    actual_text = row.get("EXPLANATION_TEXT") or full.get("user_explanation")
    def result(signature, layer, fixable, symptom, expected, observed, cause, confidence=0.9):
        return ReviewFailureAttribution(**common, failure_signature=signature, attribution_layer=layer,
            symptom=symptom, expected_behavior=expected, observed_behavior=observed,
            root_cause=cause, review_skill_fixable=fixable, confidence=confidence,
            notes=("分区仅供审计，未确认的来源不进入生成器",) if common["partition"] != "dev" else ())
    if row.get("scoreable") is False or row.get("infra_error"):
        return result("provider.infrastructure_unscoreable", "provider", False,
                      "请求无法评分", "可用运行环境", "基础设施失败", "未获得有效评分事实")
    if ("actual_skill" in row and row.get("actual_skill") != row.get("expected_skill")) or error.get("intent_ok") is False:
        return result("router.selection_mismatch", "router", False,
                      "路由/Skill 选择不匹配", "原期望路由", "实际选择不同", "选择层而非 Review 文案")
    if row.get("expected_intent") is not None and row.get("actual_intent", row.get("intent")) is not None:
        if row["expected_intent"] != row.get("actual_intent", row.get("intent")):
            return result("router.intent_mismatch", "router", False,
                          "Intent 不匹配", "冻结 Intent", "实际 Intent 不同", "Intent 路由不匹配")
    if "TURN1_CANDIDATE_NOT_CREATED" in reason:
        return result("tool.candidate_not_created", "tool", False,
                      "Review 前置候选未产生", "已有可审查候选", "未进入 Review", "失败在候选创建之前")
    if error.get("status_ok") is False:
        return result("UNATTRIBUTED.request_failed", "UNATTRIBUTED", False,
                      "请求未正常返回", "正常执行并返回事实", "原 scorer 的 status_ok 为 false",
                      "请求链失败，但原记录不足以区分服务、后端或模型；不能归因于 Review 文案", 0.5)
    if any(code in reason.lower() for code in ("timeout", "unavailable", "runtime_error", "network")):
        return result("provider.request_failed", "provider", False,
                      "请求或服务失败", "正常执行并返回事实", "运行错误", "运行链失败，不能用 Prompt 补造结果", 0.75)
    if row.get("EXPECTED_KNOWLEDGE_STATUS") == "AVAILABLE" and row.get("KNOWLEDGE_STATUS") == "INSUFFICIENT":
        return result("rag.trusted_evidence_missing", "rag", False,
                      "可信证据不足", "原评测要求有证据", "证据状态不足", "知识检索/支持过滤未供给期望证据")
    if error.get("missing") or row.get("missing_milestones"):
        if "semantic_events" in row and "review_skill" not in row["semantic_events"]:
            return result("harness.review_not_observed", "UNATTRIBUTED", None,
                          "预期 Review 路径未被观测到", "原轨迹要求进入 Review", "没有 Review 事件",
                          "未证明 Review 已执行；可能是流程、路由或事件投影，不能用 Review Prompt 修复", 0.4)
        return result("review.required_event_missing", "UNATTRIBUTED", None,
                      "必要步骤/事件未被观测到", "冻结必要步骤完整", "部分必要事件缺失",
                      "只有事件缺口，不能确定是 Skill、实际流程还是 Harness 投影", 0.4)
    if actual_text and row.get("FALSE_ACTIVATION_CLAIM") is True:
        return result("review.unsupported_success_claim", "review", True,
                      "解释误报执行成功", "不将待审批解释为执行完成", "已有 scorer 标记虚假完成",
                      "解释文本越过已有事实边界")
    if actual_text and row.get("HALLUCINATED_CITATION") is True:
        return result("review.unsupported_citation", "review", True,
                      "解释编造引用", "仅引用权威提供的锚点", "已有 scorer 标记引用幻觉",
                      "解释未遵守证据边界")
    if actual_text and row.get("HALLUCINATED_BACKEND_FACT") is True:
        return result("review.unsupported_fact", "review", True,
                      "解释编造 Backend 事实", "仅说明已提供事实", "已有 scorer 标记事实幻觉",
                      "解释未遵守事实边界")
    if row.get("EXPECTED_RAG_TRIGGER") is not None or row.get("CORPUS_EXACT_HIT_COUNT") is not None:
        return result("rag.evidence_contract_failure", "rag", False,
                      "知识证据评测失败", "原证据契约", "证据结果不匹配", "证据链而非 Review 文案", 0.8)
    if "parser" in reason.lower() or row.get("expected_parse_status") is not None:
        return result("parser.constraint_failure", "parser", False,
                      "约束解析失败", "冻结解析结果", "实际不匹配", "解析不属于 Review Skill")
    if "backend" in reason.lower() or row.get("backend_authority_correct") is False:
        return result("backend.authority_failure", "backend", False,
                      "后端事实/权威异常", "权威结果正确", "后端事实不匹配", "Backend 权威链而非说明文案")
    return result("UNATTRIBUTED", "UNATTRIBUTED", None,
                  "原评测标记失败", "原冻结期望", "已有评分失败但信息不足",
                  "缺少能够排除其他层的成对期望/实际证据", 0.2)


def clusters(attributions, min_support=3):
    grouped = {}
    for row in attributions:
        if row.review_skill_fixable is not True:
            continue
        key = (row.target_skill, row.failure_signature, row.root_cause)
        grouped.setdefault(key, []).append(row)
    output = []
    for (target, signature, cause), rows in sorted(grouped.items()):
        unique = {row.canonical_case_id for row in rows}
        eligible = {row.canonical_case_id for row in rows if row.partition in {"dev", "train"}}
        output.append({"cluster_id": fingerprint((target, signature, cause)),
            "failure_signature": signature, "support_count": len(unique), "source_count": len({r.source_ref for r in rows}),
            "eligible_support_count": len(eligible), "root_cause": cause,
            "representative_symptoms": sorted({r.symptom for r in rows}),
            "recommended_mutation_scope": ["prompt.md"], "admitted": len(eligible) >= min_support})
    return output


def audit(root: Path | tuple[Path, ...]):
    inventory, failures, record_count, scored_count = [], [], 0, 0
    hashes, cases, recovered, partitions, notes, query_variants = {}, set(), set(), {}, [], {}
    roots = (root,) if isinstance(root, Path) else root
    def sources():
        for directory in roots:
            for name, raw, physical in discover(directory):
                yield (directory.name + "/" + name if len(roots) > 1 else name), raw, physical
    for name, raw, physical in sources():
        if physical not in hashes:
            hashes[physical] = hashlib.sha256(physical.read_bytes()).hexdigest()
        if raw is None:
            inventory.append(dict(source_path=name, source_type="archive", case_count=0,
                has_review_signal=review_signal(name), has_expected_behavior=False, has_actual_behavior=False,
                has_trace=False, usable_for_attribution=False, reason="归档成员分别登记，不重复计外层"))
            continue
        source_hash = hashlib.sha256((name + "\0").encode() + raw).hexdigest()
        try:
            rows, text = parse_rows(name, raw)
        except (ValueError, UnicodeError, csv.Error):
            inventory.append(dict(source_path=name, source_type="parse_error", case_count=0,
                has_review_signal=review_signal(name), has_expected_behavior=False, has_actual_behavior=False,
                has_trace=False, usable_for_attribution=False, reason="无法按原格式解析；未静默跳过"))
            continue
        record_count += len(rows)
        signal = review_signal(name, text=text)
        expected = any(any(k.lower().startswith(("expected", "required")) for k in row) for row in rows)
        actual = any(any(k.lower().startswith(("actual", "observed")) or k in {"response", "EXPLANATION_TEXT", "task_success", "PASS"}
                         for k in row) for row in rows)
        trace = any(any(k in row for k in ("trace", "semantic_events", "trace_id", "GATE_TRACE_ID")) for row in rows)
        usable = expected and actual
        structured_format = Path(name.split("::")[-1]).suffix.lower() in {".json", ".jsonl", ".csv"}
        source_type = "structured" if rows else "structured_summary" if structured_format else "text_or_summary"
        inventory.append(dict(source_path=name, source_type=source_type,
            case_count=len(rows), has_review_signal=signal, has_expected_behavior=expected,
            has_actual_behavior=actual, has_trace=trace, usable_for_attribution=usable,
            reason="只读案例/原结果" if rows else "全文已扫描；汇总或无稳定 case ID，不作为独立案例支持"))
        if not rows and signal and re.search(r"fail|失败|不完整|缺失", text, re.I):
            notes.append(source_hash)
        for row in rows:
            cid = canonical_id(name, row)
            cases.add(cid)
            query = row.get("query") or row.get("USER_QUERY") or row.get("TURN2_QUERY")
            if isinstance(query, str):
                query_variants.setdefault(cid, set()).add(fingerprint(query))
            partitions.setdefault(cid, set()).add(partition(name, row))
            outcome = verdict(row)
            if outcome is not None:
                scored_count += 1
            if outcome is True:
                recovered.add(cid)
            if outcome is False and review_signal(name, row):
                failures.append(attribution(name, row, source_hash))
    # 同一案例只要出现在保留集，整个案例不进入生成经验。
    conflicts = {cid for cid, variants in query_variants.items() if len(variants) > 1}
    failures = [row.model_copy(update={"partition": "audit_only", "notes": row.notes +
                (("相同编号存在不同文本版本，保守隔离，不增加独立支持数",) if row.canonical_case_id in conflicts else ())})
                if "audit_only" in partitions[row.canonical_case_id] or row.canonical_case_id in conflicts
                else row for row in failures]
    final_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in hashes}
    if hashes != final_hashes:
        raise ValueError("审计期间原始资产变化；本轮结论不可冻结")
    unique_failure_cases = {r.canonical_case_id for r in failures}
    counted = {}
    for row in failures:
        counted.setdefault(row.failure_signature, set()).add(row.canonical_case_id)
    found_clusters = clusters(failures)
    summary = {
        "failure_sources_scanned": len(inventory), "physical_files_scanned": len(hashes),
        "structured_sources": sum(r["source_type"] == "structured" for r in inventory),
        "structured_summary_sources": sum(r["source_type"] == "structured_summary" for r in inventory),
        "text_or_summary_sources": sum(r["source_type"] == "text_or_summary" for r in inventory),
        "parse_error_sources": sum(r["source_type"] == "parse_error" for r in inventory),
        "case_records_scanned": record_count, "unique_cases_scanned": len(cases), "scored_records": scored_count,
        "review_failure_records": len(failures), "review_failures_found": len(unique_failure_cases),
        "signature_unique_counts": {k: len(v) for k, v in sorted(counted.items())},
        "review_skill_fixable": len({r.canonical_case_id for r in failures if r.review_skill_fixable is True}),
        "unattributed_cases": len({r.canonical_case_id for r in failures if r.review_skill_fixable is None}),
        "cases_with_successful_run": len(unique_failure_cases & recovered),
        "failure_clusters": len(found_clusters), "admitted_clusters": sum(r["admitted"] for r in found_clusters),
        "clusters": found_clusters, "original_hashes_unchanged": True,
        "qualitative_review_failure_sources": len(notes),
        "case_id_text_conflicts": len(conflicts), "repository_roots_scanned": len(roots),
        "scope": "所有发现的历史评测/审查/轨迹/trace/报告/交接文本及 ZIP 成员；排除模型、依赖、语料与索引",
    }
    return inventory, failures, summary, {str(p): h for p,h in hashes.items()}


def main():
    """只读审计入口；明细必须保存到工程外的私下输出目录。"""
    import argparse
    parser = argparse.ArgumentParser(description="审计历史审查失败，不执行评测或候选生成")
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    roots = tuple(p.resolve(strict=True) for p in args.root)
    output = args.private_output.resolve()
    package = Path(__file__).resolve().parents[3]
    if output == package or package in output.parents:
        raise ValueError("原始归因与来源清单不得写入公开工程")
    if any(output == p or p in output.parents for p in roots):
        raise ValueError("不能将审计输出写入历史输入目录")
    inventory, failures, summary, hashes = audit(roots)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (("inventory.json", inventory), ("summary.json", summary), ("source_hashes.json", hashes)):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "attributions.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in failures), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
