from __future__ import annotations

import random
from datetime import datetime, timedelta

from .helpers import refresh_ward_metrics

WARD_STAY_DAYS = {
    "ICU": (4, 8),
    "Emergency": (1, 3),
    "General": (3, 6),
    "Surgery": (2, 5),
    "Maternity": (2, 4),
}

WARD_DEATH_RISK = {
    "ICU": 0.045,
    "Emergency": 0.02,
    "General": 0.006,
    "Surgery": 0.01,
    "Maternity": 0.002,
}

ACUITY_LEVELS = ("low", "moderate", "high", "critical")


def build_initial_patients(wards: list[dict], simulation_now: datetime) -> tuple[list[dict], list[dict], int]:
    patients = []
    events = []
    counter = 0
    for ward in wards:
        for index in range(ward["occupied_beds"]):
            counter += 1
            patient = _build_patient(
                ward_name=ward["ward"],
                patient_number=counter,
                admitted_at=simulation_now - timedelta(days=(index % 4) + 1),
                seeded_random=random.Random(f"seed-{ward['ward']}-{counter}"),
            )
            patients.append(patient)
            events.append(_patient_event(patient, "admitted", patient["admitted_at"], note="Initial seeded census"))
    return patients, events, counter


def simulate_patient_step(state: dict, simulated_timestamp: datetime) -> tuple[list[dict], list[dict], list[dict], dict]:
    next_counter = int(state.get("patient_counter", 0))
    patients = [dict(patient) for patient in state.get("patients", [])]
    events = list(state.get("patient_events", []))
    wards = []
    outcomes = {}
    for ward in state["wards"]:
        updated_ward, patients, ward_events, next_counter, ward_outcomes = _simulate_ward_patients(
            ward,
            patients,
            simulated_timestamp,
            next_counter,
        )
        wards.append(updated_ward)
        events.extend(ward_events)
        outcomes[ward["ward"]] = ward_outcomes
    return wards, patients, events[-800:], {"patient_counter": next_counter, "outcomes": outcomes}


def apply_patient_flow_action(
    state: dict,
    ward_name: str,
    max_patients: int,
    action_type: str,
    simulation_now: datetime | None = None,
) -> tuple[dict, int]:
    simulation_now = simulation_now or state.get("simulation_now")
    patients = [dict(patient) for patient in state.get("patients", [])]
    patient_events = list(state.get("patient_events", []))
    active_indexes = [
        index for index, patient in enumerate(patients)
        if patient.get("ward") == ward_name and patient.get("status") == "active"
    ]
    eligible = sorted(
        active_indexes,
        key=lambda index: (
            _discharge_priority(patients[index], simulation_now),
            patients[index]["admitted_at"],
        ),
        reverse=True,
    )
    applied = 0
    for index in eligible:
        if applied >= max_patients:
            break
        patient = dict(patients[index])
        if not _is_discharge_eligible(patient, simulation_now):
            continue
        patient["status"] = "discharged"
        patient["outcome"] = "discharged"
        patient["discharged_at"] = simulation_now
        patient["disposition_reason"] = action_type
        patients[index] = patient
        patient_events.append(
            _patient_event(
                patient,
                "discharged",
                simulation_now,
                note=f"Manager action: {action_type}",
            )
        )
        applied += 1
    wards = _rebuild_wards_from_patients(state["wards"], patients)
    updated_state = {
        **state,
        "wards": wards,
        "patients": patients,
        "patient_events": patient_events[-800:],
    }
    return updated_state, applied


def patient_outcome_summary(state: dict) -> dict[str, int]:
    summary = {"active": 0, "discharged": 0, "deceased": 0}
    for patient in state.get("patients", []):
        outcome = patient.get("outcome") or ("active" if patient.get("status") == "active" else patient.get("status"))
        if outcome in summary:
            summary[outcome] += 1
    return summary


def _simulate_ward_patients(
    ward: dict,
    patients: list[dict],
    simulated_timestamp: datetime,
    patient_counter: int,
) -> tuple[dict, list[dict], list[dict], int, dict]:
    seeded_random = random.Random(f"{ward['ward']}-{simulated_timestamp.isoformat(timespec='minutes')}")
    active_indexes = [
        index for index, patient in enumerate(patients)
        if patient.get("ward") == ward["ward"] and patient.get("status") == "active"
    ]
    ward_events = []
    discharges = 0
    deaths = 0
    occupancy_pressure = round(len(active_indexes) / ward["capacity"], 3) if ward["capacity"] else 0.0
    for index in active_indexes:
        patient = dict(patients[index])
        if _should_record_death(patient, ward["ward"], occupancy_pressure, simulated_timestamp, seeded_random):
            patient["status"] = "deceased"
            patient["outcome"] = "deceased"
            patient["died_at"] = simulated_timestamp
            patients[index] = patient
            ward_events.append(_patient_event(patient, "deceased", simulated_timestamp, note="Simulated deterioration"))
            deaths += 1
            continue
        if _should_discharge_patient(patient, simulated_timestamp, seeded_random):
            patient["status"] = "discharged"
            patient["outcome"] = "discharged"
            patient["discharged_at"] = simulated_timestamp
            patients[index] = patient
            ward_events.append(_patient_event(patient, "discharged", simulated_timestamp, note="Routine discharge"))
            discharges += 1
    admissions_target = _admissions_for_ward(ward["ward"], simulated_timestamp, seeded_random)
    if len([patient for patient in patients if patient.get("ward") == ward["ward"] and patient.get("status") == "active"]) >= ward["capacity"]:
        admissions_target = max(0, admissions_target - 1)
    for _ in range(admissions_target):
        patient_counter += 1
        patient = _build_patient(ward["ward"], patient_counter, simulated_timestamp, seeded_random)
        patients.append(patient)
        ward_events.append(_patient_event(patient, "admitted", simulated_timestamp, note="Simulated admission"))
    active_patients = [
        patient for patient in patients
        if patient.get("ward") == ward["ward"] and patient.get("status") == "active"
    ]
    updated_ward = refresh_ward_metrics(
        {
            **ward,
            "occupied_beds": len(active_patients),
            "admissions_last_hour": admissions_target,
            "discharges_last_hour": discharges + deaths,
        }
    )
    return updated_ward, patients, ward_events, patient_counter, {
        "admissions": admissions_target,
        "discharges": discharges,
        "deaths": deaths,
        "active": len(active_patients),
    }


