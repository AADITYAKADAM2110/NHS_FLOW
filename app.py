from contextlib import redirect_stdout
from io import StringIO
import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from openai import OpenAI

from core.agents.saved_agents import communication_officer, manager
from core.auth import authenticate_user, has_permission, load_users, role_label
from core.realtime_ops import (
    FORECAST_MODEL_NAME,
    UPDATE_INTERVAL_SECONDS,
    advance_hospital_day,
    apply_recommendation_action,
    apply_emergency_capacity,
    apply_emergency_staffing,
    apply_full_emergency_stabilization,
    build_hospital_map,
    build_operational_snapshot,
    build_realtime_state,
    build_system_totals,
    load_realtime_state,
    save_realtime_state,
    set_operation_mode,
    simulate_realtime,
    update_ward_state,
)
from core.realtime.staffing_sync import sync_staff_counts_to_wards
from core.staff_ops import assign_staff_member, load_staff_records, summarize_staff_by_ward
from core.tools.place_order import place_order
from core.ui import render_app_shell, render_metric_band, render_table_card

load_dotenv()


def configure_openai_key():
    if os.getenv("OPENAI_API_KEY"):
        return
    try:
        secret_value = st.secrets.get("OPENAI_API_KEY")
    except Exception:
        secret_value = None
    if secret_value:
        os.environ["OPENAI_API_KEY"] = secret_value


configure_openai_key()


def build_initial_state():
    return {
        "shortages": [],
        "stock_details": {},
        "options": [],
        "supplier_options": {},
        "pending_orders": [],
        "receipt": [],
        "total_spent": 0.0,
        "human_approval": False,
        "current_agent": manager,
        "order_confirmed": False,
        "email_draft": "",
        "email_sent": False,
    }


def init_session():
    if "workflow_state" not in st.session_state:
        st.session_state.workflow_state = build_initial_state()
    if "agent_trace" not in st.session_state:
        st.session_state.agent_trace = []
    if "last_report" not in st.session_state:
        st.session_state.last_report = ""
    if "realtime_state" not in st.session_state:
        st.session_state.realtime_state = load_realtime_state()
    if "auto_refresh" not in st.session_state:
        st.session_state.auto_refresh = False
    if "operation_message" not in st.session_state:
        st.session_state.operation_message = ""
    if "skip_realtime_refresh_once" not in st.session_state:
        st.session_state.skip_realtime_refresh_once = False
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None
    if "login_error" not in st.session_state:
        st.session_state.login_error = ""
    restore_auth_from_query()


def get_query_params() -> dict:
    if hasattr(st, "query_params"):
        try:
            params = dict(st.query_params)
            normalized = {}
            for key, value in params.items():
                normalized[key] = value if isinstance(value, list) else [value]
            return normalized
        except Exception:
            pass
    if hasattr(st, "experimental_get_query_params"):
        return st.experimental_get_query_params()
    return {}


def set_query_params(**params):
    if hasattr(st, "query_params"):
        try:
            st.query_params.clear()
            for key, value in params.items():
                if value is None or value == "":
                    continue
                st.query_params[key] = value
            return
        except Exception:
            pass
    if hasattr(st, "experimental_set_query_params"):
        st.experimental_set_query_params(**params)


def restore_auth_from_query():
    if st.session_state.get("auth_user"):
        return
    query_params = get_query_params()
    user_ids = query_params.get("user")
    if not user_ids:
        return
    remembered_id = user_ids[0]
    user = next((row for row in load_users() if row.get("user_id") == remembered_id), None)
    if user:
        st.session_state.auth_user = user


def refresh_realtime_state():
    if st.session_state.skip_realtime_refresh_once:
        st.session_state.skip_realtime_refresh_once = False
        return
    if st.session_state.realtime_state.get("operation_mode") == "real":
        return
    st.session_state.realtime_state = simulate_realtime(
        st.session_state.realtime_state,
        force_step=True,
    )
    save_realtime_state(st.session_state.realtime_state)


def reset_session():
    st.session_state.workflow_state = build_initial_state()
    st.session_state.agent_trace = []
    st.session_state.last_report = ""


def logout():
    st.session_state.auth_user = None
    st.session_state.login_error = ""
    reset_session()
    st.session_state.operation_message = ""
    set_query_params()
    rerun_app()


def reset_operations():
    mode = st.session_state.realtime_state.get("operation_mode", "simulation")
    st.session_state.realtime_state = build_realtime_state(mode=mode)
    save_realtime_state(st.session_state.realtime_state)
    st.session_state.operation_message = ""
    st.session_state.skip_realtime_refresh_once = True


def rerun_app():
    if hasattr(st, "rerun"):
        st.rerun()
        return
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()


def capture_run(callback):
    output = StringIO()
    with redirect_stdout(output):
        result = callback()
    logs = output.getvalue().strip()
    if logs:
        st.session_state.agent_trace.append(logs)
    return result


def run_audit():
    state = st.session_state.workflow_state
    state.update(build_initial_state())
    result = capture_run(
        lambda: state["current_agent"].run(
            query="Are we in stock? If not, find suppliers.",
            state=state,
            openai=OpenAI(),
        )
    )
    st.session_state.last_report = result or ""


def stage_orders():
    state = st.session_state.workflow_state
    state["human_approval"] = True
    order_query = (
        f"AUTHORIZATION GRANTED. The human has approved the purchase request. "
        f"IMMEDIATELY use the 'place_order' tool for these items: {state['shortages']}. "
        f"REQUIREMENTS: "
        f"1. Select the Cheapest NHS-Approved Supplier found in history. "
        f"2. Quantity = (Threshold - Current Stock) + 10 buffer. "
        f"3. DO NOT ask for permission again. EXECUTE the tool now."
    )
    result = capture_run(
        lambda: state["current_agent"].run(
            query=order_query,
            state=state,
            openai=OpenAI(),
        )
    )
    st.session_state.last_report = result or ""


