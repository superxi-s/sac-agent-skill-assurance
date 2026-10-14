# V4 公开精修版导入记录

## 来源与授权

源包：`Agent_Skill_Governance_V4_PUBLIC_REFINED_20261011.zip`。

ZIP SHA256：`134b4c50a0193a061a160601dd13bbba86bec1a43e8bafe5e18501254cbdd87d`。

2026-10-11，提交请求方明确确认该源码已获准公开，并授权使用 GitHub 账号 `aguaiwang` fork、提交 PR，等待仓库维护者审核合并。该记录不新增或转让版权，不修改现有 LICENSE、归属及依赖许可。`v4/` 内保留原审核包文件，包括其生成时的“授权待确认”说明；本记录补充后续用户授权事实，不把历史报告重写为当时已获授权。

## 最小破坏的版本共存

- 根目录保留 V1 的安装入口、`skill_assurance` 命名空间、源码、测试、Skill 包及 CI。
- `v4/` 完整导入精修 ZIP，使用独立的 `agent-action-governance` 分发名和 `agent_governance` 命名空间。
- V4 不是 V1 的原位升级，不承诺旧 API 无修改即可迁移；安装和测试分别在两个环境执行。
- 新增独立 V4 CI，根目录原 CI 不修改。
- 不删除、重写 Git 历史，不生成新 Candidate，不改变审批、安全门控、正式 Registry 或冻结 Prompt。

## 评测口径

V4 的 330 项公开回归、四个合成示例和两套 Registry 在 PR 提交前重新运行；具体结果见本文件后续收据。历史 SAC 私有回归、HTTP 及 Benchmark112 不在本次复跑范围，公开工程内的历史摘要不能当作本次新成绩。

正式发布、RC1 和业务生产准入仍按项目原有规则，公开授权不等于质量门控通过。合并由目标仓库维护者决定，本次只提交 PR。

## 本次提交前复验（2026-10-11）

两个独立的新建 Python 3.11 虚拟环境分别安装 V1/V4；安装依赖镜像超时后改用官方 PyPI。初次无隔离构建因新环境 setuptools 65.5.0 不满足 `>=68` 失败，补齐 setuptools/wheel 后构建成功，不修改源码或测试。

| 项目 | 实际结果 |
| --- | --- |
| V1 `python -m pytest -q` | 8 passed |
| V1 security evaluation | 52/52 |
| V1 offline trigger evaluation | 80/80；Host selector runtime未评测 |
| V4 `python -m pytest -q` | 330 passed，pytest报告8.29秒 |
| V4 Registry V3 / Legacy | PASS / PASS |
| V4 Skill入口校验 | 3个入口通过 |
| V4安装资源副本 | 14文件逐字节一致 |
| V4合成示例 | SAC、通用变更、科研、自进化4/4通过 |
| 额外领域适配示例 | PASS |
| V4 wheel / sdist | 构建成功 |
| 源ZIP内容 | 141个文件逐字节一致 |
| Git暂存导出后的内部checksum | 140/140，校验清单自身由源ZIP SHA覆盖 |
| 本次新增内容密钥/真实开发者路径格式扫描 | 未发现命中；不是完整法律或隐私审计 |

测试产生的缓存、egg-info、构建产物及临时合成Candidate未提交；V1测试生成的结果文件恢复到原Git版本，不覆盖历史收据。

冻结源包 `risk_models.py` 自带一个文件末尾空行，默认 `git diff --check` 提示该既有格式问题；为保持源包字节与冻结哈希，不修改该文件。排除 `blank-at-eof` 后的差异检查通过，无其他空白问题。V4公开包原有技术扫描的精确负向测试例外原样保留。

不申请正式Candidate晋升，不执行生产操作，不生成新的真实模型回答。远程GitHub Actions由PR触发，其结果与上述本地结果分开看待。

## 2026-10-12：中性用例与展示文档修订

源包：`Agent_Skill_Governance_V4_PUBLIC_NEUTRAL_CASES_20261012.zip`；SHA256：`3c37609e42f44dcbb03ee1a20bbcdc6f0717da54689fa75860dbd94717dc7dc7`。仍为4.0.0.dev5，不升dev6，不改变正式晋升门槛。

相对前一源包：新增2文件、删除3文件、修改14文件，124文件不变。主要是README、架构、自进化、SAC隔离集成复盘与评测说明；88条声明用例改名、移除审核字段，测试改用新路径并验证无人工审核仍为HOLD。case_id、text、authority、expected_label及text_sha256保持一致，不修改Gold业务内容或历史评分。

提交前仅额外修正公开声明：说明fixture确有Schema变动；保留AI草拟且未经人工校准的制作来源；去掉无审核记录支持的人工质量结论；对齐用户已经确认的公开授权。对应文档的发布checksum重新计算；冻结Registry、Skill包哈希和生产代码不变。

本修订在既有独立Python3.11测试环境再次运行330项pytest（330 passed，8.68秒）、四个合成示例、额外领域示例、两套Registry、3个Skill入口及14份资源副本，全部通过。此前分析阶段另在新建Python3.11环境从该源ZIP复验330/330、4/4、Registry、CRC、139项checksum及84个本地链接。未重跑私有SAC回归、HTTP或Benchmark112，未重新声明生产或RC1通过。

旧版根目录V1、CI与Git历史保留。原公开文件处置说明、简短历史页以及旧名fixture从当前v4目录移出，前一提交和原ZIP仍可追溯；不覆盖历史实验原件。生成的缓存、构建产物和临时合成实验文件均不提交。
