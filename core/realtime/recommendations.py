from __future__ import annotations

from datetime import datetime

import pandas as pd

from .constants import SIMULATION_START
from .recommendation_schema import normalize_recommendation


def update_recommendation_log(state: dict, recommendations: list[dict]) -> tuple[dict, list[dict]]:
    simulation_now = state.get("simulation_now", SIMULATION_START)
    recommendation_log = dict(state.get("recommendation_log", {}))
    for recommendation in recommendations:
        recommendation_log.setdefault(recommendation["id"], simulation_now.isoformat())
    visible_recommendations = []
    retained_log = {}
    active_ids = {recommendation["id"] for recommendation in recommendations}
    by_id = {recommendation["id"]: recommendation for recommendation in recommendations}
    for recommendation_id, first_seen in recommendation_log.items():
        try:
            first_seen_dt = datetime.fromisoformat(first_seen)
        except ValueError:
            first_seen_dt = simulation_now
        if (simulation_now.date() - first_seen_dt.date()).days < 3:
            retained_log[recommendation_id] = first_seen_dt.isoformat()
            if recommendation_id in active_ids:
                visible_recommendations.append(by_id[recommendation_id])
    return {**state, "recommendation_log": retained_log}, visible_recommendations


def build_recommendations(snapshot: pd.DataFrame) -> list[dict]:
    recommendations = []
    for _, row in snapshot.iterrows():
        ward = row["Ward"]
        gaps = [
            ("assign_nurses", int(row["Nurses Required"] - row["Nurses Available"]), "Nurse coverage is below the required level."),
            ("add_doctors", int(row["Doctors Required"] - row["Doctors Available"]), "Doctor coverage is below the required level."),
            ("redeploy_ventilators", int(row["Ventilators Required"] - row["Ventilators Available"]), "Ventilator demand exceeds available equipment."),
            ("move_monitors", int(row["Monitors Required"] - row["Monitors Available"]), "Monitor demand exceeds available equipment."),
        ]
        for action_type, amount, reason in gaps:
            if amount > 0:
                recommendations.append(normalize_recommendation({"ward": ward, "action_type": action_type, "amount": amount, "priority": "high", "reason": reason}))
        peak = int(row["Predicted Peak Tomorrow"])
        capacity = int(row["Capacity"])
        if peak >= capacity:
            recommendations.append(normalize_recommendation({"ward": ward, "action_type": "trigger_bed_plan", "priority": "high", "reason": "Forecasted peak reaches ward capacity."}))
        elif peak >= int(capacity * 0.9):
            recommendations.append(normalize_recommendation({"ward": ward, "action_type": "ringfence_discharge", "priority": "medium", "reason": "Forecasted peak is near full capacity."}))
    if recommendations:
        return [recommendation for recommendation in recommendations if recommendation]
    return [normalize_recommendation({"ward": "System", "action_type": "maintain_monitoring", "priority": "low", "reason": "Coverage is within the recommended operating range."})]
