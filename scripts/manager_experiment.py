from __future__ import annotations

import json
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import os

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from core import staff_ops
from core.realtime.constants import SIMULATION_START, UPDATE_INTERVAL_SECONDS
import core.realtime.ai_recommendations as ai_recommendations
from core.realtime.helpers import refresh_ward_metrics
from core.realtime.patient_flow import patient_outcome_summary
from core.realtime.snapshot import build_operational_snapshot
from core.realtime.staffing_sync import sync_staff_counts_to_wards
from core.realtime.state import build_realtime_state, sync_history_to_current_state
from core.realtime.simulation import simulate_realtime
import core.realtime.staffing_sync as staffing_sync


REPORT_DIR = ROOT / "reports"
REPORT_PATH = REPORT_DIR / "manager_agent_comparison.md"
TMP_DIR = ROOT / ".tmp_experiments"
_ISOLATED_STAFF_SEED: list[dict] | None = None


@dataclass
class DailyMetric:
    day_index: int
    hospital_time: str
    occupancy_pct: float
    high_pressure_wards: int
    staffing_gap: int
    equipment_gap: int
    manager_actions: int


@dataclass(frozen=True)
class ScenarioMode:
    key: str
    label: str
    manager_enabled: bool
    ai_enabled: bool


@contextmanager
def isolated_staff_workspace():
    temp_dir = TMP_DIR / "manager_experiment"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_staff_file = temp_dir / "staff.json"
    shutil.copy2(staff_ops.STAFF_FILE, temp_staff_file)
    global _ISOLATED_STAFF_SEED
    _ISOLATED_STAFF_SEED = json.loads(temp_staff_file.read_text(encoding="utf-8"))
    original_staff_file = staff_ops.STAFF_FILE
    original_sync_staff_file = staffing_sync.STAFF_FILE
    staff_ops.STAFF_FILE = temp_staff_file
    staffing_sync.STAFF_FILE = temp_staff_file
    try:
        yield
    finally:
        staff_ops.STAFF_FILE = original_staff_file
        staffing_sync.STAFF_FILE = original_sync_staff_file
        _ISOLATED_STAFF_SEED = None
        shutil.rmtree(temp_dir, ignore_errors=True)


def reset_isolated_staff_file() -> None:
    if _ISOLATED_STAFF_SEED is None:
        return
    staff_ops.STAFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    staff_ops.STAFF_FILE.write_text(json.dumps(_ISOLATED_STAFF_SEED, indent=2), encoding="utf-8")


def build_normal_state() -> dict:
    reset_isolated_staff_file()
    state = build_realtime_state(now=SIMULATION_START, mode="simulation")
    state["last_updated"] = SIMULATION_START
    state["simulation_now"] = SIMULATION_START
    state["manager_agent"] = {"enabled": True, "mode": "auto", "last_applied_ids": [], "last_summary": ""}
    state["manager_decision_log"] = []
    state["recommendation_cache"] = {}
    return sync_history_to_current_state(state)


def build_emergency_state() -> dict:
    state = build_normal_state()
    records = staff_ops.load_staff_records()
    _reduce_staff(records, "Emergency", "nurse", 5)
    _reduce_staff(records, "Emergency", "doctor", 1)
    _reduce_staff(records, "Surgery", "nurse", 3)
    _reduce_staff(records, "ICU", "nurse", 2)
    staff_ops.save_staff_records(records)

    pressured = []
    for ward in state["wards"]:
        updated = dict(ward)
        if ward["ward"] == "Emergency":
            updated.update({"occupied_beds": 31, "ventilators_available": 2, "monitors_available": 9})
        elif ward["ward"] == "Surgery":
            updated.update({"occupied_beds": 27, "ventilators_available": 4, "monitors_available": 8})
        elif ward["ward"] == "ICU":
            updated.update({"occupied_beds": 21, "ventilators_available": 6, "monitors_available": 12})
        elif ward["ward"] == "General":
            updated.update({"occupied_beds": 38})
        elif ward["ward"] == "Maternity":
            updated.update({"occupied_beds": 16})
        pressured.append(refresh_ward_metrics(updated))
    state["wards"] = sync_staff_counts_to_wards(pressured)
    return sync_history_to_current_state(state)


