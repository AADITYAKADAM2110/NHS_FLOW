from __future__ import annotations

import random
from datetime import datetime, timedelta

from .constants import HISTORY_LIMIT, SIMULATION_START, SIMULATION_STEP_HOURS, UPDATE_INTERVAL_SECONDS
from .helpers import history_entry, hour_pressure, refresh_ward_metrics
from .models import WARD_PROFILES
from .patient_flow import simulate_patient_step
from .staffing_sync import sync_staff_counts_to_wards





def simulate_realtime(state: dict, now: datetime | None = None, force_step: bool = False) -> dict:
    if state.get("operation_mode") == "real":
        return state
    now = now or datetime.now()
    elapsed_seconds = max(0, int((now - state["last_updated"]).total_seconds()))
    steps = max(1, elapsed_seconds // UPDATE_INTERVAL_SECONDS) if elapsed_seconds else 0
    if force_step and steps == 0:
        steps = 1
    if steps == 0:
        return state
    timestamp = state["last_updated"]
    simulated_timestamp = state.get("simulation_now", SIMULATION_START)
    wards = state["wards"]
    history = list(state["history"])
    patients = list(state.get("patients", []))
    patient_events = list(state.get("patient_events", []))
    patient_counter = int(state.get("patient_counter", len(patients)))
    for _ in range(steps):
        timestamp += timedelta(seconds=UPDATE_INTERVAL_SECONDS)
        simulated_timestamp += timedelta(hours=SIMULATION_STEP_HOURS)
        simulated_state = {
            **state,
            "wards": wards,
            "patients": patients,
            "patient_events": patient_events,
            "patient_counter": patient_counter,
        }
        wards, patients, patient_events, patient_meta = simulate_patient_step(simulated_state, simulated_timestamp)
        patient_counter = patient_meta["patient_counter"]
        wards = sync_staff_counts_to_wards(wards)
        history.extend(history_entry(simulated_timestamp, ward) for ward in wards)
    return {
        "last_updated": timestamp,
        "simulation_now": simulated_timestamp,
        "operation_mode": state.get("operation_mode", "simulation"),
        "wards": wards,
        "history": history[-HISTORY_LIMIT * len(WARD_PROFILES):],
        "patients": patients,
        "patient_events": patient_events[-800:],
        "patient_counter": patient_counter,
        "recommendation_log": state.get("recommendation_log", {}),
        "recommendation_cache": state.get("recommendation_cache", {}),
        "manager_agent": state.get("manager_agent", {"enabled": True, "mode": "auto"}),
        "manager_decision_log": state.get("manager_decision_log", []),
        "manager_interviews": state.get("manager_interviews", []),
    }


def simulate_ward_step(ward: dict, simulated_timestamp: datetime) -> dict:
    seeded_random = random.Random(f"{ward['ward']}-{simulated_timestamp.isoformat(timespec='minutes')}")
    pressure = hour_pressure(simulated_timestamp.hour, ward["ward"])
    admissions = max(0, round(seeded_random.uniform(0, 3.2) + pressure * 1.8))
    discharges = max(0, round(seeded_random.uniform(0, 3.5) + (1.1 - pressure) * 1.8))
    if ward["ward"] == "Emergency":
        admissions += seeded_random.randint(0, 2)
    if ward["ward"] == "Surgery" and 6 <= simulated_timestamp.hour <= 18:
        admissions += 1
    if ward["ward"] == "General" and simulated_timestamp.hour >= 15:
        discharges += 2
    if ward["ward"] == "Maternity" and simulated_timestamp.hour >= 10:
        discharges += 1
    updated = {
        **ward,
        "occupied_beds": max(0, min(ward["capacity"], ward["occupied_beds"] + admissions - discharges)),
        "admissions_last_hour": admissions,
        "discharges_last_hour": discharges,
    }
    return refresh_ward_metrics(updated)
