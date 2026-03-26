from __future__ import annotations

from .helpers import refresh_ward_metrics
from .state import sync_history_to_current_state
from .staffing_sync import sync_staff_counts_to_wards
from ..staff_ops import redeploy_staff_by_role


def apply_recommendation_action(state: dict, recommendation) -> tuple[dict, str]:
    if isinstance(recommendation, dict):
        ward_name = recommendation.get("ward", "").strip()
        action_type = recommendation.get("action_type", "")
        amount = int(recommendation.get("amount", 0) or 0)
    else:
        if ":" not in recommendation:
            return state, "No direct state change available for this recommendation."
        ward_name, action_text = [part.strip() for part in recommendation.split(":", 1)]
        action_lower = action_text.lower()
        amount = int(action_text.split()[1]) if len(action_text.split()) > 1 and action_text.split()[1].isdigit() else 0
        action_type = _legacy_action_type(action_lower)
    wards = [dict(ward) for ward in state["wards"]]
    target_index = next((index for index, ward in enumerate(wards) if ward["ward"] == ward_name), None)
    if target_index is None:
        return state, "Recommended ward was not found in the live state."
    ward = dict(wards[target_index])
    applied_message = "Recommendation noted, but no direct simulation change was applied."
    if action_type == "assign_nurses":
        moved, donor_wards = redeploy_staff_by_role(ward_name, "nurse", amount)
        applied_message = f"Redeployed {moved} nurse(s) to {ward_name}."
        if donor_wards:
            applied_message += f" Source ward(s): {', '.join(sorted(set(donor_wards)))}."
    elif action_type == "add_doctors":
        moved, donor_wards = redeploy_staff_by_role(ward_name, "doctor", amount)
        applied_message = f"Redeployed {moved} doctor(s) to {ward_name}."
        if donor_wards:
            applied_message += f" Source ward(s): {', '.join(sorted(set(donor_wards)))}."
    elif action_type == "redeploy_ventilators":
        ward["ventilators_available"] += amount
        applied_message = f"Redeployed {amount} ventilator(s) to {ward_name}."
    elif action_type == "move_monitors":
        ward["monitors_available"] += amount
        applied_message = f"Moved {amount} patient monitor(s) to {ward_name}."
    elif action_type == "trigger_bed_plan":
        freed_beds = min(3, ward["occupied_beds"])
        ward["occupied_beds"] -= freed_beds
        applied_message = f"Triggered overflow response for {ward_name}; released capacity for {freed_beds} bed(s)."
    elif action_type == "ringfence_discharge":
        ward["discharges_last_hour"] += 2
        ward["occupied_beds"] = max(0, ward["occupied_beds"] - 2)
        applied_message = f"Added discharge support to {ward_name}; reduced occupancy by 2 beds."
    elif action_type == "preposition_staff":
        moved_nurses, donor_nurses = redeploy_staff_by_role(ward_name, "nurse", 1)
        moved_doctors, donor_doctors = redeploy_staff_by_role(ward_name, "doctor", 1)
        ward["occupied_beds"] = max(0, ward["occupied_beds"] - 1)
        moved_total = moved_nurses + moved_doctors
        donor_wards = sorted(set(donor_nurses + donor_doctors))
        applied_message = f"Pre-positioned {moved_total} staff member(s) for {ward_name} and relieved 1 occupied bed."
        if donor_wards:
            applied_message += f" Source ward(s): {', '.join(donor_wards)}."
    elif action_type == "overflow_standby":
        ward["occupied_beds"] = max(0, ward["occupied_beds"] - 2)
        applied_message = f"Placed overflow plan on standby for {ward_name}; relieved 2 occupied beds."
    wards[target_index] = refresh_ward_metrics(ward)
    wards = sync_staff_counts_to_wards(wards)
    return sync_history_to_current_state({**state, "wards": wards}), applied_message


def _legacy_action_type(action_lower: str) -> str:
    if action_lower.startswith("assign ") and "additional nurses" in action_lower:
        return "assign_nurses"
    if action_lower.startswith("add ") and "doctor" in action_lower:
        return "add_doctors"
    if action_lower.startswith("redeploy ") and "ventilator" in action_lower:
        return "redeploy_ventilators"
    if action_lower.startswith("move ") and "patient monitor" in action_lower:
        return "move_monitors"
    if "trigger escalation bed plan" in action_lower:
        return "trigger_bed_plan"
    if "ring-fence discharge and porter support" in action_lower:
        return "ringfence_discharge"
    if "pre-position extra staff and discharge support" in action_lower:
        return "preposition_staff"
    if "move overflow plan to standby" in action_lower:
        return "overflow_standby"
    return "maintain_monitoring"