def _admissions_for_ward(ward_name: str, simulated_timestamp: datetime, seeded_random: random.Random) -> int:
    base = {
        "ICU": seeded_random.uniform(0.3, 1.8),
        "Emergency": seeded_random.uniform(2.0, 4.5),
        "General": seeded_random.uniform(1.2, 3.3),
        "Surgery": seeded_random.uniform(1.0, 2.5),
        "Maternity": seeded_random.uniform(0.6, 1.8),
    }[ward_name]
    if ward_name == "Surgery" and 6 <= simulated_timestamp.hour <= 18:
        base += 0.8
    if ward_name == "Emergency" and simulated_timestamp.hour >= 18:
        base += 0.5
    return max(0, round(base))


def _build_patient(
    ward_name: str,
    patient_number: int,
    admitted_at: datetime,
    seeded_random: random.Random,
) -> dict:
    stay_min, stay_max = WARD_STAY_DAYS[ward_name]
    acuity_weights = {
        "ICU": (0.05, 0.2, 0.4, 0.35),
        "Emergency": (0.15, 0.45, 0.3, 0.1),
        "General": (0.35, 0.45, 0.17, 0.03),
        "Surgery": (0.2, 0.5, 0.25, 0.05),
        "Maternity": (0.45, 0.45, 0.08, 0.02),
    }[ward_name]
    acuity = seeded_random.choices(ACUITY_LEVELS, weights=acuity_weights, k=1)[0]
    expected_stay_days = seeded_random.randint(stay_min, stay_max)
    return {
        "patient_id": f"PT-{patient_number:05d}",
        "ward": ward_name,
        "status": "active",
        "outcome": "active",
        "acuity": acuity,
        "expected_stay_days": expected_stay_days,
        "admitted_at": admitted_at,
        "discharge_ready_at": admitted_at + timedelta(days=max(1, expected_stay_days - 1)),
    }


def _patient_event(patient: dict, event_type: str, timestamp: datetime, note: str = "") -> dict:
    return {
        "patient_id": patient["patient_id"],
        "ward": patient["ward"],
        "event": event_type,
        "timestamp": timestamp,
        "acuity": patient.get("acuity", "moderate"),
        "note": note,
    }


def _should_discharge_patient(patient: dict, simulated_timestamp: datetime, seeded_random: random.Random) -> bool:
    if not _is_discharge_eligible(patient, simulated_timestamp):
        return False
    readiness_bonus = 0.2 if patient.get("acuity") in {"low", "moderate"} else 0.0
    return seeded_random.random() < min(0.85, 0.45 + readiness_bonus)


def _is_discharge_eligible(patient: dict, simulated_timestamp: datetime) -> bool:
    if patient.get("status") != "active":
        return False
    if patient.get("acuity") == "critical":
        return False
    ready_at = patient.get("discharge_ready_at")
    return bool(ready_at and simulated_timestamp >= ready_at)


def _discharge_priority(patient: dict, simulation_now: datetime) -> tuple[int, float]:
    elapsed_days = max(0.0, (simulation_now - patient["admitted_at"]).total_seconds() / 86400)
    readiness = 1 if _is_discharge_eligible(patient, simulation_now) else 0
    acuity_priority = {"low": 3, "moderate": 2, "high": 1, "critical": 0}.get(patient.get("acuity"), 0)
    return readiness, elapsed_days + acuity_priority


def _should_record_death(
    patient: dict,
    ward_name: str,
    occupancy_pressure: float,
    simulated_timestamp: datetime,
    seeded_random: random.Random,
) -> bool:
    if patient.get("status") != "active":
        return False
    elapsed_days = max(0.0, (simulated_timestamp - patient["admitted_at"]).total_seconds() / 86400)
    overstay = max(0.0, elapsed_days - patient["expected_stay_days"])
    acuity_multiplier = {"low": 0.2, "moderate": 0.8, "high": 1.3, "critical": 1.8}[patient["acuity"]]
    pressure_multiplier = 1.0 + max(0.0, occupancy_pressure - 0.85) * 2.5
    risk = WARD_DEATH_RISK[ward_name] * acuity_multiplier * pressure_multiplier
    risk += min(0.03, overstay * 0.004)
    return seeded_random.random() < risk


def _rebuild_wards_from_patients(wards: list[dict], patients: list[dict]) -> list[dict]:
    rebuilt = []
    for ward in wards:
        active_count = sum(
            1 for patient in patients
            if patient.get("ward") == ward["ward"] and patient.get("status") == "active"
        )
        rebuilt.append(refresh_ward_metrics({**ward, "occupied_beds": active_count}))
    return rebuilt
