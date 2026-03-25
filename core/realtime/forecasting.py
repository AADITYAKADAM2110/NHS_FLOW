from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pandas as pd


def build_history_frame(state: dict) -> pd.DataFrame:
    history = pd.DataFrame(state["history"])
    if history.empty:
        return history
    history["timestamp"] = pd.to_datetime(history["timestamp"])
    history["occupancy_rate"] = history["occupied_beds"] / history["capacity"]
    return history.sort_values(["timestamp", "ward"]).reset_index(drop=True)


def predict_tomorrow(history: pd.DataFrame, capacity: int) -> dict[str, int]:
    if history.empty or len(history) < 6:
        fallback = int(capacity * 0.72)
        return {"predicted_avg": fallback, "predicted_peak": min(capacity, fallback + 2)}
    ordered = history.sort_values("timestamp").copy()
    ordered["t"] = np.arange(len(ordered))
    ordered["dow"] = ordered["timestamp"].dt.dayofweek
    x = np.column_stack([
        np.ones(len(ordered)),
        ordered["t"].to_numpy(),
        np.sin(2 * np.pi * ordered["dow"].to_numpy() / 7),
        np.cos(2 * np.pi * ordered["dow"].to_numpy() / 7),
    ])
    y = ordered["occupied_beds"].to_numpy()
    try:
        coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    except np.linalg.LinAlgError:
        mean_value = int(round(float(np.mean(y))))
        return {"predicted_avg": mean_value, "predicted_peak": min(capacity, mean_value + 2)}
    future_rows = []
    start = ordered["timestamp"].max() + timedelta(days=1)
    base_t = int(ordered["t"].iloc[-1])
    for step in range(1, 8):
        forecast_time = start + timedelta(days=step - 1)
        dow = forecast_time.weekday()
        future_rows.append([1.0, base_t + step, math.sin(2 * math.pi * dow / 7), math.cos(2 * math.pi * dow / 7)])
    clipped = np.clip(np.dot(np.array(future_rows), coefficients), 0, capacity)
    return {
        "predicted_avg": int(round(float(np.mean(clipped)))),
        "predicted_peak": int(round(float(np.max(clipped)))),
    }
