"""dev5 只读验收辅助。生成待审证据，不批准执行、晋升或模型实验。"""
from __future__ import annotations
import hashlib
import json
from .claim_verification import ClaimVerifierV2


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def claim_review(text, authority):
    """保留评分器原始结果；作用域是句段候选，不冒充语言学人工判定。"""
    result = ClaimVerifierV2().verify(text, authority)
    return {
        'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'prediction': result.verdict,
        'claims': [dict(c.__dict__, negation_scope_candidate=c.source_span,
                        scope_method='SCORER_CLAUSE_PENDING_HUMAN_REVIEW') for c in result.claims],
        'label_origin': 'AI_DRAFT', 'human_label': None,
        'reviewer_id': None, 'reviewed_at': None, 'signature': None,
        'review_status': 'HOLD',
    }


def canonical_snapshot(value, ignored_keys=()):
    """调用方显式选择忽略字段；领域投影留在适配侧。"""
    ignored = set(ignored_keys)
    def clean(value):
        if isinstance(value, dict):
            return {k:clean(v) for k,v in value.items()
                    if k not in ignored and not k.endswith(('_id', '_fingerprint'))}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    if not value:
        raise ValueError('缺少权威事实，不能按空对象判定无污染')
    return clean(value)


def normalized_distance(a, b):
    if not a or len(a) != len(b):
        return None
    return sum(abs(x-y)/max(1,abs(x),abs(y)) for x,y in zip(a,b))/len(a)


def order_comparison(first, second):
    allowed = {'A','B','TIE','UNCERTAIN'}
    if first not in allowed or second not in allowed:
        raise ValueError('非法评审结果')
    reverse = {'A':'B','B':'A','TIE':'TIE','UNCERTAIN':'UNCERTAIN'}[second]
    return {'mapped_second': reverse, 'order_disagreement': first != reverse,
            'order_consistent': first == reverse and first != 'UNCERTAIN'}


def admission_decision(claim, family, contamination, judge, safety):
    required = {'CLAIM_CALIBRATION':claim, 'FAMILY_INDEPENDENCE':family,
                'EXTERNAL_CONTAMINATION':contamination, 'JUDGE_CALIBRATION':judge,
                'SAFETY_CORE_UNCHANGED':safety}
    blockers = [k for k,v in required.items() if v != ('YES' if k=='SAFETY_CORE_UNCHANGED' else 'PASS')]
    return dict(required, EXPERIMENT_04='HOLD' if blockers else 'READY_FOR_FROZEN_EVALUATION',
                blockers=blockers, candidate_generated=False)
