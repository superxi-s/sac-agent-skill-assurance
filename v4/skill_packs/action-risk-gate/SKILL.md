---
name: action-risk-gate
description: 当需要理解高风险动作的执行准入、审批绑定和复核要求时使用；只提供说明，不替代确定性运行时。
metadata:
  version: "4.0.0.dev5"
---

# 使用边界

先读 [冻结说明](references/frozen_skill.md)。本入口只做能力说明；审批、Validator、CAS 和执行权限由调用方治理运行时负责。不得根据自然语言解释自授权业务写入。内部 manifest 与 governance 元数据是项目扩展，不是官方必需格式。
