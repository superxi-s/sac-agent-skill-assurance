"""家族级版本化采集；旧反馈库不就地迁移，旧实验保持原样。"""
import json
import hashlib
import sqlite3

from .feedback import ReviewFeedbackCollector
from .review_quality import ReviewQualityReport
from .review_quality_v2 import ReviewQualityReportV2


class FamilyReviewFeedbackCollector(ReviewFeedbackCollector):
    def __init__(self, private_root):
        super().__init__(private_root)
        with self.connect() as db:
            columns = {r[0] for r in db.execute('SELECT name FROM sqlite_master WHERE type="table"')}
            if 'family_protocol' not in columns:
                if db.execute('SELECT COUNT(*) FROM reports').fetchone()[0]:
                    raise ValueError('旧 identity 库必须隔离，禁止就地认作家族库')
                db.execute('CREATE TABLE family_protocol (version TEXT PRIMARY KEY)')
                db.execute('INSERT INTO family_protocol VALUES (?)', ('review-family-v2',))
            db.execute('CREATE TABLE IF NOT EXISTS family_partitions (family TEXT, split TEXT, PRIMARY KEY(family,split))')
            db.execute('CREATE TABLE IF NOT EXISTS quarantined_families (family TEXT PRIMARY KEY)')

    def _refresh(self, db, metadata):
        # 污染家族一旦发现永久隔离，后续回到 dev 也不能重新准入。
        db.execute('DELETE FROM observations WHERE substr(json_extract(data,"$.source_refs[0]"),8) IN (SELECT family FROM quarantined_families)')
        return super()._refresh(db, metadata)

    def collect(self, report: ReviewQualityReportV2):
        if not isinstance(report, ReviewQualityReportV2):
            raise ValueError('v2 采集必须带 case_family_id 与评分器版本')
        if report.scorer_version != 'review-quality-2':
            raise ValueError('评分器版本不匹配')
        family = report.case_family_id
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO family_partitions VALUES (?,?)', (family, report.split))
            count = db.execute('SELECT COUNT(*) FROM family_partitions WHERE family=?', (family,)).fetchone()[0]
            if count != 1:
                db.execute('INSERT OR IGNORE INTO quarantined_families VALUES (?)', (family,))
                for row in db.execute('SELECT data FROM clusters').fetchall():
                    self._refresh(db, json.loads(row[0]))
            quarantined = db.execute('SELECT 1 FROM quarantined_families WHERE family=?', (family,)).fetchone() is not None
        # 旧增量采集以 task_id 去重，v2 将其绑定家族而非重跑/身份。
        values = report.model_dump(exclude={'case_family_id', 'family_protocol', 'claim_verdict', 'applicable', 'ground_truth_source'})
        values['task_id'] = family
        if quarantined:
            values['split'] = 'protected_heldout'
        if report.claim_verdict == 'UNCERTAIN':
            values['skill_fixable_signatures'] = ()
        canonical = ReviewQualityReport(**values)
        return super().collect(canonical)

    def generate_ready(self, *args, **kwargs):
        with self.connect() as db:
            if db.execute('SELECT 1 FROM quarantined_families LIMIT 1').fetchone():
                raise ValueError('家族污染库 HOLD，需新版本库独立冻结后才能生成')
        return super().generate_ready(*args, **kwargs)

    def quarantine_legacy_admissions(self, source_database, family_by_task):
        """只读旧库：新协议撤销来源准入，不改旧实验/旧 SQLite。"""
        source = source_database.resolve()
        if source == self.database.resolve():
            raise ValueError('来源和隔离库必须分离')
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as legacy:
            reports = [json.loads(r[0]) for r in legacy.execute('SELECT data FROM reports')]
            old_admitted = [json.loads(r[0]) for r in legacy.execute('SELECT data FROM clusters')
                            if json.loads(r[0]).get('state') == 'CANDIDATE_READY']
        partitions = {}
        for report in reports:
            family = family_by_task.get(report['task_id'])
            if family is None:
                raise ValueError('旧来源缺少家族映射，不能自动迁移准入')
            partitions.setdefault(family, set()).add(report['split'])
        contaminated = [f for f, splits in partitions.items() if len(splits) > 1]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.executemany('INSERT OR IGNORE INTO quarantined_families VALUES (?)', [(f,) for f in contaminated])
            db.execute('CREATE TABLE IF NOT EXISTS legacy_quarantine (source_hash TEXT PRIMARY KEY, data TEXT)')
            receipt = dict(source_hash=before, imported_admissions=0, legacy_admissions_revoked_for_v2=len(old_admitted),
                           contaminated_families=len(contaminated), protocol='review-family-v2', status='QUARANTINED')
            db.execute('INSERT OR REPLACE INTO legacy_quarantine VALUES (?,?)', (before, json.dumps(receipt)))
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        return receipt