def _reduce_staff(records: list[dict], ward_name: str, role: str, amount: int) -> None:
    changed = 0
    for index, row in enumerate(records):
        if changed >= amount:
            break
        if row.get("ward") != ward_name:
            continue
        if str(row.get("role", "")).strip().lower() != role:
            continue
        if str(row.get("status", "")).strip().lower() not in staff_ops.ACTIVE_STATUSES:
            continue
        updated = dict(row)
        updated["status"] = "Off duty"
        updated["last_updated"] = SIMULATION_START.strftime("%Y-%m-%d %H:%M:%S")
        records[index] = updated
        changed += 1


def run_scenario(name: str, state_factory, days: int, mode: ScenarioMode) -> dict:
    state = state_factory()
    metrics = []
    manager_sources = {"ai": 0, "rules": 0}
    last_log_count = 0
    with _ai_mode(enabled=mode.ai_enabled):
        for day_index in range(days + 1):
            if day_index > 0:
                next_now = state["last_updated"] + timedelta(seconds=UPDATE_INTERVAL_SECONDS)
                state = simulate_realtime(state, now=next_now, force_step=True)
                state["manager_agent"] = {
                    **state.get("manager_agent", {}),
                    "enabled": mode.manager_enabled,
                    "mode": "auto" if mode.manager_enabled else "manual",
                    "last_cycle_key": None,
                    "last_applied_ids": [],
                }
                state["recommendation_cache"] = {}
            if mode.manager_enabled:
                snapshot, _, _ = build_operational_snapshot(state)
            else:
                snapshot, _, _ = build_operational_snapshot(_manager_disabled_copy(state))
                state = _restore_non_agent_state(state, snapshot)
            log = state.get("manager_decision_log", [])
            for entry in log[last_log_count:]:
                manager_sources[entry.get("source", "rules")] = manager_sources.get(entry.get("source", "rules"), 0) + 1
            last_log_count = len(log)
            metrics.append(
                DailyMetric(
                    day_index=day_index,
                    hospital_time=state["simulation_now"].strftime("%d %b %Y %H:%M"),
                    occupancy_pct=_system_occupancy_pct(state),
                    high_pressure_wards=sum(1 for ward in state["wards"] if ward["occupancy_rate"] >= 0.9),
                    staffing_gap=_staffing_gap(state),
                    equipment_gap=_equipment_gap(state),
                    manager_actions=len(state.get("manager_agent", {}).get("last_applied_ids", [])),
                )
            )
    return {
        "name": name,
        "mode": mode.key,
        "metrics": metrics,
        "sources": manager_sources,
        "state": state,
        "patient_outcomes": patient_outcome_summary(state),
        "manager_log": list(state.get("manager_decision_log", [])),
        "manager_interviews": list(state.get("manager_interviews", [])),
    }


@contextmanager
def _ai_mode(enabled: bool):
    original_flag = ai_recommendations.OPENAI_AVAILABLE
    if enabled:
        ai_recommendations.OPENAI_AVAILABLE = original_flag and bool(os.getenv("OPENAI_API_KEY"))
    else:
        ai_recommendations.OPENAI_AVAILABLE = False
    try:
        yield
    finally:
        ai_recommendations.OPENAI_AVAILABLE = original_flag


def _manager_disabled_copy(state: dict) -> dict:
    copied = {
        **state,
        "manager_agent": {
            **state.get("manager_agent", {}),
            "enabled": False,
            "mode": "manual",
            "last_cycle_key": None,
            "last_applied_ids": [],
        },
        "recommendation_cache": {},
        "manager_decision_log": list(state.get("manager_decision_log", [])),
    }
    return copied


def _restore_non_agent_state(state: dict, snapshot) -> dict:
    return {
        **state,
        "manager_agent": {
            **state.get("manager_agent", {}),
            "enabled": False,
            "mode": "manual",
            "last_applied_ids": [],
            "last_summary": "Manager agent disabled for baseline comparison.",
        },
        "recommendation_cache": {},
        "manager_decision_log": list(state.get("manager_decision_log", [])),
        "recommendation_log": dict(state.get("recommendation_log", {})),
    }


def _system_occupancy_pct(state: dict) -> float:
    occupied = sum(ward["occupied_beds"] for ward in state["wards"])
    capacity = sum(ward["capacity"] for ward in state["wards"])
    return round((occupied / capacity) * 100, 1) if capacity else 0.0


def _staffing_gap(state: dict) -> int:
    gap = 0
    for ward in state["wards"]:
        gap += max(0, ward["required_nurses"] - ward["nurses_available"])
        gap += max(0, ward["required_doctors"] - ward["doctors_available"])
    return gap


