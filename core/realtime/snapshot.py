from __future__ import annotations

import pandas as pd

from .manager_agent import build_manager_snapshot, run_manager_agent_cycle


def build_operational_snapshot(state: dict) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    snapshot, history, alerts = build_manager_snapshot(state)
    simulation_now = state.get("simulation_now", state["last_updated"])
    updated_state, visible, applied = run_manager_agent_cycle(state, snapshot, alerts, simulation_now)
    state.update(updated_state)
    if applied:
        snapshot, history, _ = build_manager_snapshot(state)
    return snapshot, history, visible


def build_system_totals(snapshot: pd.DataFrame) -> dict[str, float]:
    occupied = int(snapshot["Occupied Beds"].sum())
    capacity = int(snapshot["Capacity"].sum())
    return {
        "occupied": occupied,
        "capacity": capacity,
        "available": capacity - occupied,
        "occupancy_pct": round((occupied / capacity) * 100, 1) if capacity else 0.0,
        "predicted_avg": int(snapshot["Predicted Avg Tomorrow"].sum()),
        "predicted_peak": int(snapshot["Predicted Peak Tomorrow"].sum()),
    }
