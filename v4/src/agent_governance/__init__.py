"""治理框架入口；业务执行由场景适配器交给权威 Backend。"""
from .models import ActionRequest, Principal, GateDecision
from .policy import Policy
from .runtime import GovernanceRuntime

__all__ = ["ActionRequest", "Principal", "GateDecision", "Policy", "GovernanceRuntime"]
