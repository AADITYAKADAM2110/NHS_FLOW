from .constants import (
    FORECAST_MODEL_NAME,
    HISTORY_LIMIT,
    SIMULATION_START,
    SIMULATION_STEP_HOURS,
    STATE_FILE,
    UPDATE_INTERVAL_SECONDS,
)
try:
    from .ai_recommendations import build_ai_recommendations
except ImportError:
    def build_ai_recommendations(snapshot, simulation_now):
        return []

from .emergency_actions import (
    apply_emergency_capacity,
    apply_emergency_staffing,
    apply_full_emergency_stabilization,
)
try:
    from .forecasting import build_history_frame, predict_tomorrow
except ImportError:
    def build_history_frame(state):
        import pandas as pd
        return pd.DataFrame()
    def predict_tomorrow(history):
        return {}
from .manual_ops import advance_hospital_day, set_operation_mode, update_ward_state
from .manager_agent import build_manager_snapshot, run_manager_agent_cycle
from .map_data import build_hospital_map
from .models import WARD_PROFILES, WardProfile
from .recommendation_actions import apply_recommendation_action
from .recommendation_schema import normalize_recommendation, recommendation_id, recommendation_text
from .recommendations import build_recommendations, update_recommendation_log
from .simulation import simulate_realtime
from .snapshot import build_operational_snapshot, build_system_totals
from .state import build_realtime_state, load_realtime_state, save_realtime_state, sync_history_to_current_state
