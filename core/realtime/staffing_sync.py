from __future__ import annotations

import json
from pathlib import Path

from .helpers import refresh_ward_metrics
from ..staff_ops import summarize_staff_by_ward

DATA_DIR = Path(__file__).parent.parent / "data"
STAFF_FILE = DATA_DIR / "staff.json"


def load_staff_counts() -> dict[str, dict[str, int]]:
    if not STAFF_FILE.exists():
        return {}
    try:
        records = json.loads(STAFF_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return summarize_staff_by_ward(records)


def sync_staff_counts_to_wards(wards: list[dict]) -> list[dict]:
    counts = load_staff_counts()
    synced = []
    for ward in wards:
        current = dict(ward)
        ward_counts = counts.get(current.get("ward", ""), {})
        if ward_counts:
            current["nurses_available"] = ward_counts.get("nurses_available", current.get("nurses_available", 0))
            current["doctors_available"] = ward_counts.get("doctors_available", current.get("doctors_available", 0))
            current["support_available"] = ward_counts.get("support_available", current.get("support_available", 0))
        synced.append(refresh_ward_metrics(current))
    return synced


def strip_staffing_fields(ward: dict) -> dict:
    return {
        key: value
        for key, value in ward.items()
        if key not in {"nurses_available", "doctors_available", "support_available"}
    }
