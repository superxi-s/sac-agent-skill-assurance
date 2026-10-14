import re
import stat
from pathlib import Path, PurePosixPath

from .models import MutationScope


def allowed(path: str, scope: MutationScope) -> bool:
    if not path or "\\" in path or ":" in path or "\x00" in path:
        return False
    value = PurePosixPath(path)
    if value.is_absolute() or any(part in {"", ".", ".."} or part.startswith(".") for part in value.parts):
        return False
    if value.as_posix() != path:
        return False
    # 调用方配置不能将任意 Python/registry 路径加入候选允许范围。
    fixed = {"SKILL.md", "prompt.md", "workflow.yaml"}
    if path in fixed:
        return path in scope.allowed_files
    return scope.allow_references and bool(re.fullmatch(r"references/[A-Za-z0-9_-]+\.md", path))


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def files(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or any(is_link(path) for path in (root, *root.parents)):
        raise ValueError("资产根目录必须是普通目录")
    values = {}
    def visit(directory):
        for path in directory.iterdir():
            if is_link(path):
                raise ValueError("资产不能包含符号链接或目录联接")
            if path.name.startswith("."):
                raise ValueError("资产不能包含隐藏文件或目录")
            if path.is_dir():
                visit(path)
            elif path.is_file():
                values[path.relative_to(root).as_posix()] = path.read_bytes()
            else:
                raise ValueError("资产包含特殊文件")
    visit(root)
    return dict(sorted(values.items()))
