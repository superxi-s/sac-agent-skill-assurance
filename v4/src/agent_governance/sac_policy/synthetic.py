"""按结构生成一份合成候选，不包含历史业务记录或评测输入。"""


def valid_replan() -> dict:
    metrics = {"daily_cost_eur": 0.0, "saving_eur": 0.0,
               "total_charge_kwh": 0.0, "total_discharge_kwh": 0.0}
    schedule = [dict(index=index, time=f"{index // 4:02d}:{index % 4 * 15:02d}",
        load_kw=0.0, pv_kw=0.0, price_eur_kwh=0.0, soc_before=0.6,
        raw_action=0.0, decision="idle", power_kw=0.0, soc_after=0.6,
        baseline_cost_eur=0.0, optimized_cost_eur=0.0, saving_eur=0.0, reason_codes=[])
        for index in range(96)]
    candidate = dict(schema_version="v2", plan_id="demo-plan-001", user_id="demo-user-001",
        operating_date="2026-09-07", data_mode="historical_replay", version=2,
        source="constraint_replan", status="PENDING_APPROVAL", root_sac_plan_id="demo-active-001",
        parent_plan_id="demo-active-001", forecast_snapshot_id="demo-forecast-001",
        runtime_constraint_snapshot_id="demo-runtime-001", valid_until="2099-12-31T23:59:59Z",
        summary=dict(initial_soc=0.6, final_soc=0.6, total_charge_kwh=0.0,
            total_discharge_kwh=0.0, baseline_cost_eur=0.0, optimized_cost_eur=0.0, saving_eur=0.0),
        schedule=schedule)
    return dict(request_id="demo-request-001", policy_result=dict(allowed=True, status="ALLOWED"),
        current_active_plan_id="demo-active-001", candidate_plan=candidate,
        validation_result=dict(feasible=True, status="PASS", reason_codes=[], violations=[]),
        comparison=dict(root_sac_plan_id="demo-active-001", parent_plan_id="demo-active-001",
            revised_plan_id="demo-plan-001", parent_metrics=dict(metrics), revised_metrics=dict(metrics),
            delta={**metrics, "changed_windows": []}),
        forecast_snapshot_id="demo-forecast-001", runtime_constraint_snapshot_id="demo-runtime-001")
