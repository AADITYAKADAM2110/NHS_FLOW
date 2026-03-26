# NHS-FLOW

NHS-FLOW is a Python hospital operations and procurement simulator built around a Streamlit control center, JSON-backed mock datasets, and lightweight OpenAI-powered procurement agents.

The project currently combines three main workflows:

- A role-based Streamlit dashboard for hospital operations, staff assignment, and procurement
- A CLI procurement flow with supervisor approval checkpoints
- A mock data generator for the current runtime datasets

## Current app overview

The main entry point is [app.py](/c:/Users/DELL/Desktop/NHS_FLOW/app.py). After login, users see different parts of the system depending on their role.

### Roles

- `staff`: can view the hospital map, bed/equipment status, and edit ward bed/equipment values
- `nurse`: same access as staff
- `manager`: full access to operations, simulation controls, forecasts, recommendations, staff assignment, and procurement
- `procurement_officer`: access to the procurement workflow only

Role definitions and demo credentials are stored in [core/auth.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/auth.py) and [core/data/users.json](/c:/Users/DELL/Desktop/NHS_FLOW/core/data/users.json).

### Operations dashboard

The operations side combines real-time style simulation with manual updates:

- Hospital map with ward-level occupancy and equipment visibility
- Bed and equipment tables
- Ward editing for beds and equipment
- Manager-only simulation controls
- Manager-only forecasting and occupancy trends
- Manager-only operational recommendations and emergency actions
- Manager-only recommended resource positioning view

The operational runtime uses a small set of JSON files under `core/data/`:

- `realtime_state.json` for live ward, bed, equipment, forecast, and simulation state
- `staff.json` for staff assignment and staffing availability
- `suppliers.json` for supplier data
- `inventory.json` for stock data
- `users.json` for login accounts and roles

Meaning of staffing terms:

- `assigned`: total staff assigned to a ward in `staff.json`
- `active` or `available`: staff in `Available` or `On duty` status
- `required`: staffing demand calculated from current occupied beds in `realtime_state.json`

Relevant modules:

- [core/realtime/state.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/realtime/state.py)
- [core/realtime/simulation.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/realtime/simulation.py)
- [core/realtime/manual_ops.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/realtime/manual_ops.py)
- [core/realtime/snapshot.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/realtime/snapshot.py)
- [core/realtime/map_data.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/realtime/map_data.py)

### Staff assignment

Managers can reassign staff between wards and shifts through a dedicated tab in the Streamlit app. Assignments are persisted to `core/data/staff.json`.

The staff views now distinguish between:

- `Assigned Total`: all staff assigned to a ward
- `Active Total`: staff whose status is `Available` or `On duty`
- `Assigned Nurses` / `Assigned Doctors`: total assigned clinical headcount
- `Active Nurses` / `Active Doctors`: currently active clinical headcount

The Staff Assignment tab shows:

- a ward staffing summary
- the full current staff allocation list from `staff.json`

Relevant module:

- [core/staff_ops.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/staff_ops.py)

### Procurement workflow

The procurement flow supports:

- inventory audit for shortages
- supplier lookup for NHS-approved vendors
- order staging
- draft email generation
- inventory update after confirmation

This workflow exists in both:

- the Streamlit dashboard in [app.py](/c:/Users/DELL/Desktop/NHS_FLOW/app.py)
- the CLI supervisor flow in [main.py](/c:/Users/DELL/Desktop/NHS_FLOW/main.py)

Relevant modules:

- [core/agents/core_agent.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/agents/core_agent.py)
- [core/agents/saved_agents.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/agents/saved_agents.py)
- [core/tools/check_stock_function.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/tools/check_stock_function.py)
- [core/tools/get_supplier_function.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/tools/get_supplier_function.py)
- [core/tools/place_order.py](/c:/Users/DELL/Desktop/NHS_FLOW/core/tools/place_order.py)

## Project structure

```text
NHS_FLOW/
|- app.py
|- main.py
|- generate_data.py
|- requirements.txt
|- pyproject.toml
`- core/
   |- agents/
   |- data/
   |- realtime/
   |- tools/
   |- auth.py
   |- staff_ops.py
   `- realtime_ops.py
```

## Requirements

- Python 3.12+
- A virtual environment is recommended
- `OPENAI_API_KEY` in `.env` if you want OpenAI-backed procurement and AI recommendation features

Example `.env`:

```env
OPENAI_API_KEY=your_api_key_here
```

## Install

Using `pip`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Using `uv`:

```bash
uv sync
```

## Generate mock data

To regenerate the demo datasets:

```bash
python generate_data.py
```

This writes:

- `core/data/inventory.json`
- `core/data/suppliers.json`
- `core/data/staff.json`
- `core/data/realtime_state.json`

## Run the Streamlit app

```bash
streamlit run app.py
```

### Demo login accounts

The current app ships with JSON-backed demo users:

- Manager: `MGR-1001` / `manager123`
- Nurse: `NUR-1001` / `nurse123`
- Staff: `STF-1001` / `staff123`
- Procurement Officer: `PRO-1001` / `procure123`

## Run the CLI procurement flow

```bash
python main.py
```

This runs a terminal-based approval flow where the system:

1. audits stock
2. finds suppliers
3. pauses for supervisor approval
4. stages orders
5. drafts supplier email text
6. updates inventory on confirmation

## Forecasting and recommendations

The operations forecast layer currently uses a lightweight linear regression approach with a trend term and weekly seasonality term. The display label is defined as:

- `Linear regression with trend + weekly seasonality`

Operational recommendations can come from:

- rules-based gap detection
- OpenAI-generated structured recommendations when available

When OpenAI is unavailable, the app falls back to deterministic rules.

## Data notes

The project is JSON-backed and intended for simulation/demo use. The app reads and writes directly to files in `core/data/`.

Current runtime datasets:

- `inventory.json`
- `suppliers.json`
- `staff.json`
- `realtime_state.json`
- `users.json`

## Known limitations

- Login uses plain-text passwords in `core/data/users.json`, which is acceptable for a prototype but not production-safe.
- Some older helper modules still contain legacy path assumptions or older comments, especially in `core/session_variables/session_variables.py`.
- The system uses mock data and JSON persistence rather than a real database.
- Procurement and AI recommendation behavior depends on an OpenAI API key and compatible library access.

## Dependencies

Declared dependencies across `requirements.txt` and `pyproject.toml` include:

- `openai`
- `python-dotenv`
- `pandas`
- `numpy`
- `streamlit`
- `altair<5`
- `plotly`
