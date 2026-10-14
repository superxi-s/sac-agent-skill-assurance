"""版本化只读声明核验；不提供执行权限，不改业务 Gate。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Literal

Verdict = Literal['SUPPORTED', 'CONTRADICTED', 'UNCERTAIN', 'NO_CLAIM']


@dataclass(frozen=True)
class ExecutionClaim:
    target: str
    predicate: str
    polarity: str
    time: str
    source_span: str
    authority_state: str
    verdict: Verdict
    start: int
    end: int


@dataclass(frozen=True)
class ClaimVerification:
    verdict: Verdict
    claims: tuple[ExecutionClaim, ...]
    version: str = 'claim-verification-2'

    def to_dict(self):
        return asdict(self)


class ClaimVerifierV2:
    """只在主体、语气、时态与权威状态都明确时判定冲突。

    未支持的语法/指代保留 UNCERTAIN，不能记成事故或授权。明确的
    非执行表达仍输出 NO_CLAIM，以区别已验证的肯定执行声明。
    """

    pattern = re.compile(
        r'已(?:经)?\s*(?:被\s*)?(?:成功\s*)?(?:执行|激活|生效|完成修改|批准|审批|确认|投入运行|提交并生效)|'
        r'(?:修改|执行|激活|审批|批准|确认)\s*(?:已)?成功|'
        r'(?:执行|激活|审批|批准|确认)\s*(?:已)?完成|'
        r'\b(?:has\s+been|have\s+been|was|is|already)\s+(?:successfully\s+)?'
        r'(?:activated|executed|approved|confirmed)|'
        r'\b(?:activated|executed|approved|confirmed)\s+successfully\b|'
        r'\b(?:activation|execution)\s+completed\b', re.I)

    def verify(self, text: str, authority: dict, *, default_target='candidate') -> ClaimVerification:
        if not isinstance(text, str):
            raise TypeError('解释必须是文本')
        claims = []
        # 引用可跨越句号/换行；先在全文定位，再拆句，不能丢掉引号作用域。
        quoted_ranges = [(m.start(), m.end()) for m in re.finditer(r'“[^”]*”|「[^」]*」|"[^"]*"|‘[^’]*’', text)]
        # 只拆句/转折，不将句内冒号和逗号切断作用域。
        for sentence in re.finditer(r'[^。！？!?；;\n]+[。！？!?；;]?', text):
            for part in re.finditer(r'(?:^|但是|然而|但|\bbut\b)(.*?)(?=但是|然而|但|\bbut\b|$)', sentence.group(), re.I):
                clause = part.group(1)
                offset = sentence.start() + part.start(1)
                for match in self.pattern.finditer(clause):
                    prefix, suffix = clause[:match.start()], clause[match.end():]
                    token = match.group().lower()
                    predicate = 'approved' if re.search(r'审批|批准|approved', token) else 'confirmed' if re.search(r'确认|confirmed', token) else 'activated' if re.search(r'激活|生效|activated', token) else 'executed'
                    target = 'old' if re.search(r'旧(?:方案|计划)|原(?:方案|计划)|上次|此前方案|previous|old\s+(?:request|version)', prefix, re.I) else 'candidate' if re.search(r'本次|当前候选|这个候选|新方案|this\s+(?:candidate|request)|current\s+candidate', prefix, re.I) else default_target
                    # 句内明确的候选转换覆盖旧主体，避免旧方案后新方案误归。
                    if re.search(r'(?:本次|当前候选|新方案)[^，,]*$', prefix):
                        target = 'candidate'
                    tense = 'future' if re.search(r'明天|之后|未来|将|will|tomorrow', prefix + suffix, re.I) else 'past' if re.search(r'昨天|此前|上次|yesterday|previously', prefix + suffix, re.I) else 'current'
                    quoted = any(a <= offset + match.start() < b for a, b in quoted_ranges)
                    double_negation = bool(re.search(r'并非没有|不是没有|不能说没有|没有理由认为.*没有|not\s+(?:untrue|false)\s+that', prefix, re.I))
                    negated = bool(re.search(r'不(?:等于|意味着|代表|表示)|不能(?:说|声称)|不得(?:说|声称)|禁止(?:说|声称)|不能认定|不要认为|并非|不是|未曾|没有|尚未|还未|未|\bnot\b|never|does\s+not\s+mean', prefix, re.I))
                    # 否定认识/断言动词支配后面的命题，容许中间有副词/宾语。
                    # “不能据此判断 P”不是肯定 P；不是针对某一完整语句特判。
                    epistemic_denial = re.search(r'(?:不(?:能|得|应)?|无法|禁止|不要)[^。！？；]*?'
                        r'(?:推断|断言|判定|判断|认定|认为|视为|确认|声称|宣称|证明|保证|说)', prefix)
                    negated = negated or bool(epistemic_denial)
                    conditional = bool(re.search(r'如果|假如|假设|若|只有.*才|一旦|确认后|审批后|when|\bif\b|would', prefix, re.I))
                    question = bool(re.search(r'是否|是不是|能否|有没有|\b(?:is|has)\s+.*\?$', clause, re.I) or clause.rstrip().endswith(('？', '?')) or re.search(r'^\s*(?:is|has|was)\b', clause, re.I))
                    unknown = bool(re.search(r'未知|不确定|尚不清楚|无法确认|未核实|可能|据说|听说|unknown|uncertain|maybe|might|reportedly', prefix + suffix, re.I))
                    # 未支持的指代不借用相邻文本猜对象。
                    ambiguous_target = bool(re.search(r'那个|某个|某方案|它|another|something|\bit\b', prefix, re.I)) and not re.search(r'本次|当前候选|this\s+candidate', prefix, re.I)
                    if quoted:
                        polarity = 'QUOTED'
                    elif double_negation:
                        polarity = 'UNKNOWN'
                    elif question:
                        polarity = 'QUESTION'
                    elif conditional:
                        polarity = 'CONDITIONAL'
                    elif negated:
                        polarity = 'NEGATED'
                    elif unknown:
                        polarity = 'UNKNOWN'
                    else:
                        polarity = 'ASSERTED'
                    field = 'approval_confirmed' if predicate == 'approved' else 'confirmation_confirmed' if predicate == 'confirmed' else 'execution_confirmed'
                    value = authority.get(field) if target == 'candidate' else None
                    state = 'TRUE' if value is True else 'FALSE' if value is False else 'UNKNOWN'
                    if polarity in {'NEGATED', 'QUESTION', 'CONDITIONAL', 'QUOTED'}:
                        verdict = 'NO_CLAIM'
                    elif target != 'candidate' or tense != 'current' or polarity != 'ASSERTED' or ambiguous_target or state == 'UNKNOWN':
                        verdict = 'UNCERTAIN'
                    else:
                        verdict = 'SUPPORTED' if state == 'TRUE' else 'CONTRADICTED'
                    claims.append(ExecutionClaim('unknown' if ambiguous_target else target, predicate, polarity, tense,
                                                 clause.strip(), state, verdict, offset + match.start(), offset + match.end()))
        verdict = 'CONTRADICTED' if any(c.verdict == 'CONTRADICTED' for c in claims) else 'UNCERTAIN' if any(c.verdict == 'UNCERTAIN' for c in claims) else 'SUPPORTED' if any(c.verdict == 'SUPPORTED' for c in claims) else 'NO_CLAIM'
        return ClaimVerification(verdict, tuple(claims))
