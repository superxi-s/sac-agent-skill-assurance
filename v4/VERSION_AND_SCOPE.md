# 版本与验证范围

- **源码版本**：`4.0.0.dev5`（开发快照）；通用冻结 Skill `3.0.1`。V1 历史通过原仓库及归档保留，不在此包重复分发。
- **本次更新（2026-10-12）**：展示文档与公开fixture中性化修订。88条fixture改名并移除审核元数据，更新加载测试；原业务文本、权威事实、预期判定及文本哈希不变。保留AI草拟且未人工校准的来源声明；不生成新的真实Candidate，不改变冻结Skill、Python安全核心、业务逻辑、正式Registry或质量门槛。
- **本包独立可复现**：330 项公开 pytest、四个合成演示、Skill 与 Registry、资源副本校验。
- **历史验证，非本包独立可复现**：SAC 88 项回归及 24 项定向测试、真实 Actor / HTTP / MySQL / Redis 隔离验证、Benchmark112 真实 LLM 对照。
- **正式演进状态**：Benchmark112 Candidate 未正式晋升；`FORMAL_EVOLUTION_GATE=NOT_APPLIED`，`RC1_READY=NO`。
- **公开源码提交授权**：提交请求方已确认源码可公开，并授权提交PR；原LICENSE与归属不变。公开授权不等于生产验收或正式晋升，`RC1_READY=NO`。见 [NOTICE](NOTICE.md)。
