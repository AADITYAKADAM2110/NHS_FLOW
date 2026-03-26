from __future__ import annotations

from datetime import datetime, timedelta

from .constants import SIMULATION_START
from .helpers import refresh_ward_metrics
from .state import sync_history_to_current_state


def set_operation_mode(state: dict, mode: str) -> tuple[dict, str]:
    updated_state = {
        **state,
        "operation_mode": mode,
        "last_updated": datetime.now(),
        "recommendation_cache": {},
    }
    message = "Real mode enabled. Simulation is paused until you manually advance the hospital day."
    if mode == "simulation":
        message = "Simulation mode enabled. Automatic hospital updates are active again."
    return updated_state, message


def advance_hospital_day(state: dict, days: int = 1) -> tuple[dict, str]:
    simulation_now = state.get("simulation_now", SIMULATION_START) + timedelta(days=days)
    updated_state = sync_history_to_current_state(
        {
            **state,
            "simulation_now": simulation_now,
            "last_updated": datetime.now(),
            "recommendation_cache": {},
        }
    )
    return updated_state, f"Hospital day advanced to {simulation_now.strftime('%d %b %Y %H:%M')}."


def update_ward_state(state: dict, ward_name: str, updates: dict) -> tuple[dict, str]:
    wards = [dict(ward) for ward in state["wards"]]
    target_index = next((index for index, ward in enumerate(wards) if ward["ward"] == ward_name), None)
    if target_index is None:
        return state, "Selected ward was not found."
    ward = dict(wards[target_index])
    admissions = max(0, int(updates.get("admissions", 0)))
    discharges = max(0, int(updates.get("discharges", 0)))
    occupied = ward["occupied_beds"] + admissions - discharges
    ward.update(
        {
            "capacity": max(1, int(updates.get("capacity", ward["capacity"]))),
            "occupied_beds": max(0, int(updates.get("occupied_beds", occupied))),
            "admissions_last_hour": admissions,
            "discharges_last_hour": discharges,
            "ventilators_available": max(0, int(updates.get("ventilators_available", ward["ventilators_available"]))),
            "monitors_available": max(0, int(updates.get("monitors_available", ward["monitors_available"]))),
        }
    )
    wards[target_index] = refresh_ward_metrics(ward)
    updated_state = sync_history_to_current_state(
        {
            **state,
            "wards": wards,
            "last_updated": datetime.now(),
            "recommendation_cache": {},
        }
    )
    return updated_state, f"Updated live ward data for {ward_name}."
