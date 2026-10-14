from threading import RLock

from .models import ApprovalBinding


class InMemoryApprovalStore:
    """单进程参考审批存储；生产需要持久化和原子消费。"""

    def __init__(self):
        self._bindings: dict[str, ApprovalBinding] = {}
        self._used: set[str] = set()
        self._lock = RLock()

    def put(self, binding: ApprovalBinding) -> None:
        with self._lock:
            if binding.approval_id in self._bindings:
                raise ValueError("审批记录已存在")
            self._bindings[binding.approval_id] = binding.model_copy(deep=True)

    def get(self, approval_id: str) -> ApprovalBinding:
        with self._lock:
            if approval_id in self._used or approval_id not in self._bindings:
                raise ValueError("APPROVAL_MISSING_OR_REPLAYED")
            return self._bindings[approval_id]

    def consume(self, approval_id: str) -> None:
        with self._lock:
            self.get(approval_id)
            self._used.add(approval_id)