def _equipment_gap(state: dict) -> int:
    gap = 0
    for ward in state["wards"]:
        gap += max(0, ward["required_ventilators"] - ward["ventilators_available"])
        gap += max(0, ward["required_monitors"] - ward["monitors_available"])
    return gap


def summarize_result(result: dict) -> dict:
    metrics = result["metrics"]
    start = metrics[0]
    end = metrics[-1]
    peak_high_pressure = max(item.high_pressure_wards for item in metrics)
    avg_occupancy = round(sum(item.occupancy_pct for item in metrics) / len(metrics), 1)
    total_actions = sum(item.manager_actions for item in metrics)
    recovery_day = next(
        (
            item.day_index
            for item in metrics
            if item.high_pressure_wards == 0 and item.staffing_gap == 0 and item.equipment_gap == 0
        ),
        None,
    )
    return {
        "start_occupancy": start.occupancy_pct,
        "end_occupancy": end.occupancy_pct,
        "avg_occupancy": avg_occupancy,
        "start_staff_gap": start.staffing_gap,
        "end_staff_gap": end.staffing_gap,
        "start_equipment_gap": start.equipment_gap,
        "end_equipment_gap": end.equipment_gap,
        "peak_high_pressure": peak_high_pressure,
        "total_actions": total_actions,
        "recovery_day": recovery_day,
    }


def _mode_result(results: list[dict], mode: str) -> dict:
    return next(result for result in results if result["mode"] == mode)


def build_report(
    normal_results: list[dict],
    emergency_results: list[dict],
    normal_days: int,
    emergency_days: int,
) -> str:
    normal_summaries = {result["mode"]: summarize_result(result) for result in normal_results}
    emergency_summaries = {result["mode"]: summarize_result(result) for result in emergency_results}
    generated_at = datetime.now().strftime("%d %b %Y %H:%M")
    lines = [
        "# Manager Agent Comparison Report",
        "",
        f"Generated: {generated_at}",
        "",
        "## Experiment setup",
        "",
        "- Time basis: hospital time (`simulation_now`), not wall-clock time.",
        "- Comparison groups: baseline operations, rules-based manager operations, and AI-backed manager operations.",
        f"- Scenarios: steady-state operations over {normal_days} hospital days and an emergency surge over {emergency_days} hospital days.",
        "- Isolation: staffing changes were run against a temporary copy of `staff.json` so the live demo data was not modified.",
        "",
        "## Summary comparison",
        "",
        "| Scenario | Mode | Avg Occupancy % | End Staffing Gap | End Equipment Gap | Peak High-Pressure Wards | Recovery Day | Manager Actions |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
        _summary_row("Normal operations", "Baseline", normal_summaries["baseline"]),
        _summary_row("Normal operations", "Rules manager", normal_summaries["rules"]),
        _summary_row("Normal operations", "AI manager", normal_summaries["ai"]),
        _summary_row("Emergency surge", "Baseline", emergency_summaries["baseline"]),
        _summary_row("Emergency surge", "Rules manager", emergency_summaries["rules"]),
        _summary_row("Emergency surge", "AI manager", emergency_summaries["ai"]),
        "",
        "## Impact highlights",
        "",
        _impact_line("Normal operations, rules vs baseline", normal_summaries["baseline"], normal_summaries["rules"]),
        _impact_line("Normal operations, AI vs baseline", normal_summaries["baseline"], normal_summaries["ai"]),
        _impact_line("Emergency surge, rules vs baseline", emergency_summaries["baseline"], emergency_summaries["rules"]),
        _impact_line("Emergency surge, AI vs baseline", emergency_summaries["baseline"], emergency_summaries["ai"]),
        _impact_line("Emergency surge, AI vs rules", emergency_summaries["rules"], emergency_summaries["ai"]),
        "",
        "## Daily traces",
        "",
        "### Normal operations",
        "",
        _trace_table(normal_results),
        "",
        "### Emergency surge",
        "",
        _trace_table(emergency_results),
        "",
        "## Manager behavior notes",
        "",
        f"- Normal scenario sources, rules manager: {json.dumps(_sources_for_mode(normal_results, 'rules'))}",
        f"- Normal scenario sources, AI manager: {json.dumps(_sources_for_mode(normal_results, 'ai'))}",
        f"- Emergency scenario sources, rules manager: {json.dumps(_sources_for_mode(emergency_results, 'rules'))}",
        f"- Emergency scenario sources, AI manager: {json.dumps(_sources_for_mode(emergency_results, 'ai'))}",
        "- If AI counts are low or zero in the AI manager rows, the manager fell back to rule-backed operational actions for reliability.",
        "- The manager was evaluated on hospital-time steps, so each cycle reflects the simulated next operational day.",
        "",
        "## Patient outcomes",
        "",
        _patient_outcome_lines(normal_results, emergency_results),
        "",
        "## Detailed decision trace",
        "",
        "### Emergency surge, AI manager decisions",
        "",
        _decision_trace_markdown(_mode_result(emergency_results, "ai")["manager_log"]),
        "",
        "### Emergency surge, AI manager interview questionnaire",
        "",
        _interview_markdown(_mode_result(emergency_results, "ai")["manager_interviews"]),
        "",
        "## Interpretation",
        "",
        _interpretation(normal_summaries, emergency_summaries),
        "",
    ]
    return "\n".join(lines)


