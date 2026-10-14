from agent_governance import ActionRequest, GovernanceRuntime, Policy, Principal
from agent_governance.adapters import GenericChangeAdapter


def main() -> None:
    """在内存合成对象上演示审批与执行；导入模块不会产生写入。"""
    adapter = GenericChangeAdapter()
    runtime = GovernanceRuntime(adapter, Policy("3.0.0", (adapter.action,)))
    request = ActionRequest(
        principal=Principal(
            user_id="demo-user-001", tenant_id="demo-team-001", session_id="demo"
        ),
        action=adapter.action,
        resource_type=adapter.resource_type,
        resource_id="demo-config-001",
        payload={"max_workers": 8},
        trace_id="generic-demo",
    )
    approval = runtime.approve(request)
    result = runtime.execute(request, approval.approval_id)
    print("通用配置变更已执行。" if result.executed else "通用配置变更已阻断。")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
