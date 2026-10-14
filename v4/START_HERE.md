# 建议的阅读与运行顺序

面向第一次接触本项目的读者，先看 [README](README.md) 的总架构与核心能力，再按以下顺序：

1. [完整架构](docs/01_architecture.md)：为什么要将模型解释与业务授权分开。
2. [SAC 专业适配](docs/03_sac.md) 与 [隔离集成验证](docs/10_sac_integration_validation.md)：理解真实业务接入和公开合成示例的差别。
3. [Skill 受控自进化](docs/05_evolution.md)：反馈、归因、受限补丁、A/B、质量门控和审批。
4. [评测与证据边界](docs/07_evaluation.md)：哪些结果可公开复现，哪些只有历史摘要。
5. [安装指南](INSTALL.md)：运行 pytest、Skill 校验及四个合成示例。

需要接入新的行业场景时，参见 [领域适配器](docs/04_adapters.md) 与 [自定义领域示例](docs/09_new_domain.md)。

当前交付仍为待授权的开发快照。完整源代码在权属确认前不能公开分发，见 [NOTICE.md](NOTICE.md)。