def _summary_row(label: str, mode: str, summary: dict) -> str:
    recovery = f"Day {summary['recovery_day']}" if summary["recovery_day"] is not None else "Not reached"
    return (
        f"| {label} | {mode} | {summary['avg_occupancy']:.1f} | {summary['end_staff_gap']} | "
        f"{summary['end_equipment_gap']} | {summary['peak_high_pressure']} | {recovery} | "
        f"{summary['total_actions']} |"
    )


def _impact_line(label: str, baseline: dict, agentic: dict) -> str:
    occupancy_delta = round(agentic["avg_occupancy"] - baseline["avg_occupancy"], 1)
    staff_delta = agentic["end_staff_gap"] - baseline["end_staff_gap"]
    equipment_delta = agentic["end_equipment_gap"] - baseline["end_equipment_gap"]
    baseline_recovery = baseline["recovery_day"]
    agentic_recovery = agentic["recovery_day"]
    if baseline_recovery is None and agentic_recovery is not None:
        recovery_note = f"Agent recovered by day {agentic_recovery}, while baseline did not fully recover."
    elif baseline_recovery is not None and agentic_recovery is not None:
        recovery_note = f"Recovery changed from day {baseline_recovery} to day {agentic_recovery}."
    else:
        recovery_note = "Neither run hit the full recovery threshold."
    return (
        f"- **{label}:** occupancy delta {occupancy_delta:+.1f} pts, staffing gap delta {staff_delta:+d}, "
        f"equipment gap delta {equipment_delta:+d}. {recovery_note}"
    )


