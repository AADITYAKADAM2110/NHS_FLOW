from __future__ import annotations

import math
from datetime import datetime


def hour_pressure(hour: int, ward_name: str) -> float:
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


def required_resources(occupancy: int) -> dict[str, int]:
    return {
        "required_nurses": max(2, math.ceil(occupancy / 4)),
        "required_doctors": max(1, math.ceil(occupancy / 12)),
        "required_ventilators": math.ceil(occupancy * 0.18),
        "required_monitors": math.ceil(occupancy * 0.45),
    }


def history_entry(timestamp: datetime, ward: dict) -> dict:
    return {
        "timestamp": timestamp,
        "ward": ward["ward"],
        "occupied_beds": ward["occupied_beds"],
        "capacity": ward["capacity"],
    }


def refresh_ward_metrics(ward: dict) -> dict:
    refreshed = dict(ward)
    capacity = refreshed["capacity"]
    occupied = min(capacity, refreshed["occupied_beds"])  # Cap occupied beds at capacity
    refreshed["occupied_beds"] = occupied
    refreshed["available_beds"] = max(0, capacity - occupied)
    refreshed["occupancy_rate"] = round(occupied / capacity, 3) if capacity else 0.0
    refreshed.update(required_resources(occupied))
    return refreshed
