from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .constants import HISTORY_LIMIT, SIMULATION_START, STATE_FILE
from .helpers import history_entry, refresh_ward_metrics
from .models import WARD_PROFILES

DATA_DIR = Path(__file__).parent.parent / "data"


def load_wards_from_data() -> list[dict]:
    beds_file = DATA_DIR / "beds.json"
    equipment_file = DATA_DIR / "equipment.json"
    
    # Load equipment data
    equip_agg = {}
    if equipment_file.exists():
        try:
            equip_data = json.loads(equipment_file.read_text(encoding="utf-8"))
            for e in equip_data:
                ward = e["ward"]
                eq_type = e["equipment_type"]
                available = e["available_units"]
                if ward not in equip_agg:
                    equip_agg[ward] = {"ventilators": 0, "monitors": 0}
                if eq_type == "Ventilator":
                    equip_agg[ward]["ventilators"] = available
                elif eq_type == "Patient Monitor":
                    equip_agg[ward]["monitors"] = available
        except Exception:
            pass
    
    if not beds_file.exists():
        # Fallback to simulated
        return [
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
            for profile in WARD_PROFILES
        ]
    try:
        beds_data = json.loads(beds_file.read_text(encoding="utf-8"))
        wards = []
        for bed in beds_data:
            ward_name = bed["ward"]
            vents = equip_agg.get(ward_name, {}).get("ventilators", bed.get("ventilators_available", 0))
            mons = equip_agg.get(ward_name, {}).get("monitors", bed.get("monitors_available", 0))
            
            ward = {
                "ward": bed["ward"],
                "capacity": bed["capacity"],
                "occupied_beds": bed["occupied_beds"],
                "admissions_last_hour": bed.get("admissions_last_hour", 0),
                "discharges_last_hour": bed.get("discharges_last_hour", 0),
                "nurses_available": bed["nurses_available"],
                "doctors_available": bed["doctors_available"],
                "ventilators_available": vents,
                "monitors_available": mons,
            }
            wards.append(refresh_ward_metrics(ward))
        return wards
    except Exception:
        # Fallback
        return [
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
            for profile in WARD_PROFILES
        ]


def build_realtime_state(now: datetime | None = None, mode: str = "simulation") -> dict:
    now = now or datetime.now()
    simulation_now = SIMULATION_START
    wards = load_wards_from_data()
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
        for row in payload.get("history", []):
            row["timestamp"] = datetime.fromisoformat(row["timestamp"])
        return payload
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return build_realtime_state(now=now)


def save_realtime_state(state: dict) -> None:
    # Update beds.json with current ward data
    beds_file = DATA_DIR / "beds.json"
    if beds_file.exists():
        try:
            beds_data = json.loads(beds_file.read_text(encoding="utf-8"))
            ward_map = {ward["ward"]: ward for ward in state["wards"]}
            for bed in beds_data:
                ward_name = bed["ward"]
                if ward_name in ward_map:
                    current = ward_map[ward_name]
                    bed["occupied_beds"] = current["occupied_beds"]
                    bed["nurses_available"] = current["nurses_available"]
                    bed["doctors_available"] = current["doctors_available"]
                    bed["ventilators_available"] = current["ventilators_available"]
                    bed["monitors_available"] = current["monitors_available"]
                    bed["last_updated"] = datetime.now().isoformat()
            beds_file.write_text(json.dumps(beds_data, indent=2), encoding="utf-8")
        except Exception:
            pass  # Ignore errors, don't break save

    # Update equipment.json
    equipment_file = DATA_DIR / "equipment.json"
    if equipment_file.exists():
        try:
            equipment_data = json.loads(equipment_file.read_text(encoding="utf-8"))
            ward_map = {ward["ward"]: ward for ward in state["wards"]}
            for eq in equipment_data:
                ward_name = eq["ward"]
                eq_type = eq["equipment_type"]
                if ward_name in ward_map:
                    current = ward_map[ward_name]
                    if eq_type == "Ventilator":
                        eq["available_units"] = current["ventilators_available"]
                    elif eq_type == "Patient Monitor":
                        eq["available_units"] = current["monitors_available"]
                    eq["last_updated"] = datetime.now().isoformat()
            equipment_file.write_text(json.dumps(equipment_data, indent=2), encoding="utf-8")
        except Exception:
            pass

    history_file = DATA_DIR / "occupancy_history.json"
    try:
        history_payload = [
            {
                **row,
                "timestamp": row["timestamp"].isoformat(sep=" ")
                if isinstance(row["timestamp"], datetime)
                else str(row["timestamp"]),
                "occupancy_rate": round(row["occupied_beds"] / row["capacity"], 3) if row["capacity"] else 0.0,
            }
            for row in state["history"]
        ]
        history_file.write_text(json.dumps(history_payload, indent=2), encoding="utf-8")
    except Exception:
        pass

    serializable = {
        "last_updated": state["last_updated"].isoformat(),
        "simulation_now": state["simulation_now"].isoformat(),
        "operation_mode": state.get("operation_mode", "simulation"),
        "wards": state["wards"],
        "recommendation_log": state.get("recommendation_log", {}),
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
