"""包内入口声明；由固定哈希的 V2 运行时执行。"""
from __future__ import annotations
from typing import Any

def evaluate(payload: dict[str, Any], **_: Any) -> dict[str, Any]:
    return {"declared": True, "stage": payload.get("stage")}
