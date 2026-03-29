from __future__ import annotations

from datetime import datetime

import pandas as pd

from .ai_recommendations import build_ai_recommendations
from .forecasting import build_history_frame, predict_tomorrow
from .recommendation_actions import apply_recommendation_action
from .recommendation_schema import normalize_recommendation
from .recommendations import build_recommendations, update_recommendation_log

MANAGER_LOG_LIMIT = 120


def build_manager_snapshot(state: dict) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
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
        rows.append(
            {
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
            }
        )
    snapshot = pd.DataFrame(rows).sort_values("Occupancy %", ascending=False)
    return snapshot, history, alerts


def run_manager_agent_cycle(
    state: dict,
    snapshot: pd.DataFrame,
    alerts: list[str],
    simulation_now: datetime,
) -> tuple[dict, list[dict], bool]:
    recommendations = _build_manager_recommendations(state, snapshot, alerts, simulation_now)
    updated_state, visible = update_recommendation_log(state, recommendations)
    manager_state = dict(updated_state.get("manager_agent", {}))
    snapshot_key = f"{simulation_now.isoformat()}::{snapshot.to_json(orient='records')}"
    if manager_state.get("last_cycle_key") == snapshot_key:
        manager_state["last_visible"] = visible
        updated_state["manager_agent"] = manager_state
        return updated_state, visible, False

    updated_state = _append_manager_log(updated_state, recommendations, simulation_now, "recommended")
    applied = False
    applied_ids = []
    if manager_state.get("enabled", True) and manager_state.get("mode", "auto") == "auto":
        actionable = _dedupe_recommendations(
            recommendation for recommendation in visible if recommendation["action_type"] != "maintain_monitoring"
        )
        for recommendation in actionable:
            updated_state, message = apply_recommendation_action(updated_state, recommendation)
            updated_state = _append_manager_log(
                updated_state,
                [recommendation],
                simulation_now,
                "applied",
                message=message,
            )
            applied_ids.append(recommendation["id"])
            applied = True

    manager_state = dict(updated_state.get("manager_agent", {}))
    manager_state.update(
        {
            "enabled": manager_state.get("enabled", True),
            "mode": manager_state.get("mode", "auto"),
            "last_cycle_key": snapshot_key,
            "last_run_at": simulation_now.isoformat(),
            "last_recommendation_count": len(visible),
            "last_applied_ids": applied_ids,
            "last_visible": visible,
            "last_summary": _build_manager_summary(visible, applied_ids),
        }
    )
    updated_state["manager_agent"] = manager_state
    return updated_state, visible, applied


def _build_manager_recommendations(
    state: dict,
    snapshot: pd.DataFrame,
    alerts: list[str],
    simulation_now: datetime,
) -> list[dict]:
    alert_items = []
    for alert in alerts:
        ward = alert.split(":", 1)[0].strip()
        action_type = "overflow_standby" if "above 90%" in alert else "preposition_staff"
        alert_items.append(
            normalize_recommendation(
                {"ward": ward, "action_type": action_type, "priority": "high", "reason": alert}
            )
        )
    fallback = _dedupe_recommendations(item for item in alert_items + build_recommendations(snapshot) if item)
    snapshot_key = f"{simulation_now.isoformat()}::{snapshot.to_json(orient='records')}"
    cache = state.get("recommendation_cache", {})
    if cache.get("snapshot_key") == snapshot_key:
        return cache.get("items", fallback)
    try:
        ai_items = build_ai_recommendations(snapshot, simulation_now)
    except Exception:
        ai_items = []
    items = _dedupe_recommendations(ai_items or fallback)
    state["recommendation_cache"] = {"snapshot_key": snapshot_key, "items": items}
    return items


def _dedupe_recommendations(recommendations) -> list[dict]:
    deduped = []
    seen = set()
    for recommendation in recommendations:
        recommendation_id = recommendation["id"]
        if recommendation_id in seen:
            continue
        seen.add(recommendation_id)
        deduped.append(recommendation)
    return deduped


def _append_manager_log(
    state: dict,
    recommendations: list[dict],
    simulation_now: datetime,
    event: str,
    message: str = "",
) -> dict:
    log = list(state.get("manager_decision_log", []))
    for recommendation in recommendations:
        log.append(
            {
                "timestamp": simulation_now.isoformat(),
                "event": event,
                "ward": recommendation["ward"],
                "action_type": recommendation["action_type"],
                "amount": recommendation.get("amount", 0),
                "priority": recommendation.get("priority", "medium"),
                "source": recommendation.get("source", "rules"),
                "reason": recommendation.get("reason", ""),
                "message": message,
                "recommendation_id": recommendation["id"],
            }
        )
    return {**state, "manager_decision_log": log[-MANAGER_LOG_LIMIT:]}


def _build_manager_summary(recommendations: list[dict], applied_ids: list[str]) -> str:
    if not recommendations:
        return "Manager agent is monitoring hospital flow with no active interventions."
    if not applied_ids:
        return f"Manager agent reviewed {len(recommendations)} recommendation(s) and held position."
    return (
        f"Manager agent reviewed {len(recommendations)} recommendation(s) and auto-applied "
        f"{len(applied_ids)} action(s)."
    )
