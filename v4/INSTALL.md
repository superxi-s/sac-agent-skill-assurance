# 安装与验证

Python 3.11+。无需 Docker、CUDA、模型权重或 API 密钥。

```bash
python -m pip install -e ".[dev]" build
python -m pytest -q
python scripts/validate_skills.py
python scripts/sync_assets.py --check
python -m agent_governance_portfolio verify
python -m agent_governance_portfolio demo sac_dispatch
python -m build
```

在另一个虚拟环境、源码目录之外安装 dist/ 下的实际 wheel 或 .tar.gz 文件，再运行 verify 和四个 demo。安装版读取随包资源，不依赖开发者目录。`AGENT_GOVERNANCE_SKILLS_ROOT` 是显式覆盖参数，普通展示环境不要设置；已有值不会被强制覆盖。

所有演示为合成数据；接入方须实现权威读接口、原子提交和相应基础设施，才能验证真实业务安全。
