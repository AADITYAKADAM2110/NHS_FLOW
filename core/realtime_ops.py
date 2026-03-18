from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from pathlib import Path
import random
import json

import numpy as np
import pandas as pd


UPDATE_INTERVAL_SECONDS = 60
HISTORY_LIMIT = 120
SIMULATION_STEP_HOURS = 24
SIMULATION_START = datetime(2026, 4, 1, 6, 0)
STATE_FILE = Path(__file__).resolve().parent / "data" / "realtime_state.json"
FORECAST_MODEL_NAME = "Linear regression with trend + weekly seasonality"


@dataclass(frozen=True)
class WardProfile:
    name: str
    capacity: int
    base_occupancy: int
    nurses: int
    doctors: int
    ventilators: int
    monitors: int


WARD_PROFILES = [
    WardProfile("ICU", 24, 18, 10, 4, 10, 18),
    WardProfile("Emergency", 32, 24, 12, 4, 4, 16),
    WardProfile("General", 60, 38, 16, 5, 2, 20),
    WardProfile("Surgery", 28, 19, 9, 3, 6, 14),
    WardProfile("Maternity", 22, 14, 7, 2, 1, 10),
]


def _hour_pressure(hour: int, ward_name: str) -> float:
    ward_bias = {
        "ICU": 1.25,
        "Emergency": 1.45,
        "General": 1.0,
        "Surgery": 1.1,
        "Maternity": 0.9,
    }[ward_name]
    morning = math.sin((hour - 7) / 24 * 2 * math.pi)
    evening = math.cos((hour - 19) / 24 * 2 * math.pi)
    return ward_bias * (0.55 + 0.3 * morning + 0.15 * evening)


def _required_resources(occupancy: int) -> dict[str, int]:
    return {
        "required_nurses": max(2, math.ceil(occupancy / 4)),
        "required_doctors": max(1, math.ceil(occupancy / 12)),
        "required_ventilators": math.ceil(occupancy * 0.18),
        "required_monitors": math.ceil(occupancy * 0.45),
    }


