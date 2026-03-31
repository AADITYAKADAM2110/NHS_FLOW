from __future__ import annotations

import json
from datetime import datetime, timedelta

from .constants import HISTORY_LIMIT, SIMULATION_START, STATE_FILE
from .helpers import history_entry, refresh_ward_metrics
from .models import WARD_PROFILES
from .patient_flow import build_initial_patients
from .staffing_sync import strip_staffing_fields, sync_staff_counts_to_wards

def build_default_wards() -> list[dict]:
    wards = []
    for profile in WARD_PROFILES:
        wards.append(
            refresh_ward_metrics(
                {
                    "ward": profile.name,
                    "capacity": profile.capacity,
                    "occupied_beds": profile.base_occupancy,
                    "admissions_last_hour": 0,
                    "discharges_last_hour": 0,
                    "nurses_available": profile.nurses,
                    "doctors_available": profile.doctors,
                    "ventilators_available": profile.ventilators,
                    "monitors_available": profile.monitors,
                }
            )
        )
    return sync_staff_counts_to_wards(wards)


def build_realtime_state(now: datetime | None = None, mode: str = "simulation") -> dict:
    now = now or datetime.now()
    simulation_now = SIMULATION_START
    wards = build_default_wards()
    patients, patient_events, patient_counter = build_initial_patients(wards, simulation_now)
    history = []
    for index, ward in enumerate(wards):
        history.append(history_entry(simulation_now - timedelta(days=4 - index), ward))
    return {
        "last_updated": now,
        "simulation_now": simulation_now,
        "operation_mode": mode,
        "wards": wards,
        "history": history,
        "patients": patients,
        "patient_events": patient_events,
        "patient_counter": patient_counter,
        "recommendation_log": {},
        "recommendation_cache": {},
        "manager_agent": {
            "enabled": True,
            "mode": "auto",
            "last_applied_ids": [],
            "last_summary": "",
            "last_memory_summary": "",
        },
        "manager_decision_log": [],
        "manager_interviews": [],
    }


def load_realtime_state(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    if not STATE_FILE.exists():
        return build_realtime_state(now=now)
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        payload["last_updated"] = datetime.fromisoformat(payload["last_updated"])
        payload["simulation_now"] = datetime.fromisoformat(payload["simulation_now"])
        payload["operation_mode"] = payload.get("operation_mode", "simulation")
        payload["recommendation_log"] = payload.get("recommendation_log", {})
        payload["recommendation_cache"] = payload.get("recommendation_cache", {})
        seeded_patients = payload.get("patients", [])
        if not seeded_patients:
            seeded_patients, seeded_events, seeded_counter = build_initial_patients(payload.get("wards", []), payload["simulation_now"])
            payload["patients"] = seeded_patients
            payload["patient_events"] = seeded_events
            payload["patient_counter"] = seeded_counter
        for patient in payload.get("patients", []):
            patient["admitted_at"] = datetime.fromisoformat(patient["admitted_at"])
            if patient.get("discharge_ready_at"):
                patient["discharge_ready_at"] = datetime.fromisoformat(patient["discharge_ready_at"])
            if patient.get("discharged_at"):
                patient["discharged_at"] = datetime.fromisoformat(patient["discharged_at"])
            if patient.get("died_at"):
                patient["died_at"] = datetime.fromisoformat(patient["died_at"])
        for event in payload.get("patient_events", []):
            event["timestamp"] = datetime.fromisoformat(event["timestamp"])
        payload["patients"] = payload.get("patients", [])
        payload["patient_events"] = payload.get("patient_events", [])
        payload["patient_counter"] = payload.get("patient_counter", len(payload["patients"]))
        payload["manager_agent"] = {
            "enabled": payload.get("manager_agent", {}).get("enabled", True),
            "mode": payload.get("manager_agent", {}).get("mode", "auto"),
            "last_cycle_key": payload.get("manager_agent", {}).get("last_cycle_key"),
            "last_run_at": payload.get("manager_agent", {}).get("last_run_at"),
            "last_recommendation_count": payload.get("manager_agent", {}).get("last_recommendation_count", 0),
            "last_applied_ids": payload.get("manager_agent", {}).get("last_applied_ids", []),
            "last_visible": payload.get("manager_agent", {}).get("last_visible", []),
            "last_summary": payload.get("manager_agent", {}).get("last_summary", ""),
            "last_memory_summary": payload.get("manager_agent", {}).get("last_memory_summary", ""),
        }
        payload["manager_decision_log"] = payload.get("manager_decision_log", [])
        payload["manager_interviews"] = payload.get("manager_interviews", [])
        for row in payload.get("history", []):
            row["timestamp"] = datetime.fromisoformat(row["timestamp"])
        payload["wards"] = sync_staff_counts_to_wards(payload.get("wards", []))
        return payload
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return build_realtime_state(now=now)


def save_realtime_state(state: dict) -> None:
    serializable = {
        "last_updated": state["last_updated"].isoformat(),
        "simulation_now": state["simulation_now"].isoformat(),
        "operation_mode": state.get("operation_mode", "simulation"),
        "wards": [strip_staffing_fields(ward) for ward in state["wards"]],
        "patients": [
            {
                **patient,
                "admitted_at": patient["admitted_at"].isoformat()
                if isinstance(patient.get("admitted_at"), datetime)
                else patient.get("admitted_at"),
                "discharge_ready_at": patient["discharge_ready_at"].isoformat()
                if isinstance(patient.get("discharge_ready_at"), datetime)
                else patient.get("discharge_ready_at"),
                "discharged_at": patient["discharged_at"].isoformat()
                if isinstance(patient.get("discharged_at"), datetime)
                else patient.get("discharged_at"),
                "died_at": patient["died_at"].isoformat()
                if isinstance(patient.get("died_at"), datetime)
                else patient.get("died_at"),
            }
            for patient in state.get("patients", [])
        ],
        "patient_events": [
            {
                **event,
                "timestamp": event["timestamp"].isoformat()
                if isinstance(event.get("timestamp"), datetime)
                else event.get("timestamp"),
            }
            for event in state.get("patient_events", [])
        ],
        "patient_counter": state.get("patient_counter", 0),
        "recommendation_log": state.get("recommendation_log", {}),
        "recommendation_cache": state.get("recommendation_cache", {}),
        "manager_agent": state.get("manager_agent", {}),
        "manager_decision_log": state.get("manager_decision_log", []),
        "manager_interviews": state.get("manager_interviews", []),
        "history": [
            {
                **row,
                "timestamp": row["timestamp"].isoformat()
                if isinstance(row["timestamp"], datetime)
                else str(row["timestamp"]),
            }
            for row in state["history"]
        ],
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


def sync_history_to_current_state(state: dict) -> dict:
    simulation_now = state.get("simulation_now", SIMULATION_START)
    ward_names = {ward["ward"] for ward in state["wards"]}
    history = [
        row for row in state["history"]
        if not (row.get("timestamp") == simulation_now and row.get("ward") in ward_names)
    ]
    history.extend(history_entry(simulation_now, ward) for ward in state["wards"])
    limit = HISTORY_LIMIT * len(WARD_PROFILES)
    return {**state, "history": history[-limit:]}
