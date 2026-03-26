from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).parent / "data"
STAFF_FILE = DATA_DIR / "staff.json"
ACTIVE_STATUSES = {"available", "on duty"}


def load_staff_records() -> list[dict]:
    if not STAFF_FILE.exists():
        return []
    try:
        return json.loads(STAFF_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []


def save_staff_records(records: list[dict]) -> None:
    STAFF_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")


def assign_staff_member(staff_id: str, ward: str, shift: str, status: str) -> tuple[bool, str]:
    records = load_staff_records()
    target_index = next((index for index, row in enumerate(records) if row.get("staff_id") == staff_id), None)
    if target_index is None:
        return False, "Selected staff member was not found."

    updated = dict(records[target_index])
    updated["ward"] = ward
    updated["shift"] = shift
    updated["status"] = status
    updated["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records[target_index] = updated
    save_staff_records(records)
    return True, f"{updated.get('name', staff_id)} assigned to {ward} on {shift} shift."


def summarize_staff_by_ward(records: list[dict] | None = None) -> dict[str, dict[str, int]]:
    records = records if records is not None else load_staff_records()
    wards = sorted({row.get("ward") for row in records if row.get("ward")})
    summary: dict[str, dict[str, int]] = {}
    for ward in wards:
        ward_records = [row for row in records if row.get("ward") == ward]
        ward_total = len(ward_records)
        
        active_records = [row for row in ward_records if str(row.get("status", "")).strip().lower() in ACTIVE_STATUSES]
        active_total = len(active_records)
        
        nurse_records = [row for row in ward_records if str(row.get("role", "")).strip().lower() == "nurse"]
        nurses_total = len(nurse_records)
        
        doctor_records = [row for row in ward_records if str(row.get("role", "")).strip().lower() == "doctor"]
        doctors_total = len(doctor_records)
        
        support_records = [row for row in ward_records if str(row.get("role", "")).strip().lower() == "support"]
        support_total = len(support_records)
        
        active_nurse_records = [row for row in nurse_records if str(row.get("status", "")).strip().lower() in ACTIVE_STATUSES]
        nurses_available = len(active_nurse_records)
        
        active_doctor_records = [row for row in doctor_records if str(row.get("status", "")).strip().lower() in ACTIVE_STATUSES]
        doctors_available = len(active_doctor_records)
        
        active_support_records = [row for row in support_records if str(row.get("status", "")).strip().lower() in ACTIVE_STATUSES]
        support_available = len(active_support_records)

        summary[ward] = {
            "total": ward_total,
            "nurses": nurses_total,
            "doctors": doctors_total,
            "support": support_total,
            "active_total": active_total,
            "nurses_available": nurses_available,
            "doctors_available": doctors_available,
            "support_available": support_available,
        }
    return summary


def redeploy_staff_by_role(target_ward: str, role: str, amount: int) -> tuple[int, list[str]]:
    records = load_staff_records()
    moved_count, donor_wards = _redeploy_staff_records(records, target_ward, role, amount)
    if moved_count:
        save_staff_records(records)
    return moved_count, donor_wards


def _redeploy_staff_records(records: list[dict], target_ward: str, role: str, amount: int) -> tuple[int, list[str]]:
    normalized_role = role.strip().lower()
    if amount <= 0:
        return 0, []

    moved = 0
    donor_wards: list[str] = []

    while moved < amount:
        summary = summarize_staff_by_ward(records)
        donor_candidates = []
        for ward_name, ward_summary in summary.items():
            if ward_name == target_ward:
                continue
            available_key = f"{normalized_role}s_available"
            if ward_summary.get(available_key, 0) <= 1:
                continue
            donor_candidates.append((ward_summary.get(available_key, 0), ward_name))

        if not donor_candidates:
            break

        donor_candidates.sort(key=lambda item: (-item[0], item[1]))
        donor_ward = donor_candidates[0][1]
        staff_index = next(
            (
                index
                for index, row in enumerate(records)
                if row.get("ward") == donor_ward
                and str(row.get("role", "")).strip().lower() == normalized_role
                and str(row.get("status", "")).strip().lower() in ACTIVE_STATUSES
            ),
            None,
        )
        if staff_index is None:
            break

        updated = dict(records[staff_index])
        updated["ward"] = target_ward
        updated["status"] = "On duty"
        updated["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        records[staff_index] = updated
        moved += 1
        donor_wards.append(donor_ward)

    return moved, donor_wards
