from __future__ import annotations

from datetime import datetime

import pandas as pd

from .ai_recommendations import build_ai_recommendations
from .forecasting import build_history_frame, predict_tomorrow
from .patient_flow import patient_outcome_summary
from .recommendation_actions import apply_recommendation_action
from .recommendation_schema import normalize_recommendation
from .recommendations import build_recommendations, update_recommendation_log

MANAGER_LOG_LIMIT = 600
MANAGER_INTERVIEW_LIMIT = 300
MANAGER_MEMORY_ACTION_LIMIT = 12
MANAGER_REPEATED_FAILURE_LIMIT = 6


def build_manager_snapshot(state: dict) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    history = build_history_frame(state)
    rows = []
    alerts = []
    for ward in state["wards"]:
        forecast = predict_tomorrow(history[history["ward"] == ward["ward"]], ward["capacity"])
        pressure = ward["occupancy_rate"]
        if pressure >= 0.9:
            alerts.append(f"{ward['ward']}: occupancy above 90%, move overflow plan to standby.")
        elif pressure >= 0.8:
            alerts.append(f"{ward['ward']}: occupancy above 80%, pre-position extra staff and discharge support.")
        rows.append(
            {
                "Ward": ward["ward"],
                "Occupied Beds": ward["occupied_beds"],
                "Capacity": ward["capacity"],
                "Occupancy %": round(pressure * 100, 1),
                "Admissions/hr": ward["admissions_last_hour"],
                "Discharges/hr": ward["discharges_last_hour"],
                "Predicted Avg Tomorrow": forecast["predicted_avg"],
                "Predicted Peak Tomorrow": forecast["predicted_peak"],
                "Nurses Available": ward["nurses_available"],
                "Nurses Required": ward["required_nurses"],
                "Doctors Available": ward["doctors_available"],
                "Doctors Required": ward["required_doctors"],
                "Ventilators Available": ward["ventilators_available"],
                "Ventilators Required": ward["required_ventilators"],
                "Monitors Available": ward["monitors_available"],
                "Monitors Required": ward["required_monitors"],
            }
        )
    snapshot = pd.DataFrame(rows).sort_values("Occupancy %", ascending=False)
    return snapshot, history, alerts


def run_manager_agent_cycle(
    state: dict,
    snapshot: pd.DataFrame,
    alerts: list[str],
    simulation_now: datetime,
) -> tuple[dict, list[dict], bool]:
    recommendations = _build_manager_recommendations(state, snapshot, alerts, simulation_now)
    updated_state, visible = update_recommendation_log(state, recommendations)
    manager_state = dict(updated_state.get("manager_agent", {}))
    snapshot_key = f"{simulation_now.isoformat()}::{snapshot.to_json(orient='records')}"
    if manager_state.get("last_cycle_key") == snapshot_key:
        manager_state["last_visible"] = visible
        updated_state["manager_agent"] = manager_state
        return updated_state, visible, False

    updated_state = _append_manager_log(updated_state, recommendations, simulation_now, "recommended")
    applied = False
    applied_ids = []
    if manager_state.get("enabled", True) and manager_state.get("mode", "auto") == "auto":
        actionable = _dedupe_recommendations(
            recommendation for recommendation in visible if recommendation["action_type"] != "maintain_monitoring"
        )
        for recommendation in actionable:
            before_outcomes = patient_outcome_summary(updated_state)
            updated_state, message = apply_recommendation_action(updated_state, recommendation)
            updated_state = _append_manager_log(
                updated_state,
                [recommendation],
                simulation_now,
                "applied",
                message=message,
                before_outcomes=before_outcomes,
                after_outcomes=patient_outcome_summary(updated_state),
            )
            updated_state = _append_manager_interview(
                updated_state,
                recommendation,
                simulation_now,
                before_outcomes,
                patient_outcome_summary(updated_state),
                message,
            )
            applied_ids.append(recommendation["id"])
            applied = True

    manager_state = dict(updated_state.get("manager_agent", {}))
    manager_state.update(
        {
            "enabled": manager_state.get("enabled", True),
            "mode": manager_state.get("mode", "auto"),
            "last_cycle_key": snapshot_key,
            "last_run_at": simulation_now.isoformat(),
            "last_recommendation_count": len(visible),
            "last_applied_ids": applied_ids,
            "last_visible": visible,
            "last_summary": _build_manager_summary(visible, applied_ids),
            "last_memory_summary": _build_memory_summary(_build_manager_context(updated_state, snapshot, alerts)),
        }
    )
    updated_state["manager_agent"] = manager_state
    return updated_state, visible, applied


