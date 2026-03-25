from __future__ import annotations

import pandas as pd

from .ai_recommendations import build_ai_recommendations
from .forecasting import build_history_frame, predict_tomorrow
from .recommendation_schema import normalize_recommendation
from .recommendations import build_recommendations, update_recommendation_log


def build_operational_snapshot(state: dict) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    history = build_history_frame(state)
    rows = []
    alerts = []
    for ward in state["wards"]:
        forecast = predict_tomorrow(history[history["ward"] == ward["ward"]], ward["capacity"])
        pressure = ward["occupancy_rate"]
        if pressure >= 0.9:
            alerts.append(f"{ward['ward']}: occupancy above 90%, move overflow plan to standby.")
        elif pressure >= 0.8:
            alerts.append(f"{ward['ward']}: occupancy above 80%, pre-position extra staff and discharge support.")
        rows.append({
            "Ward": ward["ward"],
            "Occupied Beds": ward["occupied_beds"],
            "Capacity": ward["capacity"],
            "Occupancy %": round(pressure * 100, 1),
            "Admissions/hr": ward["admissions_last_hour"],
            "Discharges/hr": ward["discharges_last_hour"],
            "Predicted Avg Tomorrow": forecast["predicted_avg"],
            "Predicted Peak Tomorrow": forecast["predicted_peak"],
            "Nurses Available": ward["nurses_available"],
            "Nurses Required": ward["required_nurses"],
            "Doctors Available": ward["doctors_available"],
            "Doctors Required": ward["required_doctors"],
            "Ventilators Available": ward["ventilators_available"],
            "Ventilators Required": ward["required_ventilators"],
            "Monitors Available": ward["monitors_available"],
            "Monitors Required": ward["required_monitors"],
        })
    snapshot = pd.DataFrame(rows).sort_values("Occupancy %", ascending=False)
    simulation_now = state.get("simulation_now", state["last_updated"])
    recommendations = _build_snapshot_recommendations(state, snapshot, alerts, simulation_now)
    updated_state, visible = update_recommendation_log(state, recommendations)
    state.update(updated_state)
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


def _build_snapshot_recommendations(state: dict, snapshot: pd.DataFrame, alerts: list[str], simulation_now) -> list[dict]:
    alert_items = []
    for alert in alerts:
        ward = alert.split(":", 1)[0].strip()
        action_type = "overflow_standby" if "above 90%" in alert else "preposition_staff"
        alert_items.append(
            normalize_recommendation(
                {"ward": ward, "action_type": action_type, "priority": "high", "reason": alert}
            )
        )
    fallback = [item for item in alert_items + build_recommendations(snapshot) if item]
    snapshot_key = f"{simulation_now.isoformat()}::{snapshot.to_json(orient='records')}"
    cache = state.get("recommendation_cache", {})
    if cache.get("snapshot_key") == snapshot_key:
        return cache.get("items", fallback)
    try:
        ai_items = build_ai_recommendations(snapshot, simulation_now)
    except Exception:
        ai_items = []
    items = ai_items or fallback
    state["recommendation_cache"] = {"snapshot_key": snapshot_key, "items": items}
    return items