def build_email_context(state):
    email_schema = {
        "subject": "Procurement Order Confirmation for Medical Supplies",
        "To": "{contact.email}",
        "body": (
            "Dear {supplier_name},\n\n"
            "We are writing to confirm our recent procurement order for medical supplies. "
            "Below are the details of the order:\n\n{order_details}\n\n"
            "Please confirm receipt of this order and provide an estimated delivery date.\n\n"
            "Thank you for your prompt attention to this matter.\n\n"
            "Best regards,\nNHS Procurement Team"
        ),
        "contact_info": {
            "team_email": "procurement@nhs.uk",
            "team_phone": "+44 20 7946 0000",
        },
    }

    email_lines = []
    supplier_contacts = []
    for order in state["pending_orders"]:
        email_lines.append(
            f"- {order['item_name']}, Quantity: {order['quantity']}, "
            f"Cost per unit: GBP {order['cost_per_unit']:.2f}, "
            f"Total cost: GBP {order['total_cost']:.2f}, "
            f"Location: {order['location']}, Supplier: {order['supplier']}, "
            f"Delivery: {order['delivery']}, Supplier Email: {order['contact_email']}, "
            f"Supplier Phone: {order['contact_phone']}"
        )
        supplier_contacts.append(
            {
                "supplier": order["supplier"],
                "email": order["contact_email"],
                "phone": order["contact_phone"],
            }
        )

    return (
        f"Draft a supplier confirmation email using this template: {email_schema}. "
        f"Order details:\n" + "\n".join(email_lines) + "\n"
        f"Total Value: GBP {state['total_spent']:.2f}. "
        f"Supplier contact details: {supplier_contacts}. "
        f"Include the supplier name and their contact info clearly in the email."
    )


def draft_email():
    state = st.session_state.workflow_state
    email_context = build_email_context(state)
    draft = capture_run(
        lambda: communication_officer.run(
            email_context,
            state,
            OpenAI(),
        )
    )
    state["email_draft"] = draft or ""


def send_orders():
    state = st.session_state.workflow_state

    def commit_orders():
        for order in state["pending_orders"]:
            print(
                place_order(
                    order["item_name"],
                    order["quantity"],
                    order["supplier"],
                    order["cost_per_unit"],
                )
            )

    capture_run(commit_orders)
    state["email_sent"] = True


def receipt_dataframe(receipt):
    if not receipt:
        return pd.DataFrame(columns=["Item", "Supplier", "Qty", "Unit Cost", "Total"])
    return pd.DataFrame(
        receipt,
        columns=["Item", "Supplier", "Qty", "Unit Cost", "Total"],
    )


def render_header():
    realtime_state = st.session_state.get("realtime_state", {})
    chips = [
        ("Mode", str(realtime_state.get("operation_mode", "simulation")).title()),
        (
            "Hospital Time",
            realtime_state.get("simulation_now", realtime_state.get("last_updated")).strftime("%d %b %Y %H:%M")
            if realtime_state
            else "",
        ),
    ]
    user = st.session_state.get("auth_user")
    if user:
        chips.append(
            (
                "User",
                f"{user.get('name', user.get('user_id', 'User'))} · {role_label(user.get('role', ''))}",
            )
        )
    render_app_shell(
        "NHS-FLOW Command Center",
        "Live bed pressure, staffing readiness, tomorrow forecasting, and procurement workflow in one responsive control surface.",
        chips=chips,
    )


def render_auto_refresh():
    mode = st.session_state.realtime_state.get("operation_mode", "simulation")
    col1, col2 = st.columns([1, 1])
    with col1:
        button_label = "Advance Hospital Day" if mode == "real" else "Advance Simulation (1 day)"
        if st.button(button_label, use_container_width=True):
            if mode == "real":
                st.session_state.realtime_state, st.session_state.operation_message = advance_hospital_day(
                    st.session_state.realtime_state
                )
                save_realtime_state(st.session_state.realtime_state)
                st.session_state.skip_realtime_refresh_once = True
            else:
                refresh_realtime_state()
            rerun_app()
    with col2:
        disabled = mode == "real"
        if disabled:
            st.session_state.auto_refresh = False
        st.checkbox(
            "Auto-advance every 60 seconds",
            key="auto_refresh_checkbox",
            value=st.session_state.auto_refresh,
            disabled=disabled,
        ) 
        if st.session_state.auto_refresh_checkbox != st.session_state.auto_refresh:
            st.session_state.auto_refresh = st.session_state.auto_refresh_checkbox
            rerun_app()

    if mode == "real":
        st.caption("Real mode is active. Automatic simulation is paused until you manually advance the hospital day.")
    elif st.session_state.auto_refresh:
        components.html(
            f"""
            <script>
                setTimeout(function() {{
                    var targetUrl =
                        window.parent.location.origin +
                        window.parent.location.pathname +
                        window.parent.location.search;
                    window.parent.location.href = targetUrl;
                }}, {UPDATE_INTERVAL_SECONDS * 1000});
            </script>
            """,
            height=0,
        )
        st.caption("Auto-refresh is enabled. The page will reload on the same signed-in URL each cycle.")


def render_operations_summary(snapshot):
    totals = build_system_totals(snapshot)
    render_metric_band(
        "Live Capacity Monitor",
        [
            {"label": "Beds Occupied Now", "value": totals["occupied"], "meta": "Current in-hospital occupancy"},
            {"label": "Beds Available", "value": totals["available"], "meta": "Immediate remaining capacity"},
            {
                "label": "Current Occupancy",
                "value": f"{totals['occupancy_pct']}%",
                "meta": "All wards combined",
                "tone": "warn" if totals["occupancy_pct"] >= 85 else "",
            },
            {
                "label": "Predicted Peak Tomorrow",
                "value": totals["predicted_peak"],
                "meta": "Forecasted system peak",
                "tone": "danger" if totals["predicted_peak"] >= totals["capacity"] else "",
            },
        ],
        subtitle="A fast systems view of current pressure, remaining space, and forecasted demand.",
    )


