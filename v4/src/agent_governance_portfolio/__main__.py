"""无网络、无密钥的发行版验证入口。"""

import argparse
import json
import runpy
from importlib.resources import files
from . import configure_assets, verify


def main() -> None:
    parser = argparse.ArgumentParser(description="公开包验证与合成演示")
    parser.add_argument(
        "command", choices=["verify", "demo"], help="校验冻结注册表，或运行合成示例"
    )
    parser.add_argument(
        "example",
        nargs="?",
        choices=[
            "sac_dispatch",
            "generic_change_request",
            "research_workflow",
            "skill_evolution",
        ],
        help="合成示例名称；不调用真实模型或设备",
    )
    args = parser.parse_args()
    configure_assets()
    if args.command == "verify":
        print(json.dumps(verify()))
        return
    if not args.example:
        parser.error("demo 需要指定合成示例名称")
    verify()
    path = files("agent_governance_assets").joinpath(
        "data", "examples", args.example, "demo.py"
    )
    runpy.run_path(str(path), run_name="__main__")


if __name__ == "__main__":
    main()
