# Skill 受控自进化：设计、数据流和发布边界

> 本文解释公开源码中的真实实现。示例仅用合成数据；历史 Benchmark112 是独立的真实模型实验，不能当作当前公开示例重新运行的结果。

## 1. 为什么需要自进化？

治理运行时能够约束高风险操作，但一个只读 Review Skill 仍可能在解释方面遗漏关键内容：只复述成本差值而不说变化方向、不解释 SOC 差异、没有明确说明候选尚待审批。直接把失败对话交给 LLM 重写整个 Skill 会带来错误归因、信息泄露、过拟合和修改安全约束的风险。

因此本项目选择“收集质量反馈 → 找到可修复缺陷 → 生成有限 Prompt 补丁 → 评测 → 独立治理审批”的路线。目标是改善解释能力，不是让模型拥有修改执行权限。

## 2. 一张图看懂完整流程

```text
只读 Review 输出
      │
      ▼
质量评分（内容是否完整、事实是否有依据、是否假称已执行）
      │
      ▼
匿名反馈与失败归因
      ├── 上游权威事实缺失 ──→ 修数据契约，不进入 Prompt 迭代
      ├── 工具/服务故障 ──────→ 修工具或运行时，不进入 Prompt 迭代
      └── 可修复解释缺陷
                 │
                 ▼
        按失败签名聚合，去重独立来源
                 │
            准入门槛满足？
           ┌─────┴─────┐
           │否         │是
           ▼           ▼
        继续积累    提取结构化经验
                       │
                       ▼
              LLM 提出局部 Prompt 补丁
                       │
                       ▼
              父版本哈希 + 白名单 + 静态校验
                       │
                       ▼
              隔离 Candidate 与冻结 Champion
                       │
                       ▼
              目标/回归/保留集 A/B 评测
                       │
                       ▼
              QualityGate（质量门控）
                 ├── REJECTED → 留存失败证据
                 └── NEEDS_REVIEW
                       │
                       ▼
              独立审批后才可晋升或回滚
```

## 3. 从反馈到可修复经验

### 3.1 质量维度

`src/agent_governance/evolution/review_quality.py` 与 `review_quality_v2.py` 负责 Review 质量维度。项目区分约束说明、费用收益、SOC、候选比较、事实证据、人工确认、假执行成功等信号。**某个维度被模型评分为缺失，只是反馈证据，不等于已确认根因。**

### 3.2 反馈如何保存

`feedback.py` 的 `ReviewFeedbackCollector` 把匿名结果写入调用方指定的私有 SQLite 目录（`feedback.sqlite3`）。它禁止反馈目录位于公开工程内，按照目标 Skill、版本哈希、来源、数据分区和失败签名分桶。

对同一失败簇进行增量更新，而不是每次扫描全部历史材料。用户选择“拒绝候选”不直接等于 Skill 缺陷；只有明确的纠正或符合评分逻辑的可修复解释失败才进入候选范围。

### 3.3 为什么进行独立来源去重

同一个调度方案可能产生多种近义问题。若把这些重复提问当成完全独立的证据，会放大单个问题的权重。`experience.py` 聚合不同 `observation_id`，默认 `min_support=3`，并检查失败类别与训练分区。

经验并不是原始聊天文本，而是可追溯的结构化记录，包括：目标 Skill、失败签名、观察到的问题、预期行为、建议改动范围、支持来源与样本分区。

### 3.4 分区隔离

`split.py` 和反馈准入逻辑区分开发、回归和保留集。回归/保留集不能反向进入候选提示词生成。评测分数若被用于训练，再声称它是独立泛化成绩，就会产生数据泄漏。

## 4. 生成候选：为什么只做受限 Prompt 补丁

`candidate.py` 生成候选时，输入包含冻结 Champion 快照、已准入经验和允许修改的范围。LLM 提出的补丁需要指定：

- `path`：允许修改的文件路径；
- `original_hash`：目标原文件内容哈希；
- `before` 与 `after`：需要精确替换的旧、新文本；
- `reason` 和关联的经验来源。

旧文本需要唯一匹配；文件哈希必须匹配；修改只能发生在白名单文件中。`validator.py` 继续验证路径、链接、文件大小、Skill 包结构、只读工作流和受保护资产。

**文件级校验不等于操作系统沙箱。** 项目并不把模型生成的任意 Python 代码作为可信执行资产。面试时不要把“有白名单”说成能阻挡全部供应链攻击。