def render_basic_operations_tables(snapshot):
    equipment_frame = snapshot.copy()
    equipment_frame["Available Beds"] = equipment_frame["Capacity"] - equipment_frame["Occupied Beds"]
    equipment_frame = equipment_frame[
        [
            "Ward",
            "Occupied Beds",
            "Capacity",
            "Available Beds",
            "Ventilators Available",
            "Monitors Available",
        ]
    ]
    render_table_card(
        "Beds and Equipment",
        equipment_frame,
        highlight_rules=[
            lambda row, column: column == "Available Beds" and int(row[column]) <= 2,
        ],
    )


def render_login():
    components.html(
        """
        <html>
        <head>
            <style>
                body {
                    margin: 0;
                    padding: 0;
                    background: transparent;
                    font-family: "Segoe UI", sans-serif;
                }
                .login-hero {
                    border-radius: 24px;
                    padding: 24px 26px;
                    background:
                        radial-gradient(circle at top right, rgba(255,255,255,0.18), transparent 28%),
                        linear-gradient(135deg, #113d37, #0f7668 58%, #c96b18);
                    color: #f4fff9;
                    box-shadow: 0 24px 48px rgba(10, 53, 46, 0.18);
                }
                .login-hero h2 {
                    margin: 0 0 8px;
                    font-size: 30px;
                }
                .login-hero p {
                    margin: 0;
                    opacity: 0.92;
                    line-height: 1.5;
                    max-width: 760px;
                    font-size: 15px;
                }
            </style>
        </head>
        <body>
            <div class="login-hero">
                <h2>Secure Staff Access</h2>
                <p>Sign in with your role account to open the live operations dashboard, staffing controls, and procurement workspace.</p>
            </div>
        </body>
        </html>
        """,
        height=150,
        scrolling=False,
    )

    left, right = st.columns([1.1, 0.9], gap="large")
    with left:
        st.subheader("Sign In")
        st.caption("Use your staff ID and password to continue.")
        with st.form("login-form"):
            user_id = st.text_input("Staff ID", placeholder="e.g. MGR-1001")
            password = st.text_input("Password", type="password", placeholder="Enter password")
            submitted = st.form_submit_button("Log In", use_container_width=True)

    if submitted:
        user = authenticate_user(user_id, password)
        if user:
            st.session_state.auth_user = user
            st.session_state.login_error = ""
            set_query_params(user=user.get("user_id", ""))
            rerun_app()
        else:
            st.session_state.login_error = "Invalid staff ID or password."

    if st.session_state.login_error:
        st.error(st.session_state.login_error)

    with right:
        st.subheader("Demo Accounts")
        st.caption("Quick-access prototype accounts")
        card_cols = st.columns(2, gap="small")
        accounts = [
            ("Manager", "MGR-1001", "manager123"),
            ("Nurse", "NUR-1001", "nurse123"),
            ("Staff", "STF-1001", "staff123"),
            ("Procurement", "PRO-1001", "procure123"),
        ]
        for index, (role, user_id_value, password_value) in enumerate(accounts):
            with card_cols[index % 2]:
                st.info(f"**{role}**\n\nID: `{user_id_value}`\n\nPassword: `{password_value}`")


def render_user_banner():
    user = st.session_state.auth_user
    if not user:
        return
    left, right = st.columns([4, 1])
    with left:
        st.caption(
            f"Signed in as {user.get('name', user.get('user_id', 'User'))} | "
            f"{role_label(user.get('role', ''))} | ID {user.get('user_id', '')}"
        )
    with right:
        if st.button("Log Out", use_container_width=True):
            logout()


def show_access_denied(message: str):
    st.info(message)


def render_operations_controls():
    current_mode = st.session_state.realtime_state.get("operation_mode", "simulation")
    left, middle, right = st.columns([1.2, 1, 2.8])
    with left:
        selected_mode = st.radio(
            "Operations mode",
            options=["simulation", "real"],
            index=0 if current_mode == "simulation" else 1,
            horizontal=True,
        )
        if selected_mode != current_mode:
            st.session_state.realtime_state, st.session_state.operation_message = set_operation_mode(
                st.session_state.realtime_state,
                selected_mode,
            )
            save_realtime_state(st.session_state.realtime_state)
            st.session_state.skip_realtime_refresh_once = True
            rerun_app()
    with middle:
        if st.button("Reset Operations Data", use_container_width=True):
            reset_operations()
            rerun_app()
    with right:
        if current_mode == "real":
            st.caption("Real mode lets staff manually update beds, admissions, discharges, and staffing. No automatic simulation runs.")
        else:
            st.caption(f"Simulation refreshes every {UPDATE_INTERVAL_SECONDS} seconds when auto refresh is enabled.")


def apply_and_persist_operations_action(action):
    updated_state, message = action(st.session_state.realtime_state)
    st.session_state.realtime_state = updated_state
    save_realtime_state(st.session_state.realtime_state)
    st.session_state.operation_message = message
    st.session_state.skip_realtime_refresh_once = True
    rerun_app()


def render_emergency_controls():
    st.subheader("Emergency Controls")
    st.caption("Use these bulk interventions when multiple wards are under pressure and you need to normalize the system quickly.")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Deploy Extra Staff", use_container_width=True):
            apply_and_persist_operations_action(apply_emergency_staffing)
    with col2:
        if st.button("Open Extra Beds", use_container_width=True):
            apply_and_persist_operations_action(apply_emergency_capacity)
    with col3:
        if st.button("Full Stabilization", use_container_width=True):
            apply_and_persist_operations_action(apply_full_emergency_stabilization)


