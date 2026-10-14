---
name: action-review
description: 只读解释高风险操作的确定性门控结果及支持证据，不授予执行权限，不覆盖 BLOCK，无证据时明确弃答。
version: 3.0.1
---

# 操作风险解释

入口：`agent_governance.review.review_evidence`。

用户请求解释操作风险时触发，不授予审批或执行权限。
输入为 `GateResult`、已由调用方完成支持过滤的 `Evidence` 以及可选解释文本。
输出为 `EvidenceReview`，包含原决策、建议码、引用及证据状态。

证据和 LLM 不得把 BLOCK 改为 PASS，不得伪造 Backend 事实、审批或激活结果。
无证据时返回 `NO_EVIDENCE` 并保留空引用。此模块不实现 RAG 检索或调用外部模型。

如调用方使用 LLM 生成解释，提示词应采用以下边界：

> 你是高风险操作审查器。你的职责是解释确定性风险门控结果及其支持证据，不得覆盖、修改或绕过 PASS、REVIEW、BLOCK 决策。不得推断审批已通过或操作已执行；无支持证据时明确说明无法给出有依据的解释。
