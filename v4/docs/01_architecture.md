# 架构设计：让 Agent 有能力，但不自行获得授权

Agent Skill Governance 的核心不是“多写几个 Skill”，而是明确**业务事实来源、风险决策、人工审批与最终提交**分别由谁负责。通用运行时不理解 SAC 的 SOC、功率或 96 点计划；专业领域适配器负责把这些事实转换成可治理的结构化请求。

## 1. 完整模块图

```text
                  ┌──────────────────────────────┐
                  │        宿主 Agent             │
                  │  理解任务 / 组织工具调用      │
                  └─────────────┬────────────────┘
                                │ ActionRequest
                                ▼
                  ┌──────────────────────────────┐
                  │     Skill 加载与契约校验      │
                  ├──────────────┬───────────────┤
                  │ 确定性 Risk  │  只读 Review  │
                  │ Gate         │  Skill        │
                  └──────┬───────┴──────┬────────┘
                         │              │
                         │ Gate 决策    │ 解释与建议（不授权）
                         ▼              ▼
        ┌────────────────────────────────────────────┐
        │           GovernanceRuntime                │
        │                                            │
        │  主体/租户/资源/版本                         │
        │            ↓                               │
        │  权限与策略判定、权威事实核验                 │
        │            ↓                               │
        │  审批绑定、状态新鲜度、执行前复核             │
        │            ↓                               │
        │  调用可信 DomainAdapter.execute             │
        └────────────────────┬───────────────────────┘
                             │
           ┌─────────────────┼────────────────┐
           ▼                 ▼                ▼
      通用变更适配器      科研工作流适配器   SAC 调度适配器
           │                 │                │
           └───────────────┬─┴────────────────┘
                           ▼
               当前权威事实与原子提交
                           │
                           ▼
                    结构化执行回执
```

这里将 Skill 的专业操作说明与运行时的机器约束分开：加载 Skill 不等于获得执行能力，Review 输出不能覆盖真实 Validator，也不能绕过治理运行时。

## 2. 核心组件职责与源码位置

| 组件 | 职责 | 代码位置 |
| --- | --- | --- |
| `ActionRequest` | 描述操作主体、动作、资源和参数 | `src/agent_governance/models.py` |
| `GovernanceRuntime` | 校验策略、审批，复核后执行 | `src/agent_governance/runtime.py` |
| 策略与审批 | 能力边界、审批绑定和消费 | `src/agent_governance/policy.py`、`approval.py` |
| `DomainAdapter` | 读取权威快照、进行专业判断、原子执行 | `src/agent_governance/adapters/` |
| SAC 风险策略 | 调度候选的冻结确定性校验 | `src/agent_governance/sac_policy/` |
| 受控自进化 | 反馈、经验、补丁、对照、晋升 | `src/agent_governance/evolution/` |

`DomainAdapter` 对外约定为：

```python
snapshot(request) -> AuthoritySnapshot
assess(request, authority) -> tuple[GateDecision, tuple[str, ...]]
execute(request, expected) -> str
```

接入方必须在 `execute()` 所调用的**权威存储事务**中验证 `expected`；公开配置与科研示例的内存锁只适合单进程演示。

## 3. 为什么需要两种 Skill

确定性 `action-risk-gate` 处理能不能继续，要求结果可重复、可以测试、不受模型措辞影响。只读 `action-review` 处理为什么这样判断，允许解释候选差异、约束和已验证证据，却不拥有 `activate`、直接数据库写或设备控制权限。SAC 的 `sac-plan-review` 在同一原则下增加储能领域专用说明。

Skill 源码存放于 `skills/` 中的冻结版本，`skill_packs/` 提供清晰的阅读入口，二者是角色不同的资产，不代表两套不同的治理内核。

## 4. 一次计划确认为什么要检查两次

候选在生成时已经校验合法，用户可能在几分钟后才确认。这期间原有活动计划、约束或状态版本可能改变。审批绑定的是当时特定主体、资源和参数；执行前必须重新读取当前事实，并在最终提交时通过 CAS 阻断并发状态漂移。

这个设计解决检查时与执行时不一致（TOCTOU），但不能代替实际部署的身份认证、事务存储、权限隔离和运维安全措施。公开版本不提供完整企业 Backend 或真实 SAC Actor。

## 5. 自进化为何仍受治理

自进化组件只允许对经过准入的解释类问题提出限定 Prompt 修改，并通过冻结 A/B、回归与独立审批约束修改。它不会修改已经钉扎的安全 Gate、审批器或业务执行实现，也不会因为模型评审认为“更好”就自动发布。

完整流程、程序对应关系与 Benchmark112 的证据范围见 [受控自进化](05_evolution.md) 和 [评测说明](07_evaluation.md)。
