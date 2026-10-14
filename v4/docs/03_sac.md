# SAC 专业领域适配：从通用治理到储能调度

> **阅读建议**：先看 [总体架构](01_architecture.md)，再看本页，最后看 [SAC 隔离集成验证](10_sac_integration_validation.md)。本仓库的 SAC 示例采用合成后端，可以离线运行；历史真实 Actor / HTTP / MySQL / Redis 的集成验证在独立测试环境完成，不包含于公开可执行示例。

## 1. 为什么有了通用治理，还需要 SAC 专业适配？

通用治理系统知道谁发起了什么操作、是否允许审批、执行时版本是否发生变化，却不应自行判断“96 个时段 SOC 是否合理”“最大放电功率是否超过约束”。这些是储能领域的事实和算法责任。因此业务端提供权威快照、候选可行性及原子激活；通用系统处理授权与状态一致性。

| 部分 | 负责 | 不负责 |
| --- | --- | --- |
| SAC Actor（策略网络） | 生成候选充放电计划 | 不自行批准激活 |
| Simulator / Validator | 仿真与硬约束验证 | 不替用户审批 |
| SAC 领域适配器 | 读取候选、核对风险、调用可信后端执行 | 不复写策略网络 |
| 风险门控 | PASS / REVIEW / BLOCK | 不通过生成式模型推断硬约束 |
| 只读审查 Skill | 解释成本、SOC、约束与风险 | 不修改计划或设备 |
| 治理运行时 | 审批绑定、执行前复核、状态一致性 | 不成为计划的业务事实源 |
| Backend + MySQL | 权威计划事务与原子激活 | 不由 Skill 文档代替 |

## 2. SAC 适配器真实接口

在 [`src/agent_governance/adapters/sac_dispatch.py`](../src/agent_governance/adapters/sac_dispatch.py) 中：

```python
class SACBackendAuthority(Protocol):
    def read_candidate(self, candidate_id: str) -> AuthoritySnapshot: ...
    def activate_compare_and_set(
        self, request: ActionRequest, expected: AuthoritySnapshot
    ) -> str: ...
```

`SACDispatchAdapter` 实现通用 `DomainAdapter` 接口：

- `snapshot(request)`：向后端读取当前候选的权威状态。返回的 `AuthoritySnapshot` 是业务事实投影，不应由 LLM 自行构造。
- `assess(request, authority)`：结合 SAC 专业冻结策略检查候选计划、验证结果及生命周期，产出风险决策及原因。
- `execute(request, expected)`：委托后端 `activate_compare_and_set` 执行最终提交。原子约束必须由后端完成，不能靠 Python 内存锁替代跨进程数据库事务。

这一层只接受约定的计划激活动作，不提供任意修改 PCS/BMS、直接写设备或绕过候选重规划的能力。

## 3. 真实业务中完整工作流如何走？

```text
用户提出约束：例如限制最大放电功率
        │
        ▼
SAC Agent：意图识别、约束抽取、必要时澄清
        │
        ▼
Backend：读取当前活动计划、运行 SAC Actor、生成 Candidate
        │
        ▼
Simulator / Validator：验证功率、SOC、计划血缘与约束
        │
        ▼
SACDispatchAdapter.snapshot / assess
        │
        ▼
确定性 Gate：PASS / REVIEW / BLOCK
        ├─ BLOCK：拒绝激活，提供可核验的原因
        └─ PASS / REVIEW：进入对应确认流程
                         │
                         ▼
              只读 Review：解释成本、SOC 与风险
                         │
                         ▼
              HITL：用户确认、拒绝或修改
                         │
                         ▼
              执行前读取最新 Backend 状态
                         │
                         ▼
              审批对象 / 参数 / 版本 / 策略哈希复核
                         │
                         ▼
              Backend CAS + 幂等回执
                         │
                         ▼
              MySQL ACTIVE / SUPERSEDED 状态更新
```

**PASS 不是跳过确认**：只表示在该阶段未触发风险阻断；最终计划激活仍受用户确认和后端提交边界约束。`REVIEW` 也不能由 Review LLM 擅自升级为 PASS。

## 4. 公开代码分别对应哪一部分？

| 位置 | 作用 | 可直接运行 |
| --- | --- | --- |
| [`adapters/sac_dispatch.py`](../src/agent_governance/adapters/sac_dispatch.py) | 专业适配协议与业务权限边界 | 需要 Backend 实现 |
| [`sac_policy/`](../src/agent_governance/sac_policy/) | 冻结的 SAC 风险策略与领域 Schema | 可通过单测验证 |
| [`skills/sac-plan-review/`](../skills/sac-plan-review/) | SAC 只读解释 Skill 说明 | 文档/资源包 |
| [`examples/sac_dispatch/demo.py`](../examples/sac_dispatch/demo.py) | 完全合成的 SAC 后端场景 | 是 |
| [`tests/test_v3_sac_integration.py`](../tests/test_v3_sac_integration.py) | 适配边界与治理回归 | 是 |

`skills/sac-plan-review` 是审查技能，`sac_policy` 是确定性风险策略资产；二者不能误认为同一个 Skill ID。公开演示不是企业完整 SAC 服务，也不包含真实策略网络权重。

## 5. 如何运行合成示例？

完成 `python -m pip install -e ".[dev]"` 后：

```bash
python -m agent_governance_portfolio demo sac_dispatch
python -m pytest -q tests/test_v3_sac_integration.py
```

演示使用 `LocalSACFixtureBackend` 模拟权威后端，测试治理调用顺序、权限和状态处理，不会联网访问储能设备、不使用真实账户，也不连接生产数据库。想进一步了解历史真实集成工作，参见 [`10_sac_integration_validation.md`](10_sac_integration_validation.md)。

## 6. SAC 场景推广到其他行业时，哪些可以复用？

复用 `ActionRequest`、`AuthoritySnapshot`、风险/权限框架、审批绑定、执行前复核、Skill 只读属性及自进化候选管理；替换业务后端的 `read_candidate` / `activate_compare_and_set`、领域 Schema 和硬约束评估。通用配置变更与科研工作流已有合成示例；不能据此推断已经完成其他行业生产集成。