def build_realtime_state(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    wards = []
    history = []
    simulation_now = SIMULATION_START

    for index, profile in enumerate(WARD_PROFILES):
        occupied = profile.base_occupancy
        resources = _required_resources(occupied)
        ward = {
            "ward": profile.name,
            "capacity": profile.capacity,
            "occupied_beds": occupied,
            "available_beds": profile.capacity - occupied,
            "occupancy_rate": round(occupied / profile.capacity, 3),
            "admissions_last_hour": 0,
            "discharges_last_hour": 0,
            "nurses_available": profile.nurses,
            "doctors_available": profile.doctors,
            "ventilators_available": profile.ventilators,
            "monitors_available": profile.monitors,
            **resources,
        }
        wards.append(ward)
        history.append(
            {
                "timestamp": simulation_now - timedelta(days=4) + timedelta(days=index),
                "ward": profile.name,
                "occupied_beds": occupied,
                "capacity": profile.capacity,
            }
        )

    return {
        "last_updated": now,
        "simulation_now": simulation_now,
        "wards": wards,
        "history": history,
        "recommendation_log": {},
    }


def load_realtime_state(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    if not STATE_FILE.exists():
        return build_realtime_state(now=now)

    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        payload["last_updated"] = datetime.fromisoformat(payload["last_updated"])
        payload["simulation_now"] = datetime.fromisoformat(payload["simulation_now"])
        payload["recommendation_log"] = payload.get("recommendation_log", {})
        for row in payload.get("history", []):
            row["timestamp"] = datetime.fromisoformat(row["timestamp"])
        return payload
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return build_realtime_state(now=now)


def save_realtime_state(state: dict) -> None:
    serializable = {
        "last_updated": state["last_updated"].isoformat(),
        "simulation_now": state["simulation_now"].isoformat(),
        "wards": state["wards"],
        "recommendation_log": state.get("recommendation_log", {}),
        "history": [
            {
                **row,
                "timestamp": row["timestamp"].isoformat() if isinstance(row["timestamp"], datetime) else str(row["timestamp"]),
            }
            for row in state["history"]
        ],
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


def _simulate_ward_step(ward: dict, timestamp: datetime) -> dict:
    seeded_random = random.Random(f"{ward['ward']}-{timestamp.isoformat(timespec='minutes')}")
    pressure = _hour_pressure(timestamp.hour, ward["ward"])

    admissions = max(0, round(seeded_random.uniform(0, 3.2) + pressure * 1.8))
    discharges = max(0, round(seeded_random.uniform(0, 2.6) + (1.1 - pressure) * 1.2))

    if ward["ward"] == "Emergency":
        admissions += seeded_random.randint(0, 2)
    if ward["ward"] == "Surgery" and 6 <= timestamp.hour <= 18:
        admissions += 1
    if ward["ward"] == "General" and timestamp.hour >= 15:
        discharges += 1

    occupied = ward["occupied_beds"] + admissions - discharges
    occupied = max(0, min(ward["capacity"], occupied))

    nurse_buffer = seeded_random.randint(-1, 1)
    doctor_buffer = seeded_random.choice([0, 0, 1, -1])

    resources = _required_resources(occupied)
    return {
        **ward,
        "occupied_beds": occupied,
        "available_beds": ward["capacity"] - occupied,
        "occupancy_rate": round(occupied / ward["capacity"], 3),
        "admissions_last_hour": admissions,
        "discharges_last_hour": discharges,
        "nurses_available": max(2, ward["nurses_available"] + nurse_buffer),
        "doctors_available": max(1, ward["doctors_available"] + doctor_buffer),
        "ventilators_available": ward["ventilators_available"],
        "monitors_available": ward["monitors_available"],
        **resources,
    }


def simulate_realtime(state: dict, now: datetime | None = None, force_step: bool = False) -> dict:
    now = now or datetime.now()
    last_updated = state["last_updated"]
    simulation_now = state.get("simulation_now", SIMULATION_START)
    elapsed_seconds = max(0, int((now - last_updated).total_seconds()))
    steps = max(1, elapsed_seconds // UPDATE_INTERVAL_SECONDS) if elapsed_seconds else 0

    if force_step and steps == 0:
        steps = 1

    if steps == 0:
        return state

    timestamp = last_updated
    wards = state["wards"]
    history = list(state["history"])
    simulated_timestamp = simulation_now

    for _ in range(steps):
        timestamp += timedelta(seconds=UPDATE_INTERVAL_SECONDS)
        simulated_timestamp += timedelta(hours=SIMULATION_STEP_HOURS)
        wards = [_simulate_ward_step(ward, timestamp) for ward in wards]
        history.extend(
            {
                "timestamp": simulated_timestamp,
                "ward": ward["ward"],
                "occupied_beds": ward["occupied_beds"],
                "capacity": ward["capacity"],
            }
            for ward in wards
        )

    return {
        "last_updated": timestamp,
        "simulation_now": simulated_timestamp,
        "wards": wards,
        "history": history[-HISTORY_LIMIT * len(WARD_PROFILES):],
    }


def build_history_frame(state: dict) -> pd.DataFrame:
    history = pd.DataFrame(state["history"])
    if history.empty:
        return history
    history["timestamp"] = pd.to_datetime(history["timestamp"])
    history["occupancy_rate"] = history["occupied_beds"] / history["capacity"]
    return history.sort_values(["timestamp", "ward"]).reset_index(drop=True)


def predict_tomorrow(history: pd.DataFrame, capacity: int) -> dict[str, int]:
    if history.empty or len(history) < 6:
        fallback = int(capacity * 0.72)
        return {"predicted_avg": fallback, "predicted_peak": min(capacity, fallback + 2)}

    ordered = history.sort_values("timestamp").copy()
    ordered["t"] = np.arange(len(ordered))
    ordered["dow"] = ordered["timestamp"].dt.dayofweek

    x = np.column_stack(
        [
            np.ones(len(ordered)),
            ordered["t"].to_numpy(),
            np.sin(2 * np.pi * ordered["dow"].to_numpy() / 7),
            np.cos(2 * np.pi * ordered["dow"].to_numpy() / 7),
        ]
    )
    y = ordered["occupied_beds"].to_numpy()

    try:
        coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    except np.linalg.LinAlgError:
        mean_value = int(round(float(np.mean(y))))
        return {"predicted_avg": mean_value, "predicted_peak": min(capacity, mean_value + 2)}

    future_rows = []
    start = ordered["timestamp"].max() + timedelta(days=1)
    base_t = int(ordered["t"].iloc[-1])
    for step in range(1, 8):
        forecast_time = start + timedelta(days=step - 1)
        dow = forecast_time.weekday()
        future_rows.append(
            [
                1.0,
                base_t + step,
                math.sin(2 * math.pi * dow / 7),
                math.cos(2 * math.pi * dow / 7),
            ]
        )

    predictions = np.dot(np.array(future_rows), coefficients)
    clipped = np.clip(predictions, 0, capacity)
    return {
        "predicted_avg": int(round(float(np.mean(clipped)))),
        "predicted_peak": int(round(float(np.max(clipped)))),
    }


def build_operational_snapshot(state: dict) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    history = build_history_frame(state)
    rows = []
    alerts = []

    for ward in state["wards"]:
        ward_history = history[history["ward"] == ward["ward"]]
        forecast = predict_tomorrow(ward_history, ward["capacity"])

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
                "Occupancy %": round(ward["occupancy_rate"] * 100, 1),
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
    recommendations = build_recommendations(snapshot)
    updated_state, visible_recommendations = update_recommendation_log(state, alerts + recommendations)
    state.update(updated_state)
    return snapshot, history, visible_recommendations


def update_recommendation_log(state: dict, recommendations: list[str]) -> tuple[dict, list[str]]:
    simulation_now = state.get("simulation_now", SIMULATION_START)
    recommendation_log = dict(state.get("recommendation_log", {}))

    for recommendation in recommendations:
        recommendation_log.setdefault(recommendation, simulation_now.isoformat())

    visible_recommendations = []
    retained_log = {}
    for recommendation, first_seen in recommendation_log.items():
        try:
            first_seen_dt = datetime.fromisoformat(first_seen)
        except ValueError:
            first_seen_dt = simulation_now

        age_days = (simulation_now.date() - first_seen_dt.date()).days
        if age_days < 3:
            retained_log[recommendation] = first_seen_dt.isoformat()
            if recommendation in recommendations:
                visible_recommendations.append(recommendation)

    return {**state, "recommendation_log": retained_log}, visible_recommendations


def build_recommendations(snapshot: pd.DataFrame) -> list[str]:
    recommendations = []
    for _, row in snapshot.iterrows():
        nurse_gap = int(row["Nurses Required"] - row["Nurses Available"])
        doctor_gap = int(row["Doctors Required"] - row["Doctors Available"])
        ventilator_gap = int(row["Ventilators Required"] - row["Ventilators Available"])
        monitor_gap = int(row["Monitors Required"] - row["Monitors Available"])

        if nurse_gap > 0:
            recommendations.append(f"{row['Ward']}: assign {nurse_gap} additional nurses for the next shift.")
        if doctor_gap > 0:
            recommendations.append(f"{row['Ward']}: add {doctor_gap} doctor(s) to maintain safe coverage.")
        if ventilator_gap > 0:
            recommendations.append(f"{row['Ward']}: redeploy {ventilator_gap} ventilator(s) from lower-acuity wards.")
        if monitor_gap > 0:
            recommendations.append(f"{row['Ward']}: move {monitor_gap} patient monitor(s) into the ward.")

        predicted_peak = int(row["Predicted Peak Tomorrow"])
        capacity = int(row["Capacity"])
        if predicted_peak >= capacity:
            recommendations.append(f"{row['Ward']}: predicted to hit full capacity tomorrow, trigger escalation bed plan.")
        elif predicted_peak >= math.floor(capacity * 0.9):
            recommendations.append(f"{row['Ward']}: predicted near full tomorrow, ring-fence discharge and porter support.")

    if not recommendations:
        recommendations.append("Current staffing and equipment coverage is within the recommended operating range.")

    return recommendations


def build_system_totals(snapshot: pd.DataFrame) -> dict[str, float]:
    occupied = int(snapshot["Occupied Beds"].sum())
    capacity = int(snapshot["Capacity"].sum())
    avg_tomorrow = int(snapshot["Predicted Avg Tomorrow"].sum())
    peak_tomorrow = int(snapshot["Predicted Peak Tomorrow"].sum())
    return {
        "occupied": occupied,
        "capacity": capacity,
        "available": capacity - occupied,
        "occupancy_pct": round((occupied / capacity) * 100, 1) if capacity else 0.0,
        "predicted_avg": avg_tomorrow,
        "predicted_peak": peak_tomorrow,
    }


def sync_history_to_current_state(state: dict) -> dict:
    simulation_now = state.get("simulation_now", SIMULATION_START)
    history = [
        row
        for row in state["history"]
        if not (
            row.get("timestamp") == simulation_now
            and any(ward["ward"] == row.get("ward") for ward in state["wards"])
        )
    ]
    history.extend(
        {
            "timestamp": simulation_now,
            "ward": ward["ward"],
            "occupied_beds": ward["occupied_beds"],
            "capacity": ward["capacity"],
        }
        for ward in state["wards"]
    )
    return {
        **state,
        "history": history[-HISTORY_LIMIT * len(WARD_PROFILES):],
    }


def apply_recommendation_action(state: dict, recommendation: str) -> tuple[dict, str]:
    wards = [dict(ward) for ward in state["wards"]]
    if ":" not in recommendation:
        return state, "No direct state change available for this recommendation."

    ward_name, action_text = recommendation.split(":", 1)
    ward_name = ward_name.strip()
    action_text = action_text.strip()

    target_index = next((index for index, ward in enumerate(wards) if ward["ward"] == ward_name), None)
    if target_index is None:
        return state, "Recommended ward was not found in the live state."

    ward = dict(wards[target_index])
    action_lower = action_text.lower()
    applied_message = "Recommendation noted, but no direct simulation change was applied."

    if action_lower.startswith("assign ") and "additional nurses" in action_lower:
        amount = int(action_text.split()[1])
        ward["nurses_available"] += amount
        applied_message = f"Assigned {amount} nurses to {ward_name}."
    elif action_lower.startswith("add ") and "doctor" in action_lower:
        amount = int(action_text.split()[1])
        ward["doctors_available"] += amount
        applied_message = f"Assigned {amount} doctor(s) to {ward_name}."
    elif action_lower.startswith("redeploy ") and "ventilator" in action_lower:
        amount = int(action_text.split()[1])
        ward["ventilators_available"] += amount
        applied_message = f"Redeployed {amount} ventilator(s) to {ward_name}."
    elif action_lower.startswith("move ") and "patient monitor" in action_lower:
        amount = int(action_text.split()[1])
        ward["monitors_available"] += amount
        applied_message = f"Moved {amount} patient monitor(s) to {ward_name}."
    elif "trigger escalation bed plan" in action_lower:
        freed_beds = min(3, ward["occupied_beds"])
        ward["occupied_beds"] -= freed_beds
        applied_message = f"Triggered overflow response for {ward_name}; released capacity for {freed_beds} bed(s)."
    elif "ring-fence discharge and porter support" in action_lower:
        ward["discharges_last_hour"] += 2
        ward["occupied_beds"] = max(0, ward["occupied_beds"] - 2)
        applied_message = f"Added discharge support to {ward_name}; reduced occupancy by 2 beds."
    elif "pre-position extra staff and discharge support" in action_lower:
        ward["nurses_available"] += 1
        ward["doctors_available"] += 1
        ward["occupied_beds"] = max(0, ward["occupied_beds"] - 1)
        applied_message = f"Pre-positioned staff for {ward_name} and relieved 1 occupied bed."
    elif "move overflow plan to standby" in action_lower:
        ward["occupied_beds"] = max(0, ward["occupied_beds"] - 2)
        applied_message = f"Placed overflow plan on standby for {ward_name}; relieved 2 occupied beds."

    ward["available_beds"] = max(0, ward["capacity"] - ward["occupied_beds"])
    ward["occupancy_rate"] = round(ward["occupied_beds"] / ward["capacity"], 3) if ward["capacity"] else 0.0
    ward.update(_required_resources(ward["occupied_beds"]))
    wards[target_index] = ward

    updated_state = {
        **state,
        "wards": wards,
    }
    return sync_history_to_current_state(updated_state), applied_message


def apply_emergency_staffing(state: dict) -> tuple[dict, str]:
    wards = []
    targeted = 0

    for ward in state["wards"]:
        updated = dict(ward)
        if updated["occupancy_rate"] >= 0.8 or updated["nurses_available"] < updated["required_nurses"]:
            updated["nurses_available"] += 3
            updated["doctors_available"] += 1
            targeted += 1
        wards.append(updated)

    return sync_history_to_current_state({**state, "wards": wards}), f"Emergency staffing pool deployed to {targeted} ward(s)."


def apply_emergency_capacity(state: dict) -> tuple[dict, str]:
    wards = []
    targeted = 0

    for ward in state["wards"]:
        updated = dict(ward)
        if updated["occupancy_rate"] >= 0.85:
            updated["capacity"] += 4
            updated["available_beds"] = updated["capacity"] - updated["occupied_beds"]
            updated["occupancy_rate"] = round(updated["occupied_beds"] / updated["capacity"], 3)
            targeted += 1
        wards.append(updated)

    return sync_history_to_current_state({**state, "wards": wards}), f"Emergency bed expansion opened 4 extra beds in {targeted} ward(s)."


def apply_full_emergency_stabilization(state: dict) -> tuple[dict, str]:
    staffed_state, staffing_message = apply_emergency_staffing(state)
    expanded_state, capacity_message = apply_emergency_capacity(staffed_state)

    wards = []
    for ward in expanded_state["wards"]:
        updated = dict(ward)
        if updated["occupancy_rate"] >= 0.9:
            updated["occupied_beds"] = max(0, updated["occupied_beds"] - 2)
        updated["available_beds"] = updated["capacity"] - updated["occupied_beds"]
        updated["occupancy_rate"] = round(updated["occupied_beds"] / updated["capacity"], 3) if updated["capacity"] else 0.0
        updated.update(_required_resources(updated["occupied_beds"]))
        wards.append(updated)

    message = f"{staffing_message} {capacity_message} Overflow discharge plan applied to the highest-pressure wards."
    return sync_history_to_current_state({**expanded_state, "wards": wards}), message
