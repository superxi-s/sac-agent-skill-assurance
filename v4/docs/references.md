# 研究、规范与参考实现

> 2026-10-12 整理。以下来源用于指导文档结构、Skill 格式、失败驱动的补丁设计及评测方法；**引用不表示本项目完整复现论文算法、运行其公开基准或获得官方认证**。

| 资料 | 可借鉴的思想 | 本项目实际做了什么 / 不应宣称什么 |
| --- | --- | --- |
| [Agent Skills Specification](https://agentskills.io/specification) | `SKILL.md` 与 `name` / `description` 前置元数据，按需加载 `references/` 和 `scripts/` | 保留 Skill 说明与内部冻结资产；项目内 `manifest.json`、`governance.yaml`、冻结 Registry 为自定义治理约束，不是规范强制字段。 |
| [GitHub Docs：About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes) | 首页优先说清用途、价值、如何开始和帮助入口 | README 将定位、架构、运行、结果放在前面；历史及权属提示保留但不遮住主体。 |
| [Anthropic：Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | 组合代码、模型及人工评审，追踪执行过程和结果；从真实失败构造回归 | 本项目采用代码安全断言、LLM 对照与人工查看记录；没有完整生产人类评估统计。 |
| [GEPA：Reflective Prompt Evolution](https://arxiv.org/abs/2507.19457) | 反思失败轨迹，归纳可改进指令，提出并测试补丁 | 本项目有经验归因、受限 Prompt 补丁和 A/B；**没有实现完整 Genetic-Pareto 搜索**。 |
| [Reflexion：Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366) | 使用语言反馈改善后续尝试，而非必然更新模型权重 | 仅参考反馈与行为改进路线；不是该论文的完整训练框架。 |
| [SkillsBench](https://arxiv.org/abs/2602.12670) | Skill 并非稳定带来提升，自生成能力可能负迁移，需验证 | 本项目冻结 Champion/Candidate、报告覆盖及代价；**没有运行 SkillsBench 官方测试集**。 |
| [ToolSandbox](https://arxiv.org/abs/2408.04682) | 有状态工具调用、隐式依赖、中间与最终里程碑 | 本项目检查审批、CAS、ACTVE 计数及真实 HTTP 路径；不是原论文基准复现。 |
| [AgentDojo](https://arxiv.org/abs/2406.13352) | 不可信工具内容与提示注入的环境级安全评测 | 当前覆盖有限显式注入与越权门控，不声称覆盖全部间接注入攻击。 |
| [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) | 工具权限、身份边界和自治代理威胁模型 | 可用于检查安全说明；不是正式合规认证。 |

## 与本仓库最相关的阅读次序

1. [整体架构](01_architecture.md) → [SAC 专业适配](03_sac.md) → [SAC 集成测试](10_sac_integration_validation.md)。
2. [受控自进化](05_evolution.md) → [分层评测](07_evaluation.md)。
3. [安全边界](06_security.md) → [新增领域](09_new_domain.md)。

## 证据口径

公开可复验数据以 `tests/`、`examples/`、`TEST_RECEIPT.json` 及实际运行命令为准；历史 Benchmark112 和内部 SAC HTTP 测试用方法及汇总说明，不将未公开原始收据描述为当前仓库可复现资产。
