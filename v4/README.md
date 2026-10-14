# Agent Skill Governance

**面向高风险工具调用型 Agent 的 Skill 治理与受控自进化框架**

把**模型的解释与建议**和**系统的业务授权与执行**分开：Agent 可以调用 Skill 分析问题、提出改进，但风险决策、人工审批、执行前复核以及最终写入仍由可信的确定性程序负责。

项目源于户用储能调度 Agent 的候选方案审查需求，进一步抽象出可复用的治理内核、领域适配接口和 Skill 迭代机制。仓库同时提供**通用配置变更、科研工作流、SAC 调度**三个场景的可运行合成示例。

> **阅读入口：** [架构设计](docs/01_architecture.md) · [受控自进化详解](docs/05_evolution.md) · [运行示例](#快速开始) · [评测与边界](#评测结果与证据范围)

## 项目解决什么问题？

在普通问答 Agent 中，模型回答错了可以提示用户重新提问；但在有状态业务里，错误的工具调用可能改变真实数据。例如，用户要求修改一份调度方案，系统需要确认候选计划满足硬约束、审批确实针对该版本、执行时原计划没有被其他请求替换。

单靠一段 System Prompt 无法提供这些保证。本项目将责任拆分为三个层次：

| 层次 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| **Skill** | 专业操作流程、只读审查、解释与建议 | 不直接取得数据库写权限 |
| **治理运行时** | 权限策略、权威事实、审批绑定、状态复核、执行轨迹 | 不代替领域算法计算业务事实 |
| **领域适配器与后端** | 获取当前真实状态、校验领域规则、完成原子写入 | 不让模型绕过系统约束 |

一个核心原则是：**解释可以由大语言模型生成，放行与写入必须由可信程序决定。**

## 整体架构

### 1. 通用治理框架与领域适配

```text
用户 / 业务系统
      │
      ▼
┌───────────────────────────────────────────────────────────────┐
│ 宿主 Agent（任务理解、工具编排、维护会话状态）                 │
│ 选择 Skill，构造结构化 ActionRequest                          │
└──────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
                    Skill 加载与契约校验
                  ┌────────────┴────────────┐
                  ▼                         ▼
         action-risk-gate             action-review
         确定性风险门控               大模型只读审查
        PASS / REVIEW / BLOCK         解释约束、风险与证据
                  │                         │
                  └────────────┬────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ 通用治理运行时（GovernanceRuntime）                            │
│                                                               │
│  请求和身份校验 → 能力/策略判定 → 读取权威快照                 │
│           → 绑定审批参数与版本 → 执行前重新校验                │
│           → 交由领域适配器提交 → 记录结构化回执                 │
└──────────────────────────────┬────────────────────────────────┘
                               │ DomainAdapter 协议
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
      通用配置变更适配器   科研工作流适配器    SAC 调度适配器
       GenericChange      ResearchWorkflow     SACDispatch
              │                │                │
              ▼                ▼                ▼
         合成内存状态      合成内存状态     调度计划 / Validator
                                              │
                                              ▼
                                        权威 Backend
                                      CAS 原子执行
```

上图强调的是**组件职责**，不是所有请求都要经过一次模型生成。风险门控为确定性处理；Review 是只读解释，不参与最终授权。公开示例中的 SAC Backend 为合成实现，实际接入须由业务后端保证原子性。

### 2. SAC 计划变更的业务执行链

```text
用户提出调度约束
      ↓
Agent 解析意图和参数
      ↓
后端生成候选计划 → Validator 验证物理/业务约束
      ↓
确定性 Risk Gate：PASS / REVIEW / BLOCK
      ├── BLOCK ──────────────→ 停止执行，返回原因
      └── PASS / REVIEW
                 ↓
          Review Skill 解释候选差异和风险（只读）
                 ↓
          用户确认 / 拒绝 / 修改
                 ↓
          重新读取后端权威状态
                 ↓
          验证候选、审批、版本和参数是否一致
                 ↓
          后端比较并交换（CAS）及幂等处理
                 ↓
          返回真实执行回执
```

**为什么同时需要审批绑定、执行前复核和 CAS？** 审批绑定防止旧授权用于不同对象/参数；执行前复核处理审批后的状态变化；CAS 处理最后一次检查与数据库写入之间的并发竞争。这三个步骤不能互相替代。

## 主要能力

| 能力 | 实现要点 | 对应代码 |
| --- | --- | --- |
| 双路 Skill | 确定性风险门控与只读审查分离 | [`skills/`](skills/) · [`skill_packs/`](skill_packs/) |
| 通用治理 | 权限、权威快照、审批绑定、执行复核、回执 | [`src/agent_governance/runtime.py`](src/agent_governance/runtime.py) · [`approval.py`](src/agent_governance/approval.py) |
| 领域适配 | 统一 `snapshot / assess / execute` 协议 | [`src/agent_governance/adapters/`](src/agent_governance/adapters/) |
| SAC 专业审查 | 候选计划、Validator、风险策略与确认激活边界 | [`sac_dispatch.py`](src/agent_governance/adapters/sac_dispatch.py) · [`sac_policy/`](src/agent_governance/sac_policy/) |
| 受控自进化 | 反馈归因、经验准入、受限补丁、隔离 A/B、质量门控 | [`src/agent_governance/evolution/`](src/agent_governance/evolution/) |
| 回归与示例 | pytest、资产校验、四个合成场景 | [`tests/`](tests/) · [`examples/`](examples/) |

## 快速开始

需要 **Python 3.11+**，不需要 GPU、Docker、模型权重或 API Key。以下命令在仓库根目录运行；建议先进入 Python 虚拟环境，具体见 [INSTALL.md](INSTALL.md)。

```bash
python -m pip install -e ".[dev]"

# 检查冻结 Skill 及注册表
python -m agent_governance_portfolio verify

# 运行通用配置变更示例
python -m agent_governance_portfolio demo generic_change_request

# 执行公开回归
python -m pytest -q
```

校验正常时可看到：

```text
{"REGISTRY_V3": "PASS", "REGISTRY_LEGACY": "PASS"}
```

通用配置变更示例会返回 `executed: true` 和以 `local-change:` 开头的**合成回执**。回执哈希每次可能不同，不应按字面值对照。

另外三个示例：

```bash
python -m agent_governance_portfolio demo research_workflow
python -m agent_governance_portfolio demo sac_dispatch
python -m agent_governance_portfolio demo skill_evolution
```

| 示例 | 演示内容 | 边界 |
| --- | --- | --- |
| `generic_change_request` | 配置变更、审批与状态一致性 | 内存权威状态 |
| `research_workflow` | 通用治理迁移到科研参数场景 | 合成数据，不控制设备 |
| `sac_dispatch` | SAC 风险策略与候选激活 | 合成 Backend，不运行真实 Actor |
| `skill_evolution` | 候选准入、审批晋升及回滚流程 | 仅合成基础设施，不代表真实候选已上线 |

> 需要接入其他业务？可以从 [`examples/custom_domain.py`](examples/custom_domain.py) 和 [新增领域指南](docs/09_new_domain.md) 开始。通用内核不要求了解 SOC、储能计划或其他领域专有字段。

## SAC 工程接入与实际验证

这套架构并非仅围绕内存示例设计。项目的 SAC 专业适配曾在**真实冻结 SAC Actor、监听 HTTP 服务及隔离 MySQL 8／Redis 7** 环境完成定义范围内的集成验证，覆盖候选生成、Validator、风险门控、人工确认、执行前复核与后端原子激活；业务 Profile 和遥测为合成数据，设备为 Mock，未接触真实生产用户或设备。

| 验证层次 | 结果 | 适用范围 |
| --- | --- | --- |
| 通用治理 | **330/330** | 本公开仓库可自行复现的 Python 回归 |
| SAC 专业回归与定向测试 | **88/88 + 24/24** | 历史隔离集成环境，完整私有测试代码不公开 |
| HTTP 路径与只读不变量 | **21/21** | 最终路径与状态断言；不是 21 个独立 E2E 用户任务 |

集成过程中真实处理了**重复确认返回旧错误、后端断联的非结构化失败、约束摘要遗漏，以及合法 PASS 分支缺少验证**等问题。公开运行的 SAC 示例使用合成 Backend，目的是让读者无需企业模型或数据库便能复现治理逻辑，而不代表内部真实系统从未接入。

**[阅读 SAC 隔离集成技术复盘](docs/10_sac_integration_validation.md)**（包含工作流结构图、故障原因、修复方法和测试口径）；具体领域接口见 [SAC 专业适配](docs/03_sac.md)。

## Skill 如何实现受控自进化？

传统 Skill 往往需要开发者手工阅读失败日志，再修改 Prompt。本项目把其中可结构化的部分变为一条**可审计、不可自行发布**的候选优化流程。

```text
                已完成的 Review（只读审查）
                           │
                           ▼
                 ① 质量反馈与匿名采集
                           │
                           ▼
          ② 根因判断：Prompt / 上游事实 / 工具故障
                           │
                 ┌─────────┴─────────┐
                 │                   │
          非 Skill 缺陷         可修复解释缺陷
                 │                   │
            留在问题记录             ▼
                 │           ③ 经验聚合与独立性去重
                 │                   │
                 │                   ▼
                 │           ④ LLM 提出最小 Prompt 补丁
                 │                   │
                 │                   ▼
                 │           ⑤ 白名单、父版本哈希与静态校验
                 │                   │
                 │                   ▼
                 │           ⑥ 冻结 Champion / Candidate
                 │                   │
                 │                   ▼
                 │           ⑦ 配对 A/B 与回归/保留集评测
                 │                   │
                 │                   ▼
                 │           ⑧ 质量门控
                 │           ├── REJECTED → 不发布
                 │           └── NEEDS_REVIEW
                 │                   │
                 │                   ▼
                 │           ⑨ 独立审批、版本提交与可回滚
                 │
                 └──────────→ 不改变正式 Skill
```

设计上的三个关键限制：

1. **先归因、后修改。** 如果约束在上游数据转换时已经丢失，修改 Prompt 并不能补回权威事实。错误必须先判定是否属于 Skill 可修复问题。
2. **模型只能提补丁。** 候选补丁必须引用原文件哈希、使用精确文本替换，只允许修改限定文件；风险策略、审批、后端 CAS 不属于模型可修改范围。
3. **质量改善不等于发布许可。** 候选必须经过与冻结基线的对照、回归和安全检查；质量门控通过也只会进入独立审批，不能自行替换正式 Champion。

与代码对应的完整过程、示例数据及限制见 **[受控自进化设计与实现](docs/05_evolution.md)**。

## 评测结果与证据范围

本仓库同时包含**可以在公开包中复现的工程测试**和**只提供历史摘要的真实模型实验**，两者不混算。

| 评测范围 | 结果 | 可以证明什么 |
| --- | --- | --- |
| 公开治理回归 | **330/330** | 当前公开源码与合成测试场景通过 |
| 公开示例 | **4/4** | 配置变更、科研、SAC 合成执行、自进化基础设施可运行 |
| SAC 私有回归（历史） | **88/88＋24/24** | 历史隔离系统的回归和定向测试；源码与收据未全部公开 |
| 真实模型 Review A/B（历史） | **112 对** | 冻结 Prompt 在合成调度情境下的配对比较 |

**Benchmark112 的设计：** 14 类审查机制，每类 4 组模拟物理条件，共 56 组；每组设计两种问法，形成 112 条问题。每条问题分别调用冻结的 Champion 与 Candidate，得到 224 条真实 LLM Review 回答。实验中的父计划使用模拟策略器，不是 112 次真实 SAC Actor 推理。

| 模型评审的解释覆盖 | Champion | Candidate |
| --- | ---: | ---: |
| 经济解释 | 50.89% | 94.64% |
| SOC 解释 | 55.36% | 95.54% |

**评审与质量结论：** 上表的百分比来自冻结的**模型评审覆盖率**，不是人工校准后的准确率，也不代表生产业务收益。没有可核实的人工签署记录，本版本不新增“人工验收通过”或“达到预期”的结论。换序分歧及事实性争议保持原有记录，不修改历史评分。

评测同时记录工程代价：Candidate 的回答更长，Review P95 由约 **13.58 秒增至 18.56 秒**。配对模型评审及换序复评的完整统计见 [评测设计与统计口径](docs/07_evaluation.md)。**候选改进与正式发布属于不同流程**；本次 Benchmark112 未执行正式 Candidate 晋升。

详见 [评测报告与统计边界](docs/07_evaluation.md)、[`TEST_RECEIPT.json`](TEST_RECEIPT.json)。

## 项目结构

```text
.
├── README.md                         # 项目入口、架构与快速开始
├── src/
│   ├── agent_governance/             # 通用治理运行时
│   │   ├── runtime.py                # 请求治理和执行边界
│   │   ├── policy.py / approval.py   # 风险策略和审批
│   │   ├── adapters/                 # 通用、科研、SAC 领域适配
│   │   ├── sac_policy/               # 冻结的 SAC 确定性策略
│   │   └── evolution/                # 反馈、候选、质量门控、晋升
│   └── agent_governance_portfolio/   # 无网络的可执行示例入口
├── skills/                            # 冻结 Skill 运行资产与注册表
├── skill_packs/                       # 面向阅读的 Skill 包入口
├── examples/                          # 四个合成场景及自定义适配示例
├── tests/                             # 公开回归测试
├── docs/                              # 架构、适配、演进与评测说明
└── scripts/                           # Skill 校验与资源同步
```

`skill_packs/` 用于展示标准 Skill 说明；`skills/` 保存冻结运行资产；安装所需的 `src/agent_governance_assets/` 是资源镜像，不是第三套独立业务实现。资源副本通过校验脚本检查一致性。

## 设计边界与适用范围

本项目是**治理框架与可运行参考实现**，并非完整储能生产系统。公开包不包含企业 SAC Actor 权重、真实 HTTP/数据库服务、设备通信、私有 RAG 知识、历史模型原始回答或真实客户数据。

在公开演示中，通用和科研场景使用内存状态；SAC 适配使用合成后端。实际业务必须提供**可信身份、权威事实读取和持久化原子提交**，不能把本地内存锁当成跨进程事务。LLM 只读提示也不能替代运行时能力控制。

当前源码包标记为 `4.0.0.dev5` 开发快照，未完成正式 Candidate 晋升，也未获得生产发布验收。历史系统集成证据和当前公开包可复现证据的范围见 [版本说明](VERSION_AND_SCOPE.md)。

## 文档与参考

- **架构原理：** [整体架构](docs/01_architecture.md) · [通用治理](docs/02_generic.md) · [领域适配](docs/04_adapters.md)
- **专业场景：** [SAC 调度适配](docs/03_sac.md) · **[SAC 隔离集成验证](docs/10_sac_integration_validation.md)** · [新增领域示例](docs/09_new_domain.md)
- **质量与安全：** [Skill 自进化](docs/05_evolution.md) · [威胁模型](docs/06_security.md) · [评测设计与统计口径](docs/07_evaluation.md)
- **工程使用：** [安装指南](INSTALL.md) · [安全披露](SECURITY.md) · [研究与开源参考](docs/references.md)

## 许可与发布说明

提交请求方已确认本包源码可公开，并授权提交 GitHub PR；这是公开源码提交授权，不是生产验收、正式 Candidate 晋升或 RC1 准入。原有 [LICENSE](LICENSE) 和归属保持不变，不补造权利人或授权文件；授权记录与限制见 [NOTICE.md](NOTICE.md)。
