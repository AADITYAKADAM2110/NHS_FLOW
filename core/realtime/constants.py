from __future__ import annotations

from datetime import datetime
from pathlib import Path


UPDATE_INTERVAL_SECONDS = 60
HISTORY_LIMIT = 120
SIMULATION_STEP_HOURS = 24
SIMULATION_START = datetime(2026, 4, 1, 6, 0)
STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "realtime_state.json"
FORECAST_MODEL_NAME = "Linear regression with trend + weekly seasonality"
