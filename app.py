from contextlib import redirect_stdout
from io import StringIO

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from openai import OpenAI

from core.agents.saved_agents import communication_officer, manager
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
from core.tools.place_order import place_order

load_dotenv()


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
        st.session_state.auto_refresh = True
    if "operation_message" not in st.session_state:
        st.session_state.operation_message = ""
    if "skip_realtime_refresh_once" not in st.session_state:
        st.session_state.skip_realtime_refresh_once = False


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


def dataframe_to_html(dataframe, highlight_rules=None):
    headers = "".join(f"<th>{column}</th>" for column in dataframe.columns)
    rows = []

    for _, row in dataframe.iterrows():
        cells = []
        for column in dataframe.columns:
            css_class = ""
            if highlight_rules:
                for rule in highlight_rules:
                    if rule(row, column):
                        css_class = " class='danger-cell'"
                        break
            cells.append(f"<td{css_class}>{row[column]}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    return f"<table class='nhs-table'><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def render_table_card(title, dataframe, highlight_rules=None):
    st.subheader(title)
    if dataframe.empty:
        st.info(f"No data available for {title.lower()}.")
        return

    safe_frame = dataframe.fillna("").astype(str)
    styled_html = dataframe_to_html(safe_frame, highlight_rules=highlight_rules)
    st.markdown(styled_html, unsafe_allow_html=True)


def render_header():
    st.set_page_config(page_title="NHS-FLOW", layout="wide")
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top right, rgba(0, 105, 92, 0.18), transparent 24%),
                radial-gradient(circle at top left, rgba(205, 102, 0, 0.12), transparent 26%),
                linear-gradient(180deg, #ecf4ef 0%, #dcebe3 100%);
            color: #16352f;
        }
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            max-width: 1320px;
        }
        h1, h2, h3, .stCaption, label, p, div {
            color: #16352f;
        }
        .nhs-card {
            padding: 1rem 1.2rem;
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid rgba(14, 65, 58, 0.14);
            box-shadow: 0 18px 36px rgba(18, 61, 54, 0.10);
        }
        .hero {
            padding: 1.4rem 1.5rem;
            border-radius: 24px;
            background: linear-gradient(135deg, rgba(7, 66, 59, 0.96), rgba(20, 124, 111, 0.92));
            color: #f4fff9;
            box-shadow: 0 24px 48px rgba(11, 93, 82, 0.18);
            margin-bottom: 1rem;
        }
        .hero h1, .hero p {
            color: #f4fff9 !important;
        }
        .metric-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.8rem;
            margin-top: 0.8rem;
        }
        .metric-card {
            padding: 0.9rem 1rem;
            border-radius: 14px;
            background: #083d37;
            color: #f4fff9;
        }
        .label {
            font-size: 0.8rem;
            opacity: 0.8;
        }
        .value {
            font-size: 1.5rem;
            font-weight: 700;
        }
        .alert-card {
            padding: 0.95rem 1rem;
            border-left: 5px solid #d95d0f;
            background: rgba(255, 248, 239, 0.92);
            border-radius: 14px;
            margin-bottom: 0.7rem;
        }
        .danger-cell {
            background: #fff1f3 !important;
            color: #b42318 !important;
            font-weight: 700;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.8rem;
        }
        .stTabs [data-baseweb="tab"] {
            background: rgba(255, 255, 255, 0.72);
            border-radius: 14px;
            padding: 0.5rem 1rem;
        }
        .stButton > button {
            background: linear-gradient(135deg, #0b5d52 0%, #0f7a6b 100%);
            color: #f7fffc !important;
            border: 0;
            border-radius: 12px;
            font-weight: 700;
            font-size: 0.98rem;
            min-height: 3rem;
            box-shadow: 0 10px 24px rgba(11, 93, 82, 0.18);
        }
        .stButton > button:hover {
            background: linear-gradient(135deg, #0f6d60 0%, #12907e 100%);
            color: #ffffff !important;
        }
        .stButton > button p, .stButton > button span, .stButton > button div {
            color: #f7fffc !important;
        }
        .stTextArea textarea {
            background: #fbfdfc;
            color: #17342f;
            border-radius: 14px;
            border: 1px solid rgba(13, 80, 70, 0.18);
        }
        table.nhs-table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(255, 255, 255, 0.94);
            border-radius: 14px;
            overflow: hidden;
            box-shadow: 0 12px 24px rgba(18, 61, 54, 0.08);
        }
        table.nhs-table thead th {
            background: #0b5d52;
            color: #f5fffb !important;
            text-align: left;
            padding: 0.85rem 0.9rem;
            font-size: 0.92rem;
        }
        table.nhs-table tbody td {
            padding: 0.8rem 0.9rem;
            border-bottom: 1px solid rgba(14, 65, 58, 0.08);
            color: #17342f !important;
            background: rgba(255, 255, 255, 0.96);
        }
        table.nhs-table tbody tr:nth-child(even) td {
            background: #f3f8f5;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="hero">
            <h1>NHS-FLOW Command Center</h1>
            <p>Live bed occupancy, tomorrow forecasting, resource allocation recommendations, and procurement operations in one control surface.</p>
        </div>
        """,
        unsafe_allow_html=True,
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
                    window.parent.location.reload();
                }}, {UPDATE_INTERVAL_SECONDS * 1000});
            </script>
            """,
            height=0,
        )


def render_operations_summary(snapshot):
    totals = build_system_totals(snapshot)
    st.markdown(
        f"""
        <div class="nhs-card">
            <strong>Live Capacity Monitor</strong>
            <div class="metric-strip">
                <div class="metric-card">
                    <div class="label">Beds Occupied Now</div>
                    <div class="value">{totals['occupied']}</div>
                </div>
                <div class="metric-card">
                    <div class="label">Beds Available</div>
                    <div class="value">{totals['available']}</div>
                </div>
                <div class="metric-card">
                    <div class="label">Current Occupancy</div>
                    <div class="value">{totals['occupancy_pct']}%</div>
                </div>
                <div class="metric-card">
                    <div class="label">Predicted Peak Tomorrow</div>
                    <div class="value">{totals['predicted_peak']}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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


def render_real_mode_editor():
    if st.session_state.realtime_state.get("operation_mode") != "real":
        return
    st.subheader("Real Mode Ward Updates")
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
            nurses_available = st.number_input("Nurses available", min_value=0, value=int(ward["nurses_available"]), step=1)
            doctors_available = st.number_input("Doctors available", min_value=0, value=int(ward["doctors_available"]), step=1)
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
            "nurses_available": nurses_available,
            "doctors_available": doctors_available,
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


def render_hospital_map(snapshot):
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
    st.markdown(
        f"""
        <div class="nhs-card">
            <strong>{selected_ward} Detail</strong>
            <div class="metric-strip">
                <div class="metric-card">
                    <div class="label">Occupied Beds</div>
                    <div class="value">{details['Occupied Beds']}/{details['Capacity']}</div>
                </div>
                <div class="metric-card">
                    <div class="label">Occupancy</div>
                    <div class="value">{details['Occupancy %']:.1f}%</div>
                </div>
                <div class="metric-card">
                    <div class="label">Staff On Ward</div>
                    <div class="value">{details['Staff Total']}</div>
                </div>
                <div class="metric-card">
                    <div class="label">Predicted Peak</div>
                    <div class="value">{details['Predicted Peak Tomorrow']}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    staffing_frame = pd.DataFrame(
        [
            {"Metric": "Admissions/hr", "Value": details["Admissions/hr"]},
            {"Metric": "Discharges/hr", "Value": details["Discharges/hr"]},
            {"Metric": "Nurses Available", "Value": details["Nurses Available"]},
            {"Metric": "Nurses Required", "Value": details["Nurses Required"]},
            {"Metric": "Doctors Available", "Value": details["Doctors Available"]},
            {"Metric": "Doctors Required", "Value": details["Doctors Required"]},
            {"Metric": "Staff Nurses", "Value": details["Staff Nurses"]},
            {"Metric": "Staff Doctors", "Value": details["Staff Doctors"]},
        ]
    )
    equipment_frame = pd.DataFrame(
        [
            {"Metric": "Predicted Avg Tomorrow", "Value": details["Predicted Avg Tomorrow"]},
            {"Metric": "Predicted Peak Tomorrow", "Value": details["Predicted Peak Tomorrow"]},
            {"Metric": "Ventilators Available", "Value": details["Ventilators Available"]},
            {"Metric": "Ventilators Required", "Value": details["Ventilators Required"]},
            {"Metric": "Monitors Available", "Value": details["Monitors Available"]},
            {"Metric": "Monitors Required", "Value": details["Monitors Required"]},
        ]
    )
    left, right = st.columns(2, gap="large")
    with left:
        render_table_card(f"{selected_ward} Staffing Flow", staffing_frame)
    with right:
        render_table_card(f"{selected_ward} Equipment and Forecast", equipment_frame)


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
    render_table_card(
        "Recommended Resource Positioning",
        snapshot[
            [
                "Ward",
                "Nurses Available",
                "Nurses Required",
                "Doctors Available",
                "Doctors Required",
                "Ventilators Available",
                "Ventilators Required",
                "Monitors Available",
                "Monitors Required",
            ]
        ],
        highlight_rules=[
            lambda row, column: column == "Nurses Available" and int(row["Nurses Available"]) < int(row["Nurses Required"]),
            lambda row, column: column == "Nurses Required" and int(row["Nurses Available"]) < int(row["Nurses Required"]),
            lambda row, column: column == "Doctors Available" and int(row["Doctors Available"]) < int(row["Doctors Required"]),
            lambda row, column: column == "Doctors Required" and int(row["Doctors Available"]) < int(row["Doctors Required"]),
            lambda row, column: column == "Ventilators Available" and int(row["Ventilators Available"]) < int(row["Ventilators Required"]),
            lambda row, column: column == "Ventilators Required" and int(row["Ventilators Available"]) < int(row["Ventilators Required"]),
            lambda row, column: column == "Monitors Available" and int(row["Monitors Available"]) < int(row["Monitors Required"]),
            lambda row, column: column == "Monitors Required" and int(row["Monitors Available"]) < int(row["Monitors Required"]),
        ],
    )


def render_operations_tab():
    snapshot, history, alerts = build_operational_snapshot(st.session_state.realtime_state)
    save_realtime_state(st.session_state.realtime_state)
    simulation_now = st.session_state.realtime_state.get("simulation_now", st.session_state.realtime_state["last_updated"])
    render_operations_summary(snapshot)
    st.caption(f"Prediction model: {FORECAST_MODEL_NAME}")
    if st.session_state.operation_message:
        st.success(st.session_state.operation_message)
    st.write("")
    render_operations_controls()
    st.write("")
    render_real_mode_editor()
    if st.session_state.realtime_state.get("operation_mode") == "real":
        st.write("")
    render_hospital_map(snapshot)
    st.write("")
    if st.session_state.realtime_state.get("operation_mode") != "real":
        render_emergency_controls()
        st.write("")
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


def render_procurement_summary():
    state = st.session_state.workflow_state
    shortages = len(state["shortages"])
    staged = len(state["pending_orders"])
    total = state["total_spent"]

    st.markdown(
        f"""
        <div class="nhs-card">
            <strong>Procurement Workflow</strong>
            <div class="metric-strip">
                <div class="metric-card">
                    <div class="label">Critical Shortages</div>
                    <div class="value">{shortages}</div>
                </div>
                <div class="metric-card">
                    <div class="label">Staged Orders</div>
                    <div class="value">{staged}</div>
                </div>
                <div class="metric-card">
                    <div class="label">Total Planned Spend</div>
                    <div class="value">GBP {total:,.2f}</div>
                </div>
                <div class="metric-card">
                    <div class="label">Email Status</div>
                    <div class="value">{"Sent" if state["email_sent"] else "Pending"}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
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
    render_procurement_summary()
    st.write("")
    render_controls()
    st.write("")
    render_status()
    render_main_panels()
    st.write("")
    render_tables()


def main():
    init_session()
    refresh_realtime_state()
    render_header()
    render_auto_refresh()

    operations_tab, procurement_tab = st.tabs(
        ["Live Operations Dashboard", "Procurement Workflow"]
    )

    with operations_tab:
        render_operations_tab()

    with procurement_tab:
        render_procurement_tab()


if __name__ == "__main__":
    main()
