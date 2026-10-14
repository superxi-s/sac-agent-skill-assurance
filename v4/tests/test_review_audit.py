import hashlib
import json
import zipfile

import pytest

from agent_governance.evolution.review_audit import (
    audit, attribution, canonical_id, clusters, parse_rows, verdict,
)


def failure(identifier="synthetic-1", **changes):
    row = {"CASE_ID": identifier, "PASS": False, "EXPLANATION_TEXT": "合成错误说明",
           "FALSE_ACTIVATION_CLAIM": True, "split": "dev"}
    row.update(changes)
    return row


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def test_inventory_archive_and_duplicate_support(tmp_path):
    rows = [failure()]
    source = tmp_path / "review/run1.jsonl"
    write(source, rows)
    write(tmp_path / "review/merged.jsonl", rows)
    with zipfile.ZipFile(tmp_path / "review/handoff.zip", "w") as archive:
        archive.write(source, "review/results.jsonl")
    inventory, failures, summary, _ = audit(tmp_path)
    assert len(inventory) == 4
    assert summary["review_failure_records"] == 3
    assert summary["review_failures_found"] == 1
    assert summary["clusters"][0]["support_count"] == 1
    assert summary["admitted_clusters"] == 0
    assert len(failures) == 3


def test_three_unique_cases_admit_without_lowering_threshold(tmp_path):
    write(tmp_path / "review/results.jsonl", [failure(f"synthetic-{i}") for i in range(3)])
    _, rows, summary, _ = audit(tmp_path)
    assert summary["admitted_clusters"] == 1
    assert clusters(rows)[0]["eligible_support_count"] == 3


def test_blind_copy_quarantines_entire_case(tmp_path):
    write(tmp_path / "review/dev.jsonl", [failure(f"synthetic-{i}") for i in range(3)])
    write(tmp_path / "review/blind.jsonl", [failure("synthetic-1", split="blind")])
    _, rows, summary, _ = audit(tmp_path)
    assert summary["clusters"][0]["eligible_support_count"] == 2
    assert summary["admitted_clusters"] == 0
    assert all(r.partition == "audit_only" for r in rows if r.canonical_case_id == canonical_id("x", failure()))


def test_unknown_partition_never_becomes_training_support(tmp_path):
    write(tmp_path / "review/results.jsonl", [failure(f"synthetic-{i}", split=None) for i in range(3)])
    assert audit(tmp_path)[2]["admitted_clusters"] == 0


@pytest.mark.parametrize("changes,signature,fixable", [
    ({"EXPLANATION_TEXT": "", "FAIL_REASON": "TURN1_CANDIDATE_NOT_CREATED"}, "tool.candidate_not_created", False),
    ({"EXPLANATION_TEXT": "", "EXPECTED_KNOWLEDGE_STATUS": "AVAILABLE", "KNOWLEDGE_STATUS": "INSUFFICIENT"}, "rag.trusted_evidence_missing", False),
    ({"EXPLANATION_TEXT": "", "error": {"intent_ok": False}}, "router.selection_mismatch", False),
    ({"EXPLANATION_TEXT": "", "semantic_events": ["review_skill"], "error": {"missing": ["fact_read"]}}, "review.required_event_missing", None),
    ({"EXPLANATION_TEXT": "", "semantic_events": [], "error": {"missing": ["review_skill"]}}, "harness.review_not_observed", None),
    ({"EXPLANATION_TEXT": "", "FALSE_ACTIVATION_CLAIM": False}, "UNATTRIBUTED", None),
])
def test_attribution_uses_existing_facts_not_prompt_guess(changes, signature, fixable):
    result = attribution("review/results.jsonl", failure(**changes), "0" * 64)
    assert result.failure_signature == signature
    assert result.review_skill_fixable is fixable


def test_no_new_scorer_for_raw_output_or_summary(tmp_path):
    assert verdict({"case_id": "synthetic-1", "response": {"status": "OK"}}) is None
    path = tmp_path / "review/report.md"
    path.parent.mkdir()
    path.write_text("失败数为三，待确认根因。", encoding="utf-8")
    _, _, summary, _ = audit(tmp_path)
    assert summary["review_failures_found"] == 0
    assert summary["qualitative_review_failure_sources"] == 1


def test_windows_log_encodings_are_scanned():
    for encoding in ("utf-16", "gb18030", "utf-8-sig"):
        rows, text = parse_rows("review/output.log", "审查运行失败".encode(encoding))
        assert rows == [] and text == "审查运行失败"


def test_source_read_only_and_private_rows_not_in_attribution(tmp_path):
    source = tmp_path / "review/results.jsonl"
    rows = [failure(query="此处是私有输入，不应复制"), {"id": "trace-only"}]
    write(source, rows)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    _, failures, summary, _ = audit(tmp_path)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert summary["unique_cases_scanned"] == 1
    assert "此处是私有输入" not in failures[0].model_dump_json()


def test_variant_identifier_is_conservatively_quarantined(tmp_path):
    write(tmp_path / "review/run1.jsonl", [failure(query="第一版本")])
    write(tmp_path / "review/run2.jsonl", [failure(query="另一版本")])
    _, failures, summary, _ = audit(tmp_path)
    assert summary["case_id_text_conflicts"] == 1
    assert summary["review_failures_found"] == 1
    assert all(r.partition == "audit_only" for r in failures)


def test_multiple_roots_deduplicate_copies(tmp_path):
    roots = (tmp_path / "workspace_a", tmp_path / "workspace_b")
    for root in roots:
        write(root / "review/results.jsonl", [failure()])
    inventory, _, summary, _ = audit(roots)
    assert summary["repository_roots_scanned"] == 2
    assert summary["review_failures_found"] == 1
    assert {i["source_path"].split("/")[0] for i in inventory} == {"workspace_a", "workspace_b"}


def test_malformed_source_is_explicit_not_silent(tmp_path):
    path = tmp_path / "review/broken.json"
    path.parent.mkdir()
    path.write_text("{broken", encoding="utf-8")
    inventory, _, summary, _ = audit(tmp_path)
    assert summary["parse_error_sources"] == 1
    assert inventory[0]["usable_for_attribution"] is False
