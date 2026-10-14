"""dev5 的版本化质量报告；旧评分器及实验仍按原接口复现。"""
from datetime import datetime, timezone
from typing import Literal

from .claim_verification import ClaimVerifierV2
from .models import Digest
from .review_quality import ReviewQualityScorer, ReviewQualityReport, SIGNATURES


class ReviewQualityReportV2(ReviewQualityReport):
    scorer_version: str = 'review-quality-2'
    case_family_id: Digest
    family_protocol: Literal['review-family-v2'] = 'review-family-v2'
    claim_verdict: Literal['SUPPORTED', 'CONTRADICTED', 'UNCERTAIN', 'NO_CLAIM']
    applicable: dict[str, bool]
    ground_truth_source: dict[str, str]


class ReviewQualityScorerV2(ReviewQualityScorer):
    def score(self, *, case_family_id, **kwargs):
        legacy = super().score(**kwargs)
        claim = ClaimVerifierV2().verify(str(kwargs['result'].get('user_explanation') or ''), kwargs['context'])
        data = legacy.model_dump()
        data['unsupported_success_claim'] = True if claim.verdict == 'CONTRADICTED' else None if claim.verdict == 'UNCERTAIN' else False
        signature = SIGNATURES['unsupported_success_claim']
        failures = set(legacy.failure_signatures) - {signature}
        fixable = set(legacy.skill_fixable_signatures) - {signature}
        if claim.verdict == 'CONTRADICTED':
            failures.add(signature)
            if kwargs['result'].get('explanation_mode') == 'LLM' and kwargs['result'].get('full_review_status') == 'COMPLETE':
                fixable.add(signature)
        data.update(failure_signatures=tuple(sorted(failures)), skill_fixable_signatures=tuple(sorted(fixable)),
                    missing_dimensions=tuple(k for k, s in SIGNATURES.items() if s in failures),
                    observed_patterns=tuple(sorted(fixable)), case_family_id=case_family_id,
                    claim_verdict=claim.verdict, scorer_version='review-quality-2',
                    created_at=datetime.now(timezone.utc).isoformat())
        # 不适用和缺上游信息保持 None，不硬计为语言缺陷。
        applicable = {k: data[k] is not None for k in SIGNATURES}
        applicable['unsupported_success_claim'] = claim.verdict != 'UNCERTAIN'
        data['applicable'] = applicable
        data['ground_truth_source'] = {k: 'authority+claim-v2' if k == 'unsupported_success_claim' else
            'authority+semantic-judge' if legacy.semantic_status == 'PASS' and k in getattr(self.semantic_judge, 'dimensions', ()) else
            'structured-authority' if applicable[k] else 'NOT_AVAILABLE' for k in SIGNATURES}
        data['overall_status'] = 'FAIL' if failures else 'PARTIAL' if any(data[k] is None for k in SIGNATURES) else 'PASS'
        # 不持久化 Claim 的原始 source_span。版本/家族进入 ID 防止跨评分器覆盖。
        from .review_quality import private_ref
        data['review_id'] = private_ref(self.key, [legacy.review_id, 'review-quality-2', case_family_id, claim.verdict])
        return ReviewQualityReportV2(**data)
