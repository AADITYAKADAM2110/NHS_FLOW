from __future__ import annotations


SUPPORTED_ACTIONS = {
    "assign_nurses",
    "add_doctors",
    "redeploy_ventilators",
    "move_monitors",
    "trigger_bed_plan",
    "ringfence_discharge",
    "preposition_staff",
    "overflow_standby",
    "maintain_monitoring",
}


def recommendation_id(recommendation: dict) -> str:
    ward = recommendation.get("ward") or "system"
    action = recommendation.get("action_type", "unknown")
    amount = recommendation.get("amount", 0)
    return f"{ward}:{action}:{amount}"


def recommendation_text(recommendation: dict) -> str:
    ward = recommendation.get("ward", "System")
    amount = int(recommendation.get("amount", 0))
    action = recommendation.get("action_type")
    templates = {
        "assign_nurses": f"{ward}: assign {amount} additional nurses for the next shift.",
        "add_doctors": f"{ward}: add {amount} doctor(s) to maintain safe coverage.",
        "redeploy_ventilators": f"{ward}: redeploy {amount} ventilator(s) from lower-acuity wards.",
        "move_monitors": f"{ward}: move {amount} patient monitor(s) into the ward.",
        "trigger_bed_plan": f"{ward}: predicted to hit full capacity tomorrow, trigger escalation bed plan.",
        "ringfence_discharge": f"{ward}: predicted near full tomorrow, ring-fence discharge and porter support.",
        "preposition_staff": f"{ward}: occupancy above 80%, pre-position extra staff and discharge support.",
        "overflow_standby": f"{ward}: occupancy above 90%, move overflow plan to standby.",
        "maintain_monitoring": "Current staffing and equipment coverage is within the recommended operating range.",
    }
    return templates.get(action, recommendation.get("text", "Recommendation unavailable."))


def normalize_recommendation(payload: dict) -> dict | None:
    action = payload.get("action_type")
    if action not in SUPPORTED_ACTIONS:
        return None
    normalized = {
        "ward": payload.get("ward", "System"),
        "action_type": action,
        "amount": max(0, int(payload.get("amount", 0) or 0)),
        "priority": payload.get("priority", "medium"),
        "reason": payload.get("reason", "").strip(),
        "source": payload.get("source", "rules"),
    }
    normalized["id"] = recommendation_id(normalized)
    normalized["text"] = recommendation_text(normalized)
    return normalized
