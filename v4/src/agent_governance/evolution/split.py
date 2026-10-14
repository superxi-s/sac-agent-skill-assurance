from dataclasses import dataclass
import hashlib
import re


@dataclass(frozen=True)
class ReviewSplitAssigner:
    """匿名规范身份稳定分流；分区规则在实验前固定，不按结果调整。"""

    namespace: str = "review-split-v1"

    def assign(self, anonymous_identity: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", anonymous_identity):
            raise ValueError("仅接受匿名规范身份摘要")
        value = int(hashlib.sha256((self.namespace + anonymous_identity).encode()).hexdigest(), 16) % 100
        return "evolution_dev" if value < 60 else "regression" if value < 80 else "protected_heldout"


@dataclass(frozen=True)
class ReviewFamilySplitAssigner:
    """v2 唯一家族分区主键；不得传入 review/run 身份。"""

    namespace: str = "review-family-v2"

    def assign(self, case_family_id: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", case_family_id):
            raise ValueError("家族必须是匿名摘要")
        value = int(hashlib.sha256((self.namespace + case_family_id).encode()).hexdigest(), 16) % 100
        return "evolution_dev" if value < 60 else "regression" if value < 80 else "protected_heldout"


def family_id(key: bytes, business_snapshot: dict) -> str:
    """调用方提交规范业务事实，密钥仅在私下保存。"""
    from .review_quality import private_ref
    if not business_snapshot:
        raise ValueError("缺少权威业务快照，不能按 identity 凑独立家族")
    return private_ref(key, ['review-family-v2', business_snapshot])


def audit_family_manifest(rows: list[dict]) -> dict:
    """同家族跨分区是硬失败；近重复组也必须同分区或明确人工复核。"""
    family_splits, near_splits = {}, {}
    seen_cases = set()
    for row in rows:
        if row['case_id'] in seen_cases:
            raise ValueError("重复 case_id")
        seen_cases.add(row['case_id'])
        if not re.fullmatch(r'[0-9a-f]{64}', row['case_family_id']):
            raise ValueError('非法家族标识')
        if row['split'] not in {'evolution_dev', 'regression', 'protected_heldout'}:
            raise ValueError('非法分区')
        family_splits.setdefault(row['case_family_id'], set()).add(row['split'])
        if row.get('near_duplicate_group'):
            near_splits.setdefault(row['near_duplicate_group'], set()).add(row['split'])
    collisions = sum(len(v) > 1 for v in family_splits.values())
    near_collisions = sum(len(v) > 1 for v in near_splits.values())
    heldout = sum(v == {'protected_heldout'} for v in family_splits.values())
    return dict(total=len(rows), unique_case_families=len(family_splits),
                cross_split_family_collisions=collisions, cross_split_near_collisions=near_collisions,
                heldout_unique_families=heldout,
                isolation='PASS' if not collisions and not near_collisions else 'FAIL')