def _build_manager_recommendations(
    state: dict,
    snapshot: pd.DataFrame,
    alerts: list[str],
    simulation_now: datetime,
) -> list[dict]:
    alert_items = []
    for alert in alerts:
        ward = alert.split(":", 1)[0].strip()
        action_type = "overflow_standby" if "above 90%" in alert else "preposition_staff"
        alert_items.append(
            normalize_recommendation(
                {"ward": ward, "action_type": action_type, "priority": "high", "reason": alert}
            )
        )
    fallback = _dedupe_recommendations(item for item in alert_items + build_recommendations(snapshot) if item)
    snapshot_key = f"{simulation_now.isoformat()}::{snapshot.to_json(orient='records')}"
    cache = state.get("recommendation_cache", {})
    if cache.get("snapshot_key") == snapshot_key:
        return cache.get("items", fallback)
    strategic_context = _build_manager_context(state, snapshot, alerts)
    try:
        ai_items = build_ai_recommendations(snapshot, simulation_now, strategic_context=strategic_context)
    except Exception:
        ai_items = []
    items = _dedupe_recommendations(ai_items or fallback)
    state["recommendation_cache"] = {"snapshot_key": snapshot_key, "items": items}
    return items


def _dedupe_recommendations(recommendations) -> list[dict]:
    deduped = []
    seen = set()
    for recommendation in recommendations:
        recommendation_id = recommendation["id"]
        if recommendation_id in seen:
            continue
        seen.add(recommendation_id)
        deduped.append(recommendation)
    return deduped


def _append_manager_log(
    state: dict,
    recommendations: list[dict],
    simulation_now: datetime,
    event: str,
    message: str = "",
    before_outcomes: dict | None = None,
    after_outcomes: dict | None = None,
) -> dict:
    log = list(state.get("manager_decision_log", []))
    for recommendation in recommendations:
        log.append(
            {
                "timestamp": simulation_now.isoformat(),
                "event": event,
                "ward": recommendation["ward"],
                "action_type": recommendation["action_type"],
                "amount": recommendation.get("amount", 0),
                "priority": recommendation.get("priority", "medium"),
                "source": recommendation.get("source", "rules"),
                "reason": recommendation.get("reason", ""),
                "message": message,
                "recommendation_id": recommendation["id"],
                "patient_outcomes_before": before_outcomes or {},
                "patient_outcomes_after": after_outcomes or {},
            }
        )
    return {**state, "manager_decision_log": log[-MANAGER_LOG_LIMIT:]}


def _append_manager_interview(
    state: dict,
    recommendation: dict,
    simulation_now: datetime,
    before_outcomes: dict,
    after_outcomes: dict,
    message: str,
) -> dict:
    interviews = list(state.get("manager_interviews", []))
    interviews.append(
        {
            "timestamp": simulation_now.isoformat(),
            "recommendation_id": recommendation["id"],
            "ward": recommendation["ward"],
            "source": recommendation.get("source", "rules"),
            "qa": [
                {
                    "question": "What signal made you act now?",
                    "answer": recommendation.get("reason") or f"{recommendation['ward']} showed pressure requiring intervention.",
                },
                {
                    "question": "Why this action instead of simply reducing occupancy?",
                    "answer": (
                        f"I used `{recommendation['action_type']}` because occupancy must be linked to patient transitions, "
                        "staff movement, or equipment coverage rather than raw bed-count edits."
                    ),
                },
                {
                    "question": "What patient safeguard did you apply?",
                    "answer": (
                        f"Only eligible patient-flow transitions were allowed. Outcomes before: {before_outcomes}. "
                        f"Outcomes after: {after_outcomes}."
                    ),
                },
                {
                    "question": "What outcome did you expect from this decision?",
                    "answer": message or "Expected lower operational pressure with an auditable patient impact.",
                },
                {
                    "question": "What would make you change this decision next cycle?",
                    "answer": "If staffing gaps, equipment gaps, or unsafe patient outcomes worsen, I would change or withdraw the intervention.",
                },
            ],
        }
    )
    return {**state, "manager_interviews": interviews[-MANAGER_INTERVIEW_LIMIT:]}


def _build_manager_summary(recommendations: list[dict], applied_ids: list[str]) -> str:
    if not recommendations:
        return "Manager agent is monitoring hospital flow with no active interventions."
    if not applied_ids:
        return f"Manager agent reviewed {len(recommendations)} recommendation(s) and held position."
    return (
        f"Manager agent reviewed {len(recommendations)} recommendation(s) and auto-applied "
        f"{len(applied_ids)} action(s)."
    )


