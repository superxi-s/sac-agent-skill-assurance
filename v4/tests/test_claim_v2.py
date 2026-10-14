import hashlib
import json
from pathlib import Path

import pytest

from agent_governance.evolution.claim_verification import ClaimVerifierV2
from agent_governance.evolution.calibration import BlindPairJudge, calibration_gate
from agent_governance.evolution.review_quality_v2 import ReviewQualityScorerV2
from agent_governance.fingerprint import fingerprint
from test_review_feedback import KEY, failed

ROOT = Path(__file__).resolve().parents[1]
ROWS = [json.loads(line) for line in (ROOT / 'docs/evolution/claim_synthetic_cases.jsonl').read_text(encoding='utf-8').splitlines()]


@pytest.mark.parametrize('row', ROWS, ids=[r['case_id'] for r in ROWS])
def test_frozen_synthetic_claim_contract(row):
    assert ClaimVerifierV2().verify(row['text'], row['authority']).verdict == row['expected_label']


def test_unverified_synthetic_cases_cannot_unlock_calibration():
    assert len(ROWS) >= 80
    assert all('label_origin' not in r and 'reviewer_id' not in r for r in ROWS)
    audit = dict(isolation='PASS', unique_case_families=40, total=80, semantic_family_review='PENDING')
    result = calibration_gate(ROWS, [], audit)
    assert result['status'] == 'HOLD'
    assert 'CLAIM_HUMAN_CALIBRATION_PENDING' in result['reasons']


def test_claim_fields_and_span_are_not_execution_permission():
    result = ClaimVerifierV2().verify('本次候选已激活。', {'execution_confirmed': False})
    claim = result.claims[0]
    assert claim.target == 'candidate' and claim.polarity == 'ASSERTED'
    assert claim.authority_state == 'FALSE' and claim.verdict == 'CONTRADICTED'
    assert claim.source_span and claim.end > claim.start
    assert not hasattr(result, 'authorize')


def test_v2_no_raw_span_in_anonymous_report():
    row = failed().model_dump()
    # 使用真实旧 API 的输入结构，v2 不复制解释原文到反馈报告。
    args = dict(context={'execution_confirmed': False}, gate={'decision': 'PASS'},
        result={'user_explanation': '不等于已激活。', 'full_review_status': 'COMPLETE',
                'explanation_mode': 'LLM', 'gate_decision': 'PASS'},
        task_key='synthetic-task', candidate_key='synthetic-object', origin='synthetic',
        target_skill=row['target_skill'], skill_hash=row['skill_hash'], skill_version=row['skill_version'])
    report = ReviewQualityScorerV2(KEY).score(case_family_id=fingerprint('family'), **args)
    assert report.unsupported_success_claim is False
    assert '不等于' not in report.model_dump_json()
    assert report.applicable['candidate_comparison'] is False
    args['context'] = {}
    args['result']['user_explanation'] = '本次候选已激活。'
    unknown = ReviewQualityScorerV2(KEY).score(case_family_id=fingerprint('family'), **args)
    assert unknown.claim_verdict == 'UNCERTAIN' and unknown.unsupported_success_claim is None
    assert 'review.unsupported_success_claim' not in unknown.failure_signatures


def test_blind_pair_actual_order_swap_reports_position_bias():
    from types import SimpleNamespace
    class Biased:
        def complete(self, messages):
            data = json.loads(messages[1]['content'])
            assert set(data) == {'facts', 'A', 'B'}
            return SimpleNamespace(content='{"winner":"A"}', tool_calls=[])
    result = BlindPairJudge(Biased()).evaluate({}, '合成解释甲', '合成解释乙')
    assert result['order_swapped'] and not result['consistent']


def test_old_scorer_hash_remains_frozen():
    path = ROOT / 'src/agent_governance/evolution/review_quality.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '12884792b5e2f3ec2ee984c3edda8827e192257b383c85de235ee12a2dfc0899'


@pytest.mark.parametrize('text', [
    '不能据此推断本次已激活。', '不应根据收益宣称本次执行成功。',
    '禁止仅凭模型说本次已执行。', '不能据此声称本次候选已激活。',
    '不得根据说明认定新方案已生效。', '无法从现有状态判定本次已执行。',
    '不能将当前候选视为已激活。', '不声称当前候选已执行。',
    '摘录：“说明是只读的。不能推断本次已执行。”',
    '旧记录写道「当时审批完成。已激活仅为示例。」',
])
def test_epistemic_negation_and_cross_sentence_quote_scope(text):
    assert ClaimVerifierV2().verify(text, {'execution_confirmed': False}).verdict == 'NO_CLAIM'


def test_denied_earlier_statement_does_not_hide_assertion_after_contrast():
    result = ClaimVerifierV2().verify('不能据此推断已激活，但是本次候选已执行。', {'execution_confirmed': False})
    assert result.verdict == 'CONTRADICTED'