def render_real_mode_editor(advanced_access: bool = True):
    if advanced_access and st.session_state.realtime_state.get("operation_mode") != "real":
        return
    st.subheader("Ward Updates")
    if advanced_access:
        st.caption("Real mode editing is active for beds and equipment. Staffing now comes from the Staff Assignment dataset.")
    else:
        st.caption("Update ward beds and equipment directly from the live hospital view.")
    wards = st.session_state.realtime_state["wards"]
    ward_names = [ward["ward"] for ward in wards]
    selected_ward = st.selectbox("Select ward to update", ward_names, key="real_mode_ward")
    ward = next(ward for ward in wards if ward["ward"] == selected_ward)
    with st.form("real-mode-editor"):
        col1, col2, col3 = st.columns(3)
        with col1:
            admissions = st.number_input("New patients", min_value=0, value=0, step=1)
            discharges = st.number_input("Discharges", min_value=0, value=0, step=1)
            capacity = st.number_input("Total beds", min_value=1, value=int(ward["capacity"]), step=1)
        with col2:
            occupied_beds = st.number_input("Occupied beds", min_value=0, value=int(ward["occupied_beds"]), step=1)
            st.metric("Nurses available", int(ward["nurses_available"]))
            st.metric("Doctors available", int(ward["doctors_available"]))
        with col3:
            ventilators_available = st.number_input("Ventilators available", min_value=0, value=int(ward["ventilators_available"]), step=1)
            monitors_available = st.number_input("Monitors available", min_value=0, value=int(ward["monitors_available"]), step=1)
        submitted = st.form_submit_button("Save ward updates", use_container_width=True)
    if submitted:
        updates = {
            "admissions": admissions,
            "discharges": discharges,
            "capacity": capacity,
            "occupied_beds": occupied_beds,
            "ventilators_available": ventilators_available,
            "monitors_available": monitors_available,
        }
        st.session_state.realtime_state, st.session_state.operation_message = update_ward_state(
            st.session_state.realtime_state,
            selected_ward,
            updates,
        )
        save_realtime_state(st.session_state.realtime_state)
        st.session_state.skip_realtime_refresh_once = True
        rerun_app()


def render_operations_alerts(alerts, snapshot, simulation_now):
    st.subheader("Operational Recommendations")
    manager_state = st.session_state.realtime_state.get("manager_agent", {})
    auto_applied_ids = set(manager_state.get("last_applied_ids", []))
    if manager_state:
        mode_label = "Auto" if manager_state.get("mode") == "auto" else "Manual"
        st.caption(
            f"Manager agent: {mode_label} | "
            f"{manager_state.get('last_summary', 'Monitoring staff and equipment flow.')}"
        )
    
    # Apply All button
    if st.button("Apply All Recommendations", use_container_width=True):
        current_state = st.session_state.realtime_state
        messages = []
        for alert in alerts[:8]:
            if alert.get("action_type") != "maintain_monitoring":
                updated_state, message = apply_recommendation_action(current_state, alert)
                current_state = updated_state
                messages.append(message)
        st.session_state.realtime_state = current_state
        save_realtime_state(st.session_state.realtime_state)
        st.session_state.operation_message = "Applied all recommendations: " + "; ".join(messages)
        st.session_state.skip_realtime_refresh_once = True
        rerun_app()
    
    for index, alert in enumerate(alerts[:8], start=1):
        alert_id = alert["id"]
        source = "AI" if alert.get("source") == "ai" else "Rules"
        if alert_id in auto_applied_ids:
            source += " | Auto-applied"
        display_text = alert['text']
        if alert.get("source") == "ai" and alert.get("reason"):
            display_text += f"<br><strong>AI Explanation:</strong> {alert['reason']}"
        st.markdown(f"<div class='alert-card'>{display_text}<br><small>{source} recommendation</small></div>", unsafe_allow_html=True)
        button_col1 = st.columns([1])[0]
        with button_col1:
            disabled = alert.get("action_type") == "maintain_monitoring"
            if st.button("Apply Recommendation", key=f"apply-{index}-{alert_id}", disabled=disabled):
                updated_state, message = apply_recommendation_action(st.session_state.realtime_state, alert)
                st.session_state.realtime_state = updated_state
                save_realtime_state(st.session_state.realtime_state)
                st.session_state.operation_message = message
                st.session_state.skip_realtime_refresh_once = True
                rerun_app()

    manager_log = list(st.session_state.realtime_state.get("manager_decision_log", []))
    if manager_log:
        with st.expander("Manager Decision Log", expanded=False):
            for entry in reversed(manager_log[-12:]):
                ward = entry.get("ward", "System")
                action_type = entry.get("action_type", "maintain_monitoring")
                event = entry.get("event", "recommended").title()
                amount = entry.get("amount", 0)
                timestamp = entry.get("timestamp", simulation_now.isoformat())
                reason = entry.get("message") or entry.get("reason") or "No additional detail provided."
                st.markdown(
                    f"**{timestamp}** | {event} | {ward} | `{action_type}` x {amount}<br>{reason}",
                    unsafe_allow_html=True,
                )

    interviews = list(st.session_state.realtime_state.get("manager_interviews", []))
    if interviews:
        with st.expander("Manager Interview Q&A", expanded=False):
            for interview in reversed(interviews[-6:]):
                st.markdown(
                    f"**{interview.get('timestamp')}** | {interview.get('ward')} | `{interview.get('recommendation_id')}`"
                )
                for qa in interview.get("qa", []):
                    st.markdown(f"- **Q:** {qa.get('question', '')}")
                    st.markdown(f"- **A:** {qa.get('answer', '')}")
                st.write("")

    patient_events = list(st.session_state.realtime_state.get("patient_events", []))
    if patient_events:
        with st.expander("Patient Journey Trace", expanded=False):
            for event in reversed(patient_events[-20:]):
                timestamp = event.get("timestamp")
                if hasattr(timestamp, "isoformat"):
                    timestamp = timestamp.isoformat()
                st.markdown(
                    f"**{timestamp}** | {event.get('patient_id')} | {event.get('ward')} | "
                    f"{event.get('event')} | acuity={event.get('acuity')} | {event.get('note', '')}"
                )


