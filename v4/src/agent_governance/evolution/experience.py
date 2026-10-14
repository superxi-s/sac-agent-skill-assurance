import json
import os
from collections import defaultdict
from pathlib import Path

from .models import ExperienceCluster, ExperienceRecord, DistilledExperience
from ..fingerprint import fingerprint


class ExperienceStore:
    """只在调用方指定的私有路径入库；不保存原始文本。"""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink():
            raise ValueError("私有存储不能是符号链接")

    def put(self, item: ExperienceRecord) -> None:
        if fingerprint(item.model_dump(mode="json", exclude={"experience_id"})) != item.experience_id:
            raise ValueError("经验内容与 ID 不匹配")
        path = self.root / (item.experience_id + ".json")
        data = item.model_dump_json(indent=2).encode("utf-8")
        try:
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise ValueError("经验 ID 冲突或记录被篡改")

    def records(self) -> tuple[ExperienceRecord, ...]:
        rows = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink():
                raise ValueError("经验文件不能是符号链接")
            item = ExperienceRecord.model_validate_json(path.read_text(encoding="utf-8"))
            if path.stem != item.experience_id:
                raise ValueError("经验文件名与 ID 不匹配")
            if fingerprint(item.model_dump(mode="json", exclude={"experience_id"})) != item.experience_id:
                raise ValueError("经验内容与 ID 不匹配")
            rows.append(item)
        return tuple(rows)


def mine(records: tuple[ExperienceRecord, ...], *, min_support: int = 3,
         allowed_categories: tuple[str, ...] = ("review",)) -> tuple[ExperienceCluster, ...]:
    if min_support < 2:
        raise ValueError("普通经验准入至少需要两条独立观察")
    groups = defaultdict(dict)
    for row in records:
        groups[(row.category, row.outcome)][row.observation_id] = row
    result = []
    for (category, outcome), observations in sorted(groups.items()):
        rows = tuple(observations.values())
        ids = tuple(sorted(observations))
        refs = tuple(sorted({ref for row in rows for ref in row.source_refs}))
        support = len(ids)
        admitted = category in allowed_categories and outcome != "success" and (support >= min_support or
                   (outcome == "near_miss" and any(row.high_risk for row in rows)))
        result.append(ExperienceCluster(
            cluster_id=fingerprint({"category": category, "outcome": outcome, "ids": ids}),
            category=category, outcome=outcome, observation_ids=ids,
            source_refs=refs, support_count=support, admitted=admitted,
            confidence=min(1.0, support / min_support),
        ))
    return tuple(result)


def distill_cluster(state: dict, symptom: str, expected: str) -> DistilledExperience:
    """只把已准入分区的结构化聚合转为可追溯生成输入。"""
    if state["state"] != "CANDIDATE_READY" or state["split"] not in {"train", "dev", "evolution_dev"}:
        raise ValueError("经验未准入或属于保留集")
    values = dict(target_skill=state["target_skill"], failure_signature=state["failure_signature"],
        symptom=symptom, expected_behavior=expected,
        observed_behavior=symptom + "；来源为当前质量评分或明确人工纠正",
        root_cause=state["failure_signature"], recommended_mutation_scope=("prompt.md",), support_count=state["support_count"],
        source_refs=tuple(state["cluster"]["source_refs"]), actionable=True, split=state["split"],
        **{key: tuple(state.get(key, ())) for key in ("affected_constraints", "missing_dimensions", "observed_patterns")})
    return DistilledExperience(experience_id=fingerprint(values), **values)
