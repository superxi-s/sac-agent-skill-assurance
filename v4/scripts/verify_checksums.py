"""从包根目录检查全部资产；校验文件本身由外部 ZIP SHA256 覆盖。"""

from pathlib import Path
import hashlib

root = Path(__file__).resolve().parents[1]
listed = set()
for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
    expected, name = line.split("  ", 1)
    p = (root / name).resolve()
    assert p.is_relative_to(root.resolve()) and p.is_file(), name
    assert hashlib.sha256(p.read_bytes()).hexdigest() == expected, name
    assert name not in listed, name
    listed.add(name)
actual = {
    p.relative_to(root).as_posix()
    for p in root.rglob("*")
    if p.is_file()
    and "__pycache__" not in p.parts
    and ".pytest_cache" not in p.parts
    and p.suffix != ".pyc"
}
assert actual - {"SHA256SUMS.txt"} == listed
print(f"CHECKSUMS=PASS; FILES={len(listed)}")
