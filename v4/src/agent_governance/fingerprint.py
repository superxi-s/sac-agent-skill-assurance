import hashlib
import json

from pydantic import BaseModel


def fingerprint(value: BaseModel | dict) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def request_fingerprint(request) -> str:
    # trace/context 不属于执行参数；会话属于身份绑定。
    return fingerprint({
        "principal": request.principal.model_dump(), "action": request.action,
        "resource_type": request.resource_type, "resource_id": request.resource_id,
        "payload": request.payload,
    })