def build_svg_line_chart(points, labels, stroke, width=760, height=240):
    if not points:
        return "<div class='nhs-card'>No chart data available.</div>"

    padding_left = 42
    padding_right = 16
    padding_top = 18
    padding_bottom = 30
    plot_width = width - padding_left - padding_right
    plot_height = height - padding_top - padding_bottom

    min_value = min(points)
    max_value = max(points)
    if max_value == min_value:
        max_value += 1

    coords = []
    for index, value in enumerate(points):
        x = padding_left if len(points) == 1 else padding_left + (index / (len(points) - 1)) * plot_width
        y = padding_top + ((max_value - value) / (max_value - min_value)) * plot_height
        coords.append((round(x, 2), round(y, 2)))

    polyline = " ".join(f"{x},{y}" for x, y in coords)
    x_labels = []
    step = max(1, len(labels) // 6)
    for index in range(0, len(labels), step):
        x, _ = coords[index]
        x_labels.append(
            f"<text x='{x}' y='{height - 8}' text-anchor='middle' font-size='10' fill='#48635d'>{labels[index]}</text>"
        )

    y_labels = []
    for tick in range(5):
        value = min_value + ((max_value - min_value) / 4) * tick
        y = padding_top + plot_height - (plot_height / 4) * tick
        y_labels.append(f"<text x='6' y='{y + 4}' font-size='10' fill='#48635d'>{value:.0f}</text>")
        y_labels.append(
            f"<line x1='{padding_left}' y1='{y}' x2='{width - padding_right}' y2='{y}' stroke='rgba(11,93,82,0.12)' stroke-width='1' />"
        )

    return f"""
    <svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-label="Trend chart">
        <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" rx="18"></rect>
        {''.join(y_labels)}
        <polyline fill="none" stroke="{stroke}" stroke-width="3" points="{polyline}"></polyline>
        {''.join(f"<circle cx='{x}' cy='{y}' r='3.5' fill='{stroke}'></circle>" for x, y in coords)}
        {''.join(x_labels)}
    </svg>
    """


def render_ward_trend(history):
    if history.empty:
        st.info("No ward trend data available.")
        return

    latest_rows = history.sort_values("timestamp").groupby("ward", as_index=False).tail(1)
    latest_rows = latest_rows.sort_values("occupancy_rate", ascending=False)

    for _, row in latest_rows.iterrows():
        occupancy_rate = float(row["occupancy_rate"])
        occupancy_pct = round(occupancy_rate * 100, 1)
        left, right = st.columns([0.7, 0.3])
        with left:
            st.write(row["ward"])
        with right:
            st.write(f"{occupancy_pct}%")
        st.progress(max(0.0, min(1.0, occupancy_rate)))


def render_operations_charts(history):
    st.subheader("Occupancy Trends")
    if history.empty:
        st.info("No occupancy history available yet.")
        return

    total_history = (
        history.groupby("timestamp", as_index=False)["occupied_beds"]
        .sum()
        .rename(columns={"occupied_beds": "Total Occupied Beds"})
    )
    total_history = total_history.sort_values("timestamp").tail(7)
    total_labels = total_history["timestamp"].dt.strftime("%d %b").tolist()
    total_points = total_history["Total Occupied Beds"].astype(float).tolist()
    total_svg = build_svg_line_chart(total_points, total_labels, "#0b5d52")
    st.markdown(total_svg, unsafe_allow_html=True)

    st.caption("Ward occupancy rate trend")
    render_ward_trend(history)


def render_hospital_map(snapshot, detailed: bool = True):
    st.subheader("Hospital Map")
    zones = build_hospital_map(snapshot)
    if not zones:
        st.info("No hospital map data available.")
        return
    ward_names = [zone["ward"] for zone in zones]
    default_index = 0
    if "selected_map_ward" in st.session_state and st.session_state.selected_map_ward in ward_names:
        default_index = ward_names.index(st.session_state.selected_map_ward)
    selected_ward = st.selectbox("Ward detail view", ward_names, index=default_index, key="selected_map_ward")
    width = max(zone["x"] + zone["w"] for zone in zones) + 24
    height = max(zone["y"] + zone["h"] for zone in zones) + 24
    svg_parts = [
        "<div class='nhs-card'>",
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' width='100%' height='{height}' role='img' aria-label='Hospital map'>",
        f"<rect x='0' y='0' width='{width}' height='{height}' rx='24' fill='#ffffff'></rect>",
    ]
    for zone in zones:
        staff = zone["staff"]
        is_selected = zone["ward"] == selected_ward
        stroke_width = 6 if is_selected else 3
        fill_opacity = 0.28 if is_selected else 0.15
        label_fill = "#0b3d36" if is_selected else "#16352f"
        svg_parts.append(
            f"""
            <g>
                <rect x="{zone['x']}" y="{zone['y']}" width="{zone['w']}" height="{zone['h']}" rx="18"
                    fill="{zone['fill']}" fill-opacity="{fill_opacity}" stroke="{zone['fill']}" stroke-width="{stroke_width}"></rect>
                <title>{zone['tooltip']}</title>
                <text x="{zone['x'] + 14}" y="{zone['y'] + 24}" font-size="16" font-weight="700" fill="{label_fill}">{zone['ward']}</text>
                <text x="{zone['x'] + 14}" y="{zone['y'] + 46}" font-size="13" fill="{label_fill}">Beds {zone['beds']}</text>
                <text x="{zone['x'] + 14}" y="{zone['y'] + 64}" font-size="13" fill="{label_fill}">Nurses {zone['nurses']}</text>
                <text x="{zone['x'] + 14}" y="{zone['y'] + 82}" font-size="13" fill="{label_fill}">Doctors {zone['doctors']}</text>
                <text x="{zone['x'] + 14}" y="{zone['y'] + 100}" font-size="13" fill="{label_fill}">Vent {zone['ventilators']} | Mon {zone['monitors']}</text>
                <text x="{zone['x'] + zone['w'] - 14}" y="{zone['y'] + 24}" text-anchor="end" font-size="12" fill="{label_fill}">{zone['occupancy']:.1f}% occ</text>
                <text x="{zone['x'] + zone['w'] - 14}" y="{zone['y'] + 46}" text-anchor="end" font-size="12" fill="{label_fill}">Staff {staff.get('total', 0)}</text>
            </g>
            """
        )
    svg_parts.extend(["</svg>", "</div>"])
    components.html("".join(svg_parts), height=height + 40)
    st.caption("Hover a ward for quick metrics. Use the selector below for the full table-backed detail view.")
    selected_zone = next(zone for zone in zones if zone["ward"] == selected_ward)
    details = selected_zone["details"]
    if detailed:
        st.subheader(f"{selected_ward} Detail")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Occupied Beds", f"{details['Occupied Beds']}/{details['Capacity']}")
        with col2:
            st.metric("Occupancy", f"{details['Occupancy %']:.1f}%")
        with col3:
            st.metric("Staff On Ward", int(details["Staff Total"]))
        with col4:
            st.metric("Predicted Peak", int(details["Predicted Peak Tomorrow"]))
    else:
        st.subheader(f"{selected_ward} Detail")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Occupied Beds", f"{details['Occupied Beds']}/{details['Capacity']}")
        with col2:
            st.metric("Available Beds", int(details["Capacity"] - details["Occupied Beds"]))
        with col3:
            st.metric("Ventilators", int(details["Ventilators Available"]))
        with col4:
            st.metric("Monitors", int(details["Monitors Available"]))
        equipment_frame = pd.DataFrame(
            [
                {"Metric": "Occupied Beds", "Value": details["Occupied Beds"]},
                {"Metric": "Total Beds", "Value": details["Capacity"]},
                {"Metric": "Available Beds", "Value": details["Capacity"] - details["Occupied Beds"]},
                {"Metric": "Ventilators Available", "Value": details["Ventilators Available"]},
                {"Metric": "Monitors Available", "Value": details["Monitors Available"]},
            ]
        )
        render_table_card(f"{selected_ward} Beds and Equipment", equipment_frame)
        return
    staffing_frame = pd.DataFrame(
        [
            {"Category": "Capacity", "Beds Occupied": details["Occupied Beds"], "Total Beds": details["Capacity"], "Occupancy %": f"{details['Occupancy %']:.1f}%"},
            {"Category": "Patient Flow", "Admissions/hr": details["Admissions/hr"], "Discharges/hr": details["Discharges/hr"], "Occupancy %": "-"},
            {"Category": "Staffing", "Total Staff": details["Staff Total"], "Active Clinical": details["Nurses Available"] + details["Doctors Available"], "Support Staff": details.get("Staff Support", 0)},
            {"Category": "Nurses", "Active": details["Nurses Available"], "Assigned": details["Staff Nurses"], "Required": details["Nurses Required"]},
            {"Category": "Doctors", "Active": details["Doctors Available"], "Assigned": details["Staff Doctors"], "Required": details["Doctors Required"]},
        ]
    )
    equipment_frame = pd.DataFrame(
        [
            {"Resource": "Beds", "Available": details["Capacity"] - details["Occupied Beds"], "Current": details["Occupied Beds"], "Total": details["Capacity"]},
            {"Resource": "Predicted Avg Tomorrow", "Available": details["Predicted Avg Tomorrow"], "Current": "-", "Total": details["Capacity"]},
            {"Resource": "Predicted Peak Tomorrow", "Available": details["Predicted Peak Tomorrow"], "Current": "-", "Total": details["Capacity"]},
            {"Resource": "Ventilators", "Available": details["Ventilators Available"], "Current": "-", "Total": details["Ventilators Required"]},
            {"Resource": "Monitors", "Available": details["Monitors Available"], "Current": "-", "Total": details["Monitors Required"]},
        ]
    )
    render_table_card(f"{selected_ward} Staffing Flow", staffing_frame)
    st.write("")
    render_table_card(f"{selected_ward} Resource Positioning", equipment_frame)


def render_operations_tables(snapshot, simulation_now):
    forecast_date = (simulation_now + pd.Timedelta(days=1)).strftime("%d %b %Y")
    render_table_card(
        "Ward Capacity and Forecast",
        snapshot[
            [
                "Ward",
                "Occupied Beds",
                "Capacity",
                "Occupancy %",
                "Admissions/hr",
                "Discharges/hr",
                "Predicted Avg Tomorrow",
                "Predicted Peak Tomorrow",
            ]
        ],
        highlight_rules=[
            lambda row, column: column == "Occupancy %" and float(row[column]) >= 90,
            lambda row, column: column == "Predicted Peak Tomorrow" and float(row[column]) >= float(row["Capacity"]),
        ],
    )
    st.caption(f"Forecast columns reflect the simulated next day: {forecast_date}.")
    st.write("")
    
    # Simplified Recommended Resource Positioning table - clear data, no complexity
    st.caption("Active staff comes from the Staff Assignment dataset. Required staff is calculated from current occupied beds.")
    
    # Build simplified resource positioning dataframe
    resource_data = []
    for _, row in snapshot.iterrows():
        resource_data.append({
            "Ward": row["Ward"],
            "Occupancy %": f"{float(row['Occupancy %']):.1f}%",
            "Nurses Active/Req": f"{int(row['Nurses Available'])}/{int(row['Nurses Required'])}",
            "Doctors Active/Req": f"{int(row['Doctors Available'])}/{int(row['Doctors Required'])}",
            "Support Staff": int(row.get("Staff Support", 0)),
            "Ventilators Avl/Req": f"{int(row['Ventilators Available'])}/{int(row['Ventilators Required'])}",
            "Monitors Avl/Req": f"{int(row['Monitors Available'])}/{int(row['Monitors Required'])}",
        })
    
    resource_df = pd.DataFrame(resource_data)
    render_table_card(
        "Recommended Resource Positioning",
        resource_df,
        highlight_rules=[
            lambda row, column: "/" in str(row[column]) and column.startswith("Nurses") and int(str(row[column]).split("/")[0]) < int(str(row[column]).split("/")[1]),
            lambda row, column: "/" in str(row[column]) and column.startswith("Doctors") and int(str(row[column]).split("/")[0]) < int(str(row[column]).split("/")[1]),
            lambda row, column: "/" in str(row[column]) and column.startswith("Ventilators") and int(str(row[column]).split("/")[0]) < int(str(row[column]).split("/")[1]),
            lambda row, column: "/" in str(row[column]) and column.startswith("Monitors") and int(str(row[column]).split("/")[0]) < int(str(row[column]).split("/")[1]),
        ],
    )


def render_operations_tab():
    if not has_permission(st.session_state.auth_user, "operations_view"):
        show_access_denied("Your role does not have access to the live operations dashboard.")
        return
    advanced_access = has_permission(st.session_state.auth_user, "operations_advanced")
    snapshot, history, alerts = build_operational_snapshot(st.session_state.realtime_state)
    save_realtime_state(st.session_state.realtime_state)
    simulation_now = st.session_state.realtime_state.get("simulation_now", st.session_state.realtime_state["last_updated"])
    render_operations_summary(snapshot)
    if advanced_access:
        st.caption(f"Prediction model: {FORECAST_MODEL_NAME}")
    if st.session_state.operation_message:
        st.success(st.session_state.operation_message)
    st.write("")
    if advanced_access:
        render_operations_controls()
        st.write("")
    render_real_mode_editor(advanced_access=advanced_access)
    if advanced_access and st.session_state.realtime_state.get("operation_mode") == "real":
        st.write("")
    render_hospital_map(snapshot, detailed=advanced_access)
    st.write("")
    if advanced_access and st.session_state.realtime_state.get("operation_mode") != "real":
        render_emergency_controls()
        st.write("")
    if advanced_access:
        left, right = st.columns([1.15, 0.85], gap="large")
        with left:
            render_operations_charts(history)
        with right:
            render_operations_alerts(alerts, snapshot, simulation_now)
        st.write("")
        render_operations_tables(snapshot, simulation_now)
        st.caption(
            f"Hospital time: {simulation_now.strftime('%d %b %Y %H:%M')} | "
            f"Mode: {st.session_state.realtime_state.get('operation_mode', 'simulation').title()}"
        )
    else:
        render_basic_operations_tables(snapshot)


def render_procurement_summary():
    state = st.session_state.workflow_state
    shortages = len(state["shortages"])
    staged = len(state["pending_orders"])
    total = state["total_spent"]
    render_metric_band(
        "Procurement Workflow",
        [
            {"label": "Critical Shortages", "value": shortages, "meta": "Items currently below threshold", "tone": "danger" if shortages else ""},
            {"label": "Staged Orders", "value": staged, "meta": "Orders waiting to be sent"},
            {"label": "Planned Spend", "value": f"GBP {total:,.2f}", "meta": "Current staged order value"},
            {
                "label": "Email Status",
                "value": "Sent" if state["email_sent"] else "Pending",
                "meta": "Supplier communication step",
                "tone": "" if state["email_sent"] else "warn",
            },
        ],
        subtitle="Track shortages, ordering momentum, and supplier communication at a glance.",
    )


def render_controls():
    state = st.session_state.workflow_state
    col1, col2, col3, col4, col5 = st.columns([1.1, 1.2, 1.1, 1.1, 0.9])

    with col1:
        if st.button("1. Run Audit", use_container_width=True):
            run_audit()

    with col2:
        disabled = (not bool(state["shortages"])) or bool(state["pending_orders"])
        if st.button("2. Approve and Stage", disabled=disabled, use_container_width=True):
            stage_orders()

    with col3:
        disabled = not bool(state["pending_orders"])
        if st.button("3. Draft Email", disabled=disabled, use_container_width=True):
            draft_email()

    with col4:
        disabled = (not bool(state["email_draft"])) or bool(state["email_sent"])
        if st.button("4. Send and Update", disabled=disabled, use_container_width=True):
            send_orders()

    with col5:
        if st.button("Reset Workflow", use_container_width=True):
            reset_session()
            rerun_app()


def render_main_panels():
    state = st.session_state.workflow_state
    left, right = st.columns([1.15, 0.85], gap="large")

    with left:
        st.subheader("Agent Activity")
        st.caption("Execution trace for stock checks, supplier lookups, order staging, and inventory updates.")
        trace_text = "\n\n".join(st.session_state.agent_trace) if st.session_state.agent_trace else "No agent activity yet."
        st.text_area(
            "Execution Trace",
            value=trace_text,
            height=520,
            label_visibility="collapsed",
        )

    with right:
        st.subheader("Draft Email")
        st.caption("Review the generated supplier confirmation email before inventory is updated.")
        st.text_area(
            "Draft Email",
            value=state["email_draft"] or "No email drafted yet.",
            height=520,
            label_visibility="collapsed",
        )


def render_tables():
    state = st.session_state.workflow_state
    col1, col2 = st.columns([1.1, 0.9], gap="large")

    with col1:
        render_table_card("Staged Receipt", receipt_dataframe(state["receipt"]))

    with col2:
        if state["shortages"]:
            shortage_rows = []
            for item_name in state["shortages"]:
                details = state["stock_details"].get(item_name, {})
                shortage_rows.append(
                    {
                        "Item": item_name,
                        "Current": details.get("quantity", 0),
                        "Threshold": details.get("critical_threshold", 0),
                        "Location": details.get("location", ""),
                    }
                )
            render_table_card("Critical Shortages", pd.DataFrame(shortage_rows))
        else:
            render_table_card("Critical Shortages", pd.DataFrame())


def render_status():
    state = st.session_state.workflow_state
    if st.session_state.last_report:
        st.success(st.session_state.last_report)

    if state["email_sent"]:
        st.info("Email approved and inventory updated.")
    elif state["email_draft"]:
        st.warning("Draft email ready for review.")
    elif state["pending_orders"]:
        st.warning("Orders are staged. Draft the email to continue.")


def render_procurement_tab():
    if not has_permission(st.session_state.auth_user, "procurement_view"):
        show_access_denied("Your role does not have access to the procurement workflow.")
        return
    render_procurement_summary()
    st.write("")
    render_controls()
    st.write("")
    render_status()
    render_main_panels()
    st.write("")
    render_tables()


def render_staff_assignment_tab():
    if not has_permission(st.session_state.auth_user, "staff_assign"):
        show_access_denied("Only managers can assign nurses and staff.")
        return

    records = load_staff_records()
    total_staff_count = len(records)
    
    st.subheader("Staff Assignment")
    st.caption("Managers can reassign staff between wards and shifts. Available and On duty count as active staffing in operations.")

    if not records:
        st.info("No staff records are available.")
        return

    # Display total counts at top
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Staff", total_staff_count)
    with col2:
        total_nurses = len([r for r in records if str(r.get("role", "")).strip().lower() == "nurse"])
        st.metric("Total Nurses", total_nurses)
    with col3:
        total_doctors = len([r for r in records if str(r.get("role", "")).strip().lower() == "doctor"])
        st.metric("Total Doctors", total_doctors)
    with col4:
        total_support = len([r for r in records if str(r.get("role", "")).strip().lower() == "support"])
        st.metric("Total Support Staff", total_support)
    with col5:
        active_staff = len([r for r in records if str(r.get("status", "")).strip().lower() in {"available", "on duty"}])
        st.metric("Currently Active", active_staff)

    staff_options = {
        f"{row['staff_id']} | {row.get('name', '')} | {row.get('role', '')} | {row.get('ward', '')}": row
        for row in records
    }
    selected_label = st.selectbox("Select staff member", list(staff_options.keys()))
    selected_record = staff_options[selected_label]

    with st.form("staff-assignment-form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            ward = st.selectbox(
                "Assign to ward",
                ["ICU", "Emergency", "General", "Surgery", "Maternity"],
                index=["ICU", "Emergency", "General", "Surgery", "Maternity"].index(selected_record.get("ward", "General"))
                if selected_record.get("ward", "General") in ["ICU", "Emergency", "General", "Surgery", "Maternity"]
                else 2,
            )
        with col2:
            shift_options = ["Day", "Night", "On-call"]
            shift = st.selectbox(
                "Shift",
                shift_options,
                index=shift_options.index(selected_record.get("shift", "Day"))
                if selected_record.get("shift", "Day") in shift_options
                else 0,
            )
        with col3:
            status_options = ["Available", "On duty", "Break"]
            status = st.selectbox(
                "Status",
                status_options,
                index=status_options.index(selected_record.get("status", "Available"))
                if selected_record.get("status", "Available") in status_options
                else 0,
            )
        submitted = st.form_submit_button("Save Assignment", use_container_width=True)

    if submitted:
        ok, message = assign_staff_member(selected_record["staff_id"], ward, shift, status)
        if ok:
            st.session_state.realtime_state["wards"] = sync_staff_counts_to_wards(
                st.session_state.realtime_state.get("wards", [])
            )
            save_realtime_state(st.session_state.realtime_state)
            st.success(message)
            rerun_app()
        else:
            st.error(message)

    ward_summary = summarize_staff_by_ward(records)
    summary_frame = pd.DataFrame(
        [
            {
                "Ward": ward_name,
                "Assigned Total": stats.get("total", 0),
                "Active Total": stats.get("active_total", 0),
                "Assigned Nurses": stats.get("nurses", 0),
                "Active Nurses": stats.get("nurses_available", 0),
                "Assigned Doctors": stats.get("doctors", 0),
                "Active Doctors": stats.get("doctors_available", 0),
                "Assigned Support": stats.get("support", 0),
                "Active Support": stats.get("support_available", 0),
            }
            for ward_name, stats in sorted(ward_summary.items())
        ]
    )
    render_table_card("Ward Staffing Summary", summary_frame)

    assignment_frame = pd.DataFrame(
        [
            {
                "Staff ID": row.get("staff_id", ""),
                "Name": row.get("name", ""),
                "Role": row.get("role", ""),
                "Ward": row.get("ward", ""),
                "Shift": row.get("shift", ""),
                "Status": row.get("status", ""),
            }
            for row in records
        ]
    )
    st.write(f"**Showing all {total_staff_count} staff members**")
    render_table_card("Current Staff Allocation", assignment_frame)


def main():
    init_session()
    if not st.session_state.auth_user:
        render_header()
        render_user_banner()
        render_login()
        return
    refresh_realtime_state()
    render_header()
    render_user_banner()
    if has_permission(st.session_state.auth_user, "operations_advanced"):
        render_auto_refresh()
    available_tabs = []
    if has_permission(st.session_state.auth_user, "operations_view"):
        available_tabs.append(("Live Operations Dashboard", render_operations_tab))
    if has_permission(st.session_state.auth_user, "staff_assign"):
        available_tabs.append(("Staff Assignment", render_staff_assignment_tab))
    if has_permission(st.session_state.auth_user, "procurement_view"):
        available_tabs.append(("Procurement Workflow", render_procurement_tab))

    if not available_tabs:
        st.warning("Your account is authenticated but has no dashboard permissions assigned.")
        return

    tabs = st.tabs([label for label, _ in available_tabs])
    for tab, (_, renderer) in zip(tabs, available_tabs):
        with tab:
            renderer()


if __name__ == "__main__":
    main()
