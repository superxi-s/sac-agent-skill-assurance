import json
import threading
from types import SimpleNamespace

import pytest

from agent_governance.evolution.family_feedback import FamilyReviewFeedbackCollector
from agent_governance.evolution.feedback import ReviewFeedbackCollector
from agent_governance.evolution.review_quality_v2 import ReviewQualityReportV2
from agent_governance.evolution.split import ReviewFamilySplitAssigner, family_id, audit_family_manifest
from agent_governance.evolution.adapters.sac import SACForwardReviewFeedback, business_snapshot
from agent_governance.fingerprint import fingerprint
from test_review_feedback import KEY, failed


def family_report(identity, family, split='evolution_dev'):
    values = failed(identity, split=split).model_dump()
    values.update(case_family_id=fingerprint(family), claim_verdict='CONTRADICTED',
                  scorer_version='review-quality-2', applicable={}, ground_truth_source={})
    return ReviewQualityReportV2(**values)


def test_many_identities_same_family_never_accumulate_support(tmp_path):
    collector = FamilyReviewFeedbackCollector(tmp_path)
    for i in range(10):
        collector.collect(family_report(str(i), 'same-family'))
    assert collector.states()[0]['support_count'] == 1
    assert collector.states()[0]['state'] == 'INSUFFICIENT_EVIDENCE'


def test_three_independent_families_are_required(tmp_path):
    collector = FamilyReviewFeedbackCollector(tmp_path)
    for i in range(3):
        collector.collect(family_report(str(i), str(i)))
    assert collector.states()[0]['support_count'] == 3
    assert collector.states()[0]['state'] == 'CANDIDATE_READY'


@pytest.mark.parametrize('partition', ['regression', 'protected_heldout'])
def test_cross_split_family_revokes_admission_permanently(tmp_path, partition):
    collector = FamilyReviewFeedbackCollector(tmp_path)
    for i in range(3):
        collector.collect(family_report(str(i), str(i)))
    collector.collect(family_report('other-identity', '0', partition))
    assert collector.states()[0]['support_count'] == 2
    collector.collect(family_report('replayed-dev', '0'))
    assert collector.states()[0]['state'] == 'INSUFFICIENT_EVIDENCE'
    with pytest.raises(ValueError, match='HOLD'):
        collector.generate_ready('unused', None, None, None, source_skill_hash=fingerprint('x'))


def test_old_library_is_not_relabelled_as_family_database(tmp_path):
    ReviewFeedbackCollector(tmp_path).collect(failed())
    with pytest.raises(ValueError, match='隔离'):
        FamilyReviewFeedbackCollector(tmp_path)
    assert ReviewFeedbackCollector(tmp_path).states()[0]['support_count'] == 1


def test_uncertain_claim_not_failure_support(tmp_path):
    collector = FamilyReviewFeedbackCollector(tmp_path)
    for i in range(3):
        collector.collect(family_report(str(i), str(i)).model_copy(update={'claim_verdict': 'UNCERTAIN'}))
    assert all(row['state'] == 'INSUFFICIENT_EVIDENCE' for row in collector.states())


def test_same_business_family_ignores_identity_and_wording():
    base = {'replan_result': {'candidate_plan': {'plan_id': 'synthetic-one', 'user_id': 'synthetic-user',
                                               'points': [{'index': 0, 'power_kw': 1}]}},
            'constraint_set': {'minimum': .3}, 'review_question': '合成问题一'}
    other = json.loads(json.dumps(base))
    other['review_question'] = '完全不同的合成措辞'
    other['replan_result']['candidate_plan']['plan_id'] = 'synthetic-two'
    one = family_id(KEY, business_snapshot(base))
    two = family_id(KEY, business_snapshot(other))
    assert one == two
    assert ReviewFamilySplitAssigner().assign(one) == ReviewFamilySplitAssigner().assign(two)


def test_manifest_conflict_and_near_duplicates_hold():
    rows = [{'case_id': str(i), 'case_family_id': fingerprint(str(i)), 'near_duplicate_group': 'shared-shape',
             'split': partition} for i, partition in enumerate(['evolution_dev', 'protected_heldout'])]
    assert audit_family_manifest(rows)['isolation'] == 'FAIL'
    rows[1]['case_family_id'] = rows[0]['case_family_id']
    assert audit_family_manifest(rows)['cross_split_family_collisions'] == 1


def test_feedback_queue_shutdown_full_is_bounded_and_visible():
    import queue
    worker = SACForwardReviewFeedback.__new__(SACForwardReviewFeedback)
    worker.closed, worker.dropped_on_shutdown = False, 0
    worker.queue = queue.Queue(maxsize=1)
    worker.queue.put_nowait(('observe', ()))
    worker.worker = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: False)
    receipt = worker.close()
    assert receipt == {'worker_stopped': True, 'dropped_on_shutdown': 1}
    with pytest.raises(RuntimeError, match='CLOSED'):
        worker.submit({}, {}, {})


def test_restart_retry_preserves_family_dedup(tmp_path):
    FamilyReviewFeedbackCollector(tmp_path).collect(family_report('first-run', 'same'))
    reopened = FamilyReviewFeedbackCollector(tmp_path)
    reopened.collect(family_report('after-restart', 'same'))
    assert reopened.states()[0]['support_count'] == 1


def test_legacy_quarantine_is_readonly_and_revokes_v2_admission(tmp_path):
    import hashlib
    old = ReviewFeedbackCollector(tmp_path / 'old')
    reports = [failed(str(i), split='evolution_dev') for i in range(3)]
    for r in reports:
        old.collect(r)
    old.collect(failed('0', split='protected_heldout'))
    before = old.database.read_bytes()
    new = FamilyReviewFeedbackCollector(tmp_path / 'new')
    receipt = new.quarantine_legacy_admissions(old.database, {r.task_id: fingerprint('one-family') for r in reports})
    assert receipt['contaminated_families'] == 1
    assert receipt['imported_admissions'] == 0
    assert old.database.read_bytes() == before
    assert new.states() == ()
