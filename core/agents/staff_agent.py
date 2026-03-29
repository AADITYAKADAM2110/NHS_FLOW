from .core_agent import Agent
import pandas as pd

from core.realtime.ai_recommendations import build_ai_recommendations
from core.realtime.forecasting import build_history_frame, predict_tomorrow
from core.realtime.recommendation_actions import apply_recommendation_action
from core.realtime.recommendation_schema import normalize_recommendation

instructions = (
        "You are a hospital operations analyst responsible for monitoring ward capacity and staffing. Observe the current state of each ward, including occupancy, staffing levels, and predicted demand. "
        "Provide actionable insights and recommendations to optimize resource allocation and patient care."
        "When generating recommendations, focus on specific actions such as redeploying staff, moving equipment, or triggering overflow plans. Prioritize recommendations based on urgency and potential impact. Do not provide generic advice; instead, offer clear, operational steps that can be taken to address capacity and staffing challenges in the hospital. Only include recommendations that can be directly applied to the simulation state, and ensure they are concise and actionable. You've observed the following ward states: {snapshot}. Based on this information, generate specific recommendations for improving hospital operations. These recommendations should be in the form of a JSON array, where each item includes the ward, action_type, amount, priority, and reason for the recommendation. Allowed action_type values include: assign_nurses, add_doctors, redeploy_ventilators, move_monitors, trigger_bed_plan, ringfence_discharge, preposition_staff, overflow_standby, maintain_monitoring. These are your tools for improving hospital operations. Use them wisely to address the challenges faced by each ward and optimize patient care across the hospital."
    )

class StaffAgent(Agent):
    def __init__(self, name, instructions, tools, model="gpt-4.1-nano"):
        super().__init__(name=name, instructions=instructions, tools=tools, model=model)

    def observe(self, state: dict):
        self.state = state
        self.history = build_history_frame(state)
        self.snapshot = self.build_snapshot()
        self.recommendations = build_ai_recommendations(
            self.snapshot,
            state.get("simulation_now", state["last_updated"]),
        )


    def act(self) -> str:
        if not self.recommendations:
            return "No recommendations generated."
        applied_messages = []
        for recommendation in self.recommendations:
            normalized = normalize_recommendation(recommendation)
            if normalized:
                updated_state, message = apply_recommendation_action(self.state, normalized)
                self.state.update(updated_state)
                applied_messages.append(message)
        return "\n".join(applied_messages) if applied_messages else "No valid recommendations to apply."
    
    def build_snapshot(self) -> pd.DataFrame:
        snapshot = []
        for ward in self.state["wards"]:
            forecast = predict_tomorrow(self.history[self.history["ward"] == ward["ward"]], ward["capacity"])
            snapshot.append({
                "ward": ward["ward"],
                "occupied_beds": ward["occupied_beds"],
                "capacity": ward["capacity"],
                "occupancy_rate": round(ward["occupied_beds"] / ward["capacity"], 3) if ward["capacity"] else 0.0,
                "admissions_last_hour": ward["admissions_last_hour"],
                "discharges_last_hour": ward["discharges_last_hour"],
                "predicted_avg_tomorrow": forecast["predicted_avg"],
                "predicted_peak_tomorrow": forecast["predicted_peak"],
                "nurses_available": ward["nurses_available"],
                "required_nurses": ward["required_nurses"],
                "doctors_available": ward["doctors_available"],
                "required_doctors": ward["required_doctors"],
                "ventilators_available": ward["ventilators_available"],
                "required_ventilators": ward["required_ventilators"],
                "monitors_available": ward["monitors_available"],
                "required_monitors": ward["required_monitors"],
            })
        return pd.DataFrame(snapshot)
    



    
