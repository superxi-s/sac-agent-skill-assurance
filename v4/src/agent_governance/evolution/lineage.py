import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .scope import is_link


def safe_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if any(is_link(item) for item in (path, *path.parents)):
        raise ValueError("私有资产目录不能经链接解析")


@contextmanager
def registry_lock(root: Path):
    safe_directory(root)
    path = root / "registry.lock"
    try:
        with path.open("xb") as stream:
            stream.write(b"locked")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("REGISTRY_BUSY") from exc
    try:
        yield
    finally:
        path.unlink()


def atomic_json(path: Path, value: dict) -> None:
    safe_directory(path.parent)
    if path.exists() and is_link(path):
        raise ValueError("registry 不能是链接")
    temporary = path.parent / (uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_json(path: Path) -> dict:
    if is_link(path):
        raise ValueError("registry 不能是链接")
    return json.loads(path.read_text(encoding="utf-8"))
