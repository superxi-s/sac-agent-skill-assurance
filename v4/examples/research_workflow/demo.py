from agent_governance import ActionRequest, GovernanceRuntime, Policy, Principal
from agent_governance.adapters import ResearchWorkflowAdapter


def main() -> None:
    """仅演示合成科研参数审批，不连接实验设备。"""
    adapter = ResearchWorkflowAdapter()
    runtime = GovernanceRuntime(adapter, Policy("3.0.0", (adapter.action,)))
    request = ActionRequest(
        principal=Principal(
            user_id="demo-researcher-001", tenant_id="demo-team-001", session_id="demo"
        ),
        action=adapter.action,
        resource_type=adapter.resource_type,
        resource_id="demo-experiment-001",
        payload={"scan_rate": 1, "temperature": 25, "duration": 10},
        trace_id="research-demo",
    )
    approval = runtime.approve(request, review_acknowledged=True)
    print("仅为适配示例，未接入真实 XRD/SEM 或设备。")
    result = runtime.execute(request, approval.approval_id)
    print("合成实验参数变更已执行。" if result.executed else "合成实验参数变更已阻断。")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
