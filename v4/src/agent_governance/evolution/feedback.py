from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from pathlib import Path
import sqlite3
from typing import Literal

from .candidate import apply_bound_patch, propose
from .snapshot import snapshot
from .experience import mine, distill_cluster
from .models import EvolutionObservation, ExperienceRecord, FrozenModel, Digest, MutationScope
from .observation import record
from .review_quality import ReviewQualityReport, SIGNATURES
from ..fingerprint import fingerprint


class HumanReviewFeedback(FrozenModel):
    review_id: Digest
    status: Literal["ACCEPTED", "REJECTED", "NEEDS_CLARIFICATION", "CORRECTED"]
    correction_type: Literal["confirmation_clear", "constraint_explanation", "candidate_comparison", "cost_benefit", "soc_explanation", "evidence_grounding", "confirmation_clarity", "other"] | None = None


class ReviewFeedbackCollector:
    """匿名前向数据持久化；仅更新当前失败键，不重扫历史资产。"""

    min_support = 3

    def __init__(self, private_root: Path):
        root = private_root.resolve()
        public = Path(__file__).resolve().parents[3]
        if root == public or public in root.parents:
            raise ValueError("反馈必须保存到公开工程之外")
        root.mkdir(parents=True, exist_ok=True)
        self.database = root / "feedback.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, candidate_ref TEXT, data TEXT);
                CREATE INDEX IF NOT EXISTS report_candidate ON reports(candidate_ref);
                CREATE INDEX IF NOT EXISTS report_partition ON reports(json_extract(data,'$.task_id'), json_extract(data,'$.split'));
                CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, bucket TEXT, data TEXT, experience TEXT);
                CREATE INDEX IF NOT EXISTS observation_bucket ON observations(bucket);
                CREATE TABLE IF NOT EXISTS clusters (bucket TEXT PRIMARY KEY, data TEXT);
                CREATE TABLE IF NOT EXISTS human (id TEXT PRIMARY KEY, data TEXT);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=2)
        try:
            db.execute("PRAGMA busy_timeout=2000")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def bucket(report, signature):
        return fingerprint((report.target_skill, report.skill_version, report.skill_hash,
                            report.origin, report.split, signature))

    def _append(self, db, report, signature, *, human=False):
        fixable = signature in report.skill_fixable_signatures or human
        ref = "source:" + report.task_id
        observation = EvolutionObservation(
            observation_id=fingerprint((ref, report.skill_hash, report.origin, signature)),
            source_refs=(ref,), split="dev" if report.split == "evolution_dev" else report.split,
            outcome="human_correction" if human else "failure" if signature != "success" else "success",
            category="review" if fixable or signature == "success" else "unknown")
        experience = record(observation)
        bucket = self.bucket(report, signature)
        db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?)",
                   (observation.observation_id, bucket, observation.model_dump_json(), experience.model_dump_json()))
        if human:
            db.execute("UPDATE observations SET data=?, experience=? WHERE id=?",
                       (observation.model_dump_json(), experience.model_dump_json(), observation.observation_id))
        # 单个失败簇增量更新；既有 mine 负责独立支持与门槛。
        metadata = {"bucket": bucket, "target_skill": report.target_skill, "skill_version": report.skill_version,
                    "skill_hash": report.skill_hash, "failure_signature": signature, "origin": report.origin,
                    "split": report.split}
        return self._refresh(db, metadata)

    def _refresh(self, db, metadata):
        bucket = metadata["bucket"]
        stored = [ExperienceRecord.model_validate_json(row[0]) for row in db.execute(
            """SELECT o.experience FROM observations o WHERE o.bucket=? AND NOT EXISTS
               (SELECT 1 FROM reports r WHERE json_extract(r.data,'$.task_id') =
                substr(json_extract(o.data,'$.source_refs[0]'),8) AND json_extract(r.data,'$.split') IN ('heldout','protected_heldout','regression'))""", (bucket,))]
        eligible = []
        for row in stored:
            if row.category == "review" and row.outcome != "success":
                values = row.model_dump(exclude={"experience_id"})
                values["outcome"] = "failure"
                eligible.append(ExperienceRecord(experience_id=fingerprint(values), **values))
        groups = mine(tuple(eligible), min_support=self.min_support) if eligible else ()
        cluster = groups[0] if groups else None
        features = {field: sorted({value for row in db.execute(
            """SELECT r.data FROM reports r WHERE json_extract(r.data,'$.skill_hash')=?
            AND json_extract(r.data,'$.origin')=? AND json_extract(r.data,'$.split')=?
            AND NOT EXISTS (SELECT 1 FROM reports blocked WHERE
            json_extract(blocked.data,'$.task_id')=json_extract(r.data,'$.task_id')
            AND json_extract(blocked.data,'$.split') IN ('heldout','protected_heldout','regression'))""",
            (metadata["skill_hash"], metadata["origin"], metadata["split"]))
            for value in json.loads(row[0]).get(field, [])
            if metadata["failure_signature"] in json.loads(row[0]).get("skill_fixable_signatures", [])})
            for field in ("affected_constraints", "missing_dimensions", "observed_patterns")}
        state = {**metadata, "support_count": cluster.support_count if cluster else 0,
                 **features,
                 "state": "CANDIDATE_READY" if cluster and cluster.admitted else "INSUFFICIENT_EVIDENCE",
                 "cluster": cluster.model_dump(mode="json") if cluster else None}
        db.execute("INSERT OR REPLACE INTO clusters VALUES (?,?)", (bucket, json.dumps(state)))
        return state

    def collect(self, report: ReviewQualityReport) -> tuple[dict, ...]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO reports VALUES (?,?,?)",
                       (report.review_id, report.candidate_ref, report.model_dump_json()))
            if report.split in {"heldout", "protected_heldout", "regression"}:
                affected = db.execute("SELECT DISTINCT bucket FROM observations WHERE json_extract(data,'$.source_refs[0]')=?",
                                      ("source:" + report.task_id,)).fetchall()
                for row in affected:
                    state = db.execute("SELECT data FROM clusters WHERE bucket=?", (row[0],)).fetchone()
                    if state:
                        self._refresh(db, json.loads(state[0]))
                return ()
            return tuple(self._append(db, report, signature) for signature in report.failure_signatures or ("success",))

    def human_feedback(self, feedback: HumanReviewFeedback) -> tuple[dict, ...]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM reports WHERE id=?", (feedback.review_id,)).fetchone()
            if row is None:
                raise ValueError("没有相应的匿名审查记录")
            report = ReviewQualityReport.model_validate_json(row[0])
            identity = fingerprint(feedback.model_dump(mode="json"))
            db.execute("INSERT OR IGNORE INTO human VALUES (?,?)", (identity, feedback.model_dump_json()))
            # Reject/refine 是业务选择，不自动当作 Skill 缺陷。
            if feedback.status not in {"NEEDS_CLARIFICATION", "CORRECTED"} or feedback.correction_type in {None, "other"} or report.split in {"heldout", "protected_heldout", "regression"}:
                return ()
            dimension = {"cost_benefit": "cost_benefit_explanation", "evidence_grounding": "evidence_grounded", "confirmation_clarity": "confirmation_clear"}.get(feedback.correction_type, feedback.correction_type)
            signature = SIGNATURES[dimension]
            return (self._append(db, report, signature, human=True),)

    def human_for_candidate(self, candidate_ref: str, status: str, correction_type=None):
        with self.connect() as db:
            rows = db.execute("SELECT id FROM reports WHERE candidate_ref=?", (candidate_ref,)).fetchall()
        for row in rows:
            self.human_feedback(HumanReviewFeedback(review_id=row[0], status=status, correction_type=correction_type))

    def states(self, *, origin: str | None = None) -> tuple[dict, ...]:
        with self.connect() as db:
            rows = [json.loads(row[0]) for row in db.execute("SELECT data FROM clusters ORDER BY bucket")]
        return tuple(row for row in rows if origin is None or row["origin"] == origin)

    def generate_ready(self, bucket: str, champion: Path, sandbox: Path, provider, *, source_skill_hash: str,
                       scope: MutationScope = MutationScope()):
        """显式离线调用；只走既有 Champion-aware 补丁链，绝不晋升。"""
        from .models import ExperienceCluster
        state = next(row for row in self.states() if row["bucket"] == bucket)
        if state["state"] != "CANDIDATE_READY" or state["skill_hash"] != source_skill_hash or state["split"] not in {"dev", "train", "evolution_dev"}:
            raise ValueError("经验未准入或来源版本已漂移")
        champion_snapshot = snapshot(champion)
        if (champion_snapshot.skill_name, champion_snapshot.version) != (state["target_skill"], state["skill_version"]):
            raise ValueError("Champion 与前向反馈的 Skill 版本不一致")
        cluster = ExperienceCluster.model_validate_json(json.dumps(state["cluster"]))
        signature = state["failure_signature"]
        behavior = {
            "review.unsupported_success_claim": ("候选尚未执行时解释误报执行完成", "明确候选仍待审批，只有权威执行成功后才说明已执行"),
            "review.decision_inconsistent": ("BLOCK 的解释出现直接执行建议", "只解释阻断原因，不建议越过既有 Gate"),
            "review.citation_unsupported": ("解释引用了未提供的来源", "引用仅使用已供给且支持结论的锚点"),
            "review.evidence_not_grounded": ("无证据时声称有外部知识支持", "证据不足时明确说明，不补造依据"),
            "review.confirmation_unclear": ("解释的审批下一步不清楚", "明确确认、复核与最终执行的区别"),
            "review.constraint_explanation_incomplete": ("已有约束影响没有解释清楚", "逐条说明已有约束影响或明确无法确认"),
            "review.candidate_comparison_incomplete": ("已有候选差异没有解释清楚", "说明当前已提供的候选与基线差异"),
            "review.cost_benefit_missing": ("已有费用收益差异未说明", "说明已有费用收益差异，不能编造数值"),
            "review.soc_explanation_missing": ("已有荷电状态变化未说明", "说明已有荷电状态变化与约束影响"),
            "review.incomplete": ("解释未覆盖已提供的必要事实", "完整说明已提供事实，缺失事实明确标记未知"),
        }
        symptom, expected = behavior[signature]
        experience = distill_cluster(state, symptom, expected)
        proposal = propose(provider, champion_snapshot, (experience,), scope)
        return apply_bound_patch(champion, sandbox, proposal, (experience,), (cluster,), scope)


def observe_safely(callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except Exception as exc:
        # 不记录异常原文、业务文本或内部 Trace。
        logging.getLogger(__name__).warning("REVIEW_FEEDBACK_FAILED:%s", type(exc).__name__)
        return None
