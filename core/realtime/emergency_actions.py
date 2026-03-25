from __future__ import annotations

from .helpers import refresh_ward_metrics
from .state import sync_history_to_current_state


def apply_emergency_staffing(state: dict) -> tuple[dict, str]:
    wards = []
    targeted = 0
    for ward in state["wards"]:
        updated = dict(ward)
        if updated["occupancy_rate"] >= 0.8 or updated["nurses_available"] < updated["required_nurses"]:
            updated["nurses_available"] += 3
            updated["doctors_available"] += 1
            targeted += 1
        wards.append(refresh_ward_metrics(updated))
    return sync_history_to_current_state({**state, "wards": wards}), f"Emergency staffing pool deployed to {targeted} ward(s)."


def apply_emergency_capacity(state: dict) -> tuple[dict, str]:
    wards = []
    targeted = 0
    for ward in state["wards"]:
        updated = dict(ward)
        if updated["occupancy_rate"] >= 0.85:
            updated["capacity"] += 4
            targeted += 1
        wards.append(refresh_ward_metrics(updated))
    return sync_history_to_current_state({**state, "wards": wards}), f"Emergency bed expansion opened 4 extra beds in {targeted} ward(s)."


def apply_full_emergency_stabilization(state: dict) -> tuple[dict, str]:
    staffed_state, staffing_message = apply_emergency_staffing(state)
    expanded_state, capacity_message = apply_emergency_capacity(staffed_state)
    wards = []
    for ward in expanded_state["wards"]:
        updated = dict(ward)
        if updated["occupancy_rate"] >= 0.9:
            updated["occupied_beds"] = max(0, updated["occupied_beds"] - 2)
        wards.append(refresh_ward_metrics(updated))
    message = f"{staffing_message} {capacity_message} Overflow discharge plan applied to the highest-pressure wards."
    return sync_history_to_current_state({**expanded_state, "wards": wards}), message
