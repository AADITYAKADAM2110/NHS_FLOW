from __future__ import annotations

import json
from datetime import datetime, timedelta

from .constants import HISTORY_LIMIT, SIMULATION_START, STATE_FILE
from .helpers import history_entry, refresh_ward_metrics
from .models import WARD_PROFILES
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
    history = []
    for index, ward in enumerate(wards):
        history.append(history_entry(simulation_now - timedelta(days=4 - index), ward))
    return {
        "last_updated": now,
        "simulation_now": simulation_now,
        "operation_mode": mode,
        "wards": wards,
        "history": history,
        "recommendation_log": {},
        "recommendation_cache": {},
        "manager_agent": {"enabled": True, "mode": "auto", "last_applied_ids": [], "last_summary": ""},
        "manager_decision_log": [],
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
        payload["manager_agent"] = {
            "enabled": payload.get("manager_agent", {}).get("enabled", True),
            "mode": payload.get("manager_agent", {}).get("mode", "auto"),
            "last_cycle_key": payload.get("manager_agent", {}).get("last_cycle_key"),
            "last_run_at": payload.get("manager_agent", {}).get("last_run_at"),
            "last_recommendation_count": payload.get("manager_agent", {}).get("last_recommendation_count", 0),
            "last_applied_ids": payload.get("manager_agent", {}).get("last_applied_ids", []),
            "last_visible": payload.get("manager_agent", {}).get("last_visible", []),
            "last_summary": payload.get("manager_agent", {}).get("last_summary", ""),
        }
        payload["manager_decision_log"] = payload.get("manager_decision_log", [])
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
        "recommendation_log": state.get("recommendation_log", {}),
        "recommendation_cache": state.get("recommendation_cache", {}),
        "manager_agent": state.get("manager_agent", {}),
        "manager_decision_log": state.get("manager_decision_log", []),
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
