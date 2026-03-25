from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"
LAYOUT_FILE = DATA_DIR / "hospital_layout.json"


def build_hospital_map(snapshot: pd.DataFrame) -> list[dict]:
    layout = _load_layout()
    staff_counts = _load_staff_counts()
    wards = snapshot.sort_values(["Occupancy %", "Ward"], ascending=[False, True]).to_dict(orient="records")
    positions = layout or _dynamic_layout(len(wards))
    return [_build_zone(ward, staff_counts.get(ward["Ward"], {}), positions[index]) for index, ward in enumerate(wards)]


def _build_zone(ward: dict, staff: dict, position: dict) -> dict:
    occupancy = float(ward["Occupancy %"])
    details = {
        "Occupied Beds": int(ward["Occupied Beds"]),
        "Capacity": int(ward["Capacity"]),
        "Occupancy %": occupancy,
        "Admissions/hr": int(ward["Admissions/hr"]),
        "Discharges/hr": int(ward["Discharges/hr"]),
        "Predicted Avg Tomorrow": int(ward["Predicted Avg Tomorrow"]),
        "Predicted Peak Tomorrow": int(ward["Predicted Peak Tomorrow"]),
        "Nurses Available": int(ward["Nurses Available"]),
        "Nurses Required": int(ward["Nurses Required"]),
        "Doctors Available": int(ward["Doctors Available"]),
        "Doctors Required": int(ward["Doctors Required"]),
        "Ventilators Available": int(ward["Ventilators Available"]),
        "Ventilators Required": int(ward["Ventilators Required"]),
        "Monitors Available": int(ward["Monitors Available"]),
        "Monitors Required": int(ward["Monitors Required"]),
        "Staff Total": int(staff.get("total", 0)),
        "Staff Nurses": int(staff.get("nurses", 0)),
        "Staff Doctors": int(staff.get("doctors", 0)),
    }
    return {
        "ward": ward["Ward"],
        "x": position["x"],
        "y": position["y"],
        "w": position["w"],
        "h": position["h"],
        "occupancy": occupancy,
        "fill": _heat_color(occupancy),
        "beds": f"{int(ward['Occupied Beds'])}/{int(ward['Capacity'])}",
        "staff": staff,
        "nurses": f"{int(ward['Nurses Available'])}/{int(ward['Nurses Required'])}",
        "doctors": f"{int(ward['Doctors Available'])}/{int(ward['Doctors Required'])}",
        "ventilators": f"{int(ward['Ventilators Available'])}/{int(ward['Ventilators Required'])}",
        "monitors": f"{int(ward['Monitors Available'])}/{int(ward['Monitors Required'])}",
        "details": details,
        "tooltip": _tooltip_text(ward["Ward"], details),
    }


def _load_layout() -> list[dict]:
    if not LAYOUT_FILE.exists():
        return []
    try:
        data = json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    zones = []
    for item in data:
        if all(key in item for key in ("x", "y", "w", "h")):
            zones.append({key: int(item[key]) for key in ("x", "y", "w", "h")})
    return zones


def _load_staff_counts() -> dict[str, dict[str, int]]:
    staff_file = DATA_DIR / "staff.json"
    if not staff_file.exists():
        return {}
    try:
        records = json.loads(staff_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    counts: dict[str, dict[str, int]] = {}
    for row in records:
        ward = row.get("ward")
        role = str(row.get("role", "")).lower()
        if not ward:
            continue
        counts.setdefault(ward, {"total": 0, "nurses": 0, "doctors": 0})
        counts[ward]["total"] += 1
        if role == "nurse":
            counts[ward]["nurses"] += 1
        if role == "doctor":
            counts[ward]["doctors"] += 1
    return counts


def _dynamic_layout(count: int) -> list[dict]:
    cols = 2 if count <= 4 else 3
    return [
        {"x": 24 + (index % cols) * 244, "y": 24 + (index // cols) * 144, "w": 220, "h": 120}
        for index in range(count)
    ]


def _heat_color(occupancy: float) -> str:
    if occupancy >= 95:
        return "#b42318"
    if occupancy >= 85:
        return "#d95d0f"
    if occupancy >= 70:
        return "#f59e0b"
    return "#0b7a6b"


def _tooltip_text(ward_name: str, details: dict) -> str:
    lines = [ward_name]
    for label, value in details.items():
        suffix = "%" if label == "Occupancy %" else ""
        display = f"{value:.1f}" if isinstance(value, float) else str(value)
        lines.append(f"{label}: {display}{suffix}")
    return "&#10;".join(lines)