## 5. Candidate 如何验证：冻结配对 A/B

先固定 Champion 与 Candidate 的 Prompt 与哈希，再让它们处理相同的业务输入；评测同时关注解释覆盖、事实支持、安全声明、长度、延迟和负迁移。项目保留模型评审结果及换序分歧，不把 Judge 结果当成人工真值。

历史 Benchmark112：14 类机制 × 每类 4 组模拟物理条件 × 每组 2 问 = 112 条问题，每条分别调用两版 Prompt，共 224 条真实 LLM Review。按 56 组共享业务条件进行家族级重采样，避免把同组两个问题当成完全独立样本。

| 模型评审项 | Champion | Candidate |
| --- | ---: | ---: |
| 经济解释覆盖 | 57/112（50.89%） | 106/112（94.64%） |
| SOC 解释覆盖 | 62/112（55.36%） | 107/112（95.54%） |
| Review P95 | 约 13.58 秒 | 约 18.56 秒 |

候选输出更长；28 对反序复评仅 17 对结论一致，且存在事实性自动评分争议。没有可核实的人工签署记录，本版不新增人工质量结论；这些分歧仍需与事实和安全核验分开判断。因此**不能说 Candidate 已全面优于 Champion，更不能说生产效果提高了 40%**。

## 6. 质量门控、独立审批与回滚

`quality_gate.py` 要求 `target`、`regression`、`heldout` 套件完整，安全回归、越权动作、错误成功声明等约束没有出现，并检查目标增益和回归退化。门控结果为：

- `REJECTED`：候选无资格晋升。
- `NEEDS_REVIEW`：通过程序性准入检查，但仍然**需要审批**，不是自动上线。

`promotion.py` 的 `SkillPromotionAdapter` 通过可信评测提供者、审批绑定和 Registry 版本比对完成隔离晋升/回滚。回滚也需要新的审批。公开演示的 Registry 是合成隔离环境，不能混同于正式业务 Registry。

**真实状态：Benchmark112 的 Candidate 没有走正式质量门控晋升，也没有在生产发布。** 当前公开 `skill_evolution` 示例只验证合成基础设施路径。

## 7. 怎么自己验证

先完成安装（参见项目根目录 `INSTALL.md`），再在仓库根目录运行：

```bash
python -m agent_governance_portfolio demo skill_evolution
python -m pytest -q tests/test_evolution.py tests/test_evolution_promotion.py
```

合成示例会输出 `SYNTHETIC_INFRASTRUCTURE_ONLY`，显示候选准入、审批、隔离晋升和回滚的结果。不能据此推断本次 Benchmark112 Candidate 已正式晋升。

## 8. 与外部研究的关系

本项目的反馈—候选—验证设计与 GEPA 的“用反思发现提示改进”思想有相似之处；但没有实现 GEPA 的完整搜索与最优选择算法。它也不是 DSPy MIPROv2 的贝叶斯优化实现。研究链接及差异见 [`references.md`](references.md)。

## 9. 源码导航

| 模块 | 文件路径 |
| --- | --- |
| 质量评分 | `src/agent_governance/evolution/review_quality.py`、`review_quality_v2.py` |
| 匿名反馈 | `src/agent_governance/evolution/feedback.py` |
| 失败归因 | `src/agent_governance/evolution/attribution.py` |
| 独立经验 | `src/agent_governance/evolution/experience.py` |
| 数据分区 | `src/agent_governance/evolution/split.py` |
| 补丁生成 | `src/agent_governance/evolution/candidate.py` |
| 静态校验 | `src/agent_governance/evolution/validator.py` |
| 评测与质量门控 | `src/agent_governance/evolution/evaluator.py`、`quality_gate.py` |
| 晋升与回滚 | `src/agent_governance/evolution/promotion.py`、`lineage.py` |

更多评测限制见 [`07_evaluation.md`](07_evaluation.md)，项目权属与发布范围见根目录 [`NOTICE.md`](../NOTICE.md)。

## 10. 一条完整的自进化案例（教学示意，不伪装成原始模型收据）

下面把“解释了收益数字，却没说明变化方向”这一类缺陷走一遍。字段是为了说明代码职责而整理的**合成示例**，不等同于 Benchmark112 原始日志。