def _trace_table(results: list[dict]) -> str:
    metrics_by_mode = {result["mode"]: result["metrics"] for result in results}
    lines = [
        "| Day | Hospital Time | Baseline Occ % | Rules Occ % | AI Occ % | Baseline Staff Gap | Rules Staff Gap | AI Staff Gap | Baseline Equip Gap | Rules Equip Gap | AI Equip Gap | Rules Actions | AI Actions |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for baseline, rules, ai in zip(metrics_by_mode["baseline"], metrics_by_mode["rules"], metrics_by_mode["ai"]):
        lines.append(
            f"| {baseline.day_index} | {baseline.hospital_time} | {baseline.occupancy_pct:.1f} | "
            f"{rules.occupancy_pct:.1f} | {ai.occupancy_pct:.1f} | {baseline.staffing_gap} | "
            f"{rules.staffing_gap} | {ai.staffing_gap} | {baseline.equipment_gap} | "
            f"{rules.equipment_gap} | {ai.equipment_gap} | {rules.manager_actions} | {ai.manager_actions} |"
        )
    return "\n".join(lines)


def _sources_for_mode(results: list[dict], mode: str) -> dict:
    return next(result["sources"] for result in results if result["mode"] == mode)


def _patient_outcome_lines(normal_results: list[dict], emergency_results: list[dict]) -> str:
    rows = [
        "| Scenario | Mode | Active Patients | Discharged Patients | Deceased Patients |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for scenario_label, results in (("Normal operations", normal_results), ("Emergency surge", emergency_results)):
        for mode_label, mode_key in (("Baseline", "baseline"), ("Rules manager", "rules"), ("AI manager", "ai")):
            outcomes = _mode_result(results, mode_key)["patient_outcomes"]
            rows.append(
                f"| {scenario_label} | {mode_label} | {outcomes.get('active', 0)} | "
                f"{outcomes.get('discharged', 0)} | {outcomes.get('deceased', 0)} |"
            )
    return "\n".join(rows)


def _decision_trace_markdown(entries: list[dict]) -> str:
    if not entries:
        return "_No manager trace entries recorded._"
    lines = []
    for entry in entries:
        lines.append(
            f"- `{entry.get('timestamp')}` | {entry.get('event', 'event').title()} | "
            f"{entry.get('ward', 'System')} | `{entry.get('action_type', 'maintain_monitoring')}` | "
            f"source={entry.get('source', 'rules')} | reason={entry.get('reason', '') or 'n/a'} | "
            f"message={entry.get('message', '') or 'n/a'} | "
            f"patients_before={entry.get('patient_outcomes_before', {})} | patients_after={entry.get('patient_outcomes_after', {})}"
        )
    return "\n".join(lines)


def _interview_markdown(entries: list[dict]) -> str:
    if not entries:
        return "_No interview entries recorded._"
    blocks = []
    for entry in entries:
        blocks.append(
            f"#### {entry.get('timestamp')} | {entry.get('ward')} | {entry.get('recommendation_id')}\n"
        )
        for qa in entry.get("qa", []):
            blocks.append(f"- **Q:** {qa.get('question', '')}")
            blocks.append(f"- **A:** {qa.get('answer', '')}")
        blocks.append("")
    return "\n".join(blocks)


def _interpretation(normal_summaries: dict[str, dict], emergency_summaries: dict[str, dict]) -> str:
    lines = []
    normal_rules = normal_summaries["rules"]
    normal_ai = normal_summaries["ai"]
    normal_base = normal_summaries["baseline"]
    emergency_rules = emergency_summaries["rules"]
    emergency_ai = emergency_summaries["ai"]
    emergency_base = emergency_summaries["baseline"]
    if normal_ai["end_staff_gap"] <= normal_rules["end_staff_gap"] and normal_ai["avg_occupancy"] <= normal_rules["avg_occupancy"]:
        lines.append(
            "In steady-state operations, the AI manager matched or improved on the rules manager without increasing background pressure."
        )
    elif normal_rules["end_staff_gap"] <= normal_base["end_staff_gap"]:
        lines.append(
            "In steady-state operations, the rules manager reduced operational deficits relative to baseline."
        )
    else:
        lines.append(
            "In steady-state operations, both manager variants were broadly comparable and mainly acted as stabilizers."
        )
    if emergency_ai["recovery_day"] is not None and (
        emergency_base["recovery_day"] is None
        or emergency_ai["recovery_day"] <= emergency_base["recovery_day"]
    ):
        lines.append(
            "In the emergency surge, the AI manager improved recovery behavior by acting early on staffing, discharge, and overflow steps."
        )
    elif emergency_ai["avg_occupancy"] < emergency_rules["avg_occupancy"] or emergency_ai["end_staff_gap"] < emergency_rules["end_staff_gap"]:
        lines.append(
            "In the emergency surge, the AI manager improved pressure or deficit metrics versus the rules manager, but not enough to fully recover."
        )
    else:
        lines.append(
            "In the emergency surge, the rules manager provided most of the measurable gain and the AI manager remained close to that baseline."
        )
    lines.append(
        "Overall, the manager variants are best understood as always-on operational coordinators using hospital-time checkpoints rather than real-time wall-clock reaction."
    )
    return " ".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run manager-agent comparison experiments.")
    parser.add_argument("--normal-days", type=int, default=5, help="Hospital days for the normal-operations scenario.")
    parser.add_argument("--emergency-days", type=int, default=6, help="Hospital days for the emergency scenario.")
    parser.add_argument("--require-ai", action="store_true", help="Fail fast if no API key is available for the AI manager runs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()
    if args.require_ai and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not available for AI experiment mode.")
    modes = [
        ScenarioMode("baseline", "Baseline", manager_enabled=False, ai_enabled=False),
        ScenarioMode("rules", "Rules manager", manager_enabled=True, ai_enabled=False),
        ScenarioMode("ai", "AI manager", manager_enabled=True, ai_enabled=True),
    ]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with isolated_staff_workspace():
        normal_results = [run_scenario("normal", build_normal_state, days=args.normal_days, mode=mode) for mode in modes]
        emergency_results = [run_scenario("emergency", build_emergency_state, days=args.emergency_days, mode=mode) for mode in modes]
    report = build_report(
        normal_results,
        emergency_results,
        args.normal_days,
        args.emergency_days,
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
