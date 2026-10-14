# 依赖许可核对

本轮读取实际新环境中的已安装发行包元数据，不依据记忆推测。直接运行依赖：Pydantic 2.14.0（MIT）、PyYAML 6.0.3（MIT）。

| 依赖 | 实测版本 | 元数据许可 |
| --- | --- | --- |
| pydantic_core | 2.50.0 | MIT |
| annotated-types | 0.8.0 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| pytest | 9.1.1 | MIT |
| pluggy | 1.6.0 | MIT |
| iniconfig | 2.3.1 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| colorama | 0.4.6 | BSD（分类字段未指定条款数） |
| build | 1.6.1 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pyproject_hooks | 1.3.3 | MIT |

环境自带 pip 22.3.1 与 setuptools 65.5.0 分类为 MIT；实际隔离构建安装 setuptools 84.0.0，构建收据保留该版本。DEPENDENCIES_FROZEN.txt 保存测试环境版本，pyproject.toml 声明兼容范围。

本包不捆绑这些第三方库的源码或二进制。项目自身保留基线 LICENSE，wheel 的 License-File 为 LICENSE；没有凭依赖开源许可推断公司源码授权。安装方应保留第三方发行包原许可，部署时仍须审查变更版本。
