"""同步发行资源副本，或逐字节核验副本；不重算冻结注册表。"""

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅校验，不写入")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    assets = root / "src/agent_governance_assets/data"
    compared = 0
    for name in ("skills", "examples"):
        source = root / name
        target = assets / name
        originals = {
            p.relative_to(source): p
            for p in source.rglob("*")
            if p.is_file() and p.suffix != ".pyc" and "__pycache__" not in p.parts
        }
        copies = {
            p.relative_to(target): p
            for p in target.rglob("*")
            if p.is_file() and p.suffix != ".pyc" and "__pycache__" not in p.parts
        }
        if args.check:
            assert originals.keys() == copies.keys(), f"资源清单不一致：{name}"
        for relative, original in originals.items():
            destination = target / relative
            if args.check:
                assert (
                    destination.read_bytes() == original.read_bytes()
                ), f"资源内容不一致：{name}/{relative}"
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
            compared += 1
    print(
        f"RESOURCE_PARITY=PASS; FILES={compared}; MODE={'CHECK' if args.check else 'SYNC'}"
    )


if __name__ == "__main__":
    main()
