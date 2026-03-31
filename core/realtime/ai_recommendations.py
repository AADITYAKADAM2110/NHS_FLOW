from __future__ import annotations

import json

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None

from .recommendation_schema import normalize_recommendation


def build_ai_recommendations(snapshot, simulation_now, strategic_context: dict | None = None) -> list[dict]:
    if not OPENAI_AVAILABLE:
        # Fallback: return empty list when OpenAI is not available
        return []
    
    records = snapshot.to_dict(orient="records")
    strategic_context = strategic_context or {}
    prompt = (
        "You are an NHS hospital operations analyst. "
        "Return a JSON array only. Each item must contain ward, action_type, amount, priority, and reason. "
        "Allowed action_type values: assign_nurses, add_doctors, redeploy_ventilators, move_monitors, "
        "trigger_bed_plan, ringfence_discharge, preposition_staff, overflow_standby, maintain_monitoring. "
        "Use only the wards and metrics provided. Keep recommendations operational, specific, and concise. "
        "Treat the strategic context as memory from prior cycles. Avoid repeating an ineffective action in the same ward "
        "unless the problem has clearly worsened or you explicitly explain why repetition is still justified. "
        "Prioritize unresolved constraints and diversify tactics when recent actions had little effect.\n\n"
        f"Simulated hospital time: {simulation_now.isoformat()}\n"
        f"Ward metrics: {json.dumps(records)}\n"
        f"Strategic context: {json.dumps(strategic_context)}"
    )
    response = OpenAI().responses.create(model="gpt-4.1-nano", input=prompt)
    parsed = json.loads((response.output_text or "[]").strip())
    if not isinstance(parsed, list):
        return []
    recommendations = []
    for item in parsed:
        if isinstance(item, dict):
            normalized = normalize_recommendation({**item, "source": "ai"})
            if normalized:
                recommendations.append(normalized)
    return recommendations[:8]