def _build_manager_context(state: dict, snapshot: pd.DataFrame, alerts: list[str]) -> dict:
    recent_actions = _recent_applied_actions(state)
    return {
        "active_alerts": alerts[:5],
        "unresolved_issues": _build_unresolved_issues(snapshot),
        "recent_actions": recent_actions,
        "repeated_failures": _build_repeated_failures(recent_actions),
    }


def _recent_applied_actions(state: dict) -> list[dict]:
    entries = [
        entry
        for entry in state.get("manager_decision_log", [])
        if entry.get("event") == "applied"
    ]
    recent = entries[-MANAGER_MEMORY_ACTION_LIMIT:]
    return [
        {
            "timestamp": entry.get("timestamp"),
            "ward": entry.get("ward"),
            "action_type": entry.get("action_type"),
            "source": entry.get("source", "rules"),
            "reason": entry.get("reason", ""),
            "message": entry.get("message", ""),
            "result": _classify_action_result(entry),
        }
        for entry in recent
    ]


def _classify_action_result(entry: dict) -> str:
    message = str(entry.get("message", "")).lower()
    before = entry.get("patient_outcomes_before", {}) or {}
    after = entry.get("patient_outcomes_after", {}) or {}
    active_delta = after.get("active", 0) - before.get("active", 0)
    discharged_delta = after.get("discharged", 0) - before.get("discharged", 0)
    deceased_delta = after.get("deceased", 0) - before.get("deceased", 0)

    if "redeployed 0 nurse" in message or "redeployed 0 doctor" in message:
        return "ineffective"
    if "redeployed 0 ventilator" in message or "moved 0 patient monitor" in message:
        return "ineffective"
    if "transitioned 0 eligible patient" in message:
        return "ineffective"
    if deceased_delta > 0:
        return "harmful"
    if active_delta < 0 or discharged_delta > 0:
        return "helpful"
    if "redeployed " in message or "moved " in message or "pre-positioned " in message:
        return "mixed"
    return "neutral"


def _build_unresolved_issues(snapshot: pd.DataFrame) -> list[dict]:
    issues = []
    for row in snapshot.to_dict(orient="records"):
        ward = row["Ward"]
        nurse_gap = max(0, row["Nurses Required"] - row["Nurses Available"])
        doctor_gap = max(0, row["Doctors Required"] - row["Doctors Available"])
        ventilator_gap = max(0, row["Ventilators Required"] - row["Ventilators Available"])
        monitor_gap = max(0, row["Monitors Required"] - row["Monitors Available"])
        if row["Occupancy %"] >= 80 or nurse_gap or doctor_gap or ventilator_gap or monitor_gap:
            issues.append(
                {
                    "ward": ward,
                    "occupancy_pct": row["Occupancy %"],
                    "nurse_gap": nurse_gap,
                    "doctor_gap": doctor_gap,
                    "ventilator_gap": ventilator_gap,
                    "monitor_gap": monitor_gap,
                    "predicted_peak_tomorrow": row["Predicted Peak Tomorrow"],
                }
            )
    return issues[:6]


def _build_repeated_failures(recent_actions: list[dict]) -> list[dict]:
    grouped = {}
    for item in recent_actions:
        if item["result"] != "ineffective":
            continue
        key = (item["ward"], item["action_type"])
        grouped[key] = grouped.get(key, 0) + 1
    failures = [
        {"ward": ward, "action_type": action_type, "count": count}
        for (ward, action_type), count in grouped.items()
        if count >= 2
    ]
    failures.sort(key=lambda item: item["count"], reverse=True)
    return failures[:MANAGER_REPEATED_FAILURE_LIMIT]


def _build_memory_summary(context: dict) -> str:
    failures = context.get("repeated_failures", [])
    unresolved = context.get("unresolved_issues", [])
    if not failures and not unresolved:
        return "No unresolved operational issues or repeated ineffective actions."
    parts = []
    if failures:
        failure_text = ", ".join(
            f"{item['ward']}:{item['action_type']} x{item['count']}" for item in failures[:3]
        )
        parts.append(f"Repeated ineffective actions: {failure_text}")
    if unresolved:
        unresolved_text = ", ".join(
            f"{item['ward']} occ={item['occupancy_pct']:.1f}% nurse_gap={item['nurse_gap']} doctor_gap={item['doctor_gap']}"
            for item in unresolved[:3]
        )
        parts.append(f"Current unresolved issues: {unresolved_text}")
    return ". ".join(parts)
