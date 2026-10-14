---
name: action-risk-gate
description: 在 Agent 执行高风险写操作前进行确定性风险判断，根据权威业务状态输出 PASS、REVIEW 或 BLOCK，并在审批及执行前复核绑定信息。
version: 3.0.1
---

# 高风险操作门控

入口：`agent_governance.GovernanceRuntime`。

在高风险写操作的审批前和执行前触发；是否需要门控不由 LLM 决定。
输入为 `ActionRequest`；业务事实只通过 `DomainAdapter.snapshot` 从 Backend 读取。
输出为 `GateResult`，保留决策、原因码、策略哈希及追踪标识。

只能读取权威事实和执行纯策略判断，不得直接写数据库、控制设备或替代 Backend CAS。
审批绑定身份、会话、对象、参数、权威版本和策略。REVIEW 必须显式确认；BLOCK 不可审批。
加载或执行异常时默认 BLOCK；执行成功必须具有 Backend 回执。旧审批不可重复使用。

SAC 适配器调用随包提供的最小 SAC 确定性风险策略，不依赖历史评测目录。