```text
输入事实：现有计划与候选计划的费用比较
问题：为什么限制功率后费用变化？
旧 Review：只复述 cost_delta，没有明确解释方向
                       │
                       ▼
① ReviewQualityScorer：发现 cost_benefit_explanation 缺失
                       │
                       ▼
② ReviewFeedbackCollector：匿名持久化、按 Skill 与失败签名分桶
                       │
                       ▼
③ ExperienceStore / mine：汇总不同来源、检查最小支持数
                       │
                       ▼
④ distill_cluster：抽出 symptom、expected_behavior、修改范围
                       │
                       ▼
⑤ candidate.propose：提供 Champion、文件哈希、经验、MutationScope
                       │
                       ▼
⑥ 模型返回：parent_hash + path + original_hash + before/after
                       │
                       ▼
⑦ apply_bound_patch / validate_candidate：只改准入文件，检查冻结核心
                       │
                       ▼
⑧ target / regression / heldout：对照收益、事实性、安全与延迟
                       │
                       ▼
⑨ QualityGate：REJECTED 或 NEEDS_REVIEW
                       │
                       ▼
⑩ PromotionAdapter：只有另行审批才能更新隔离注册表
```

对于模型输出的 `before`/`after`，不能用随意模糊搜索覆盖整段 Skill：`apply_bound_patch` 要求原文件 SHA256 匹配且待替换文本恰好出现一次。如果父版本已经变化，需要重新生成补丁，不能无视冲突继续覆盖。

### 一个简化的补丁形状

```json
{
  "parent_hash": "<champion_package_sha256>",
  "patches": [
    {
      "path": "prompt.md",
      "original_hash": "<prompt_sha256>",
      "before": "只复述已提供的费用差异。",
      "after": "说明费用变化方向，并标注缺少归因证据时不能推断原因。",
      "reason": "补齐经济变化说明，保留事实约束",
      "experience_ids": ["<admitted_experience_id>"]
    }
  ],
  "rationale": "只更新只读解释规则"
}
```

注意：实际 `propose()` 还会向模型传入 `previous_trials`、`mutation_scope` 和原文件哈希映射；模型无法通过提出 `tool_calls` 直接执行补丁。

## 11. 一次反馈为什么不能直接触发改写？

`ReviewFeedbackCollector.min_support = 3`，但“至少三个支持”是**普通失败经验的准入门槛**，不是“三句相似用户话语就算三个独立案例”。评估时还要核对观察记录、签名、任务分区和真实根因。高风险近失事件在底层 `mine()` 中有单独特殊处理，但不能因此宣称任何单例都可自动上线。

### 两类最容易误归因的事件

**例一：约束丢失。** 用户限制 0.5kW，后端结构化事实里存在该约束，但解释上下文的投影漏了字段。归因应该是数据适配缺陷，修复字段转换，**不是**给 Prompt 加一句“必须解释 0.5kW”。

**例二：HTTP 500。** 后端断联，模型无法拿到新鲜状态。这不是 LLM 表达能力不足，而是服务和异常契约问题，应返回可读的失败原因并阻断高风险提交。

这两种情况如果错误纳入 Prompt 演进，会让候选看起来解释更多，却依然没有真实业务事实。

## 12. 代码检查顺序与审查建议

对于阅读源码的开发者，建议从下面的调用顺序逐个设置断点：

```text
review_quality.ReviewQualityScorer.score
    ↓
feedback.ReviewFeedbackCollector.collect / human_feedback
    ↓
feedback.ReviewFeedbackCollector.states
    ↓
experience.mine / distill_cluster
    ↓
feedback.ReviewFeedbackCollector.generate_ready
    ↓
candidate.propose / apply_bound_patch / build_candidate
    ↓
validator.validate_candidate
    ↓
evaluator / quality_gate.decide
    ↓
promotion.SkillPromotionAdapter + GovernanceRuntime
```

每一步要回答四个问题：**输入是什么、哪些字段受到校验、失败是否阻断后续步骤、是否可能触碰正式业务状态**。自进化链路的主要难点在于归因、数据独立性及修改权限控制，而不只是让模型输出更长的文字。

从工程实践看，评测结果不应只记录赢或输；还要留下 Candidate 来源经验、修改文件、父哈希、测试套件、风险变化及版本谱系，才能解释下一次迭代为什么合理。历史 Benchmark112 的候选没有正式晋升，所以本仓库不会写出“线上已自动优化”的结论。
