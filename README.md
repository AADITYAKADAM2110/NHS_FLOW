# NHS-FLOW

NHS-FLOW is a Python project for simulating hospital operations and coordinating medical supply procurement with OpenAI-powered agents. The repository includes a Streamlit command center, a CLI workflow, and a dataset generator for mock NHS-style operational data.

## What the project includes

- A `Streamlit` dashboard in `app.py` with two views:
  - Live Operations Dashboard for bed occupancy, ward pressure, forecasts, and emergency actions
  - Procurement Workflow for shortage detection, supplier lookup, email drafting, and inventory updates
- A CLI workflow in `main.py` that runs the same procurement flow with supervisor approval steps
- A synthetic data generator in `generate_data.py` that creates inventory, supplier, bed, staff, equipment, and occupancy-history JSON files
- OpenAI agent definitions in `core/agents/saved_agents.py`
- Supporting procurement tools in `core/tools`

## Features

- Simulated ward capacity tracking across ICU, Emergency, General, Surgery, and Maternity
- Forecasting for next-day average and peak occupancy
- Operational recommendations with optional AI-generated explanations
- Emergency actions such as extra staffing, opening extra beds, and full stabilization
- Inventory audit for critical shortages
- Supplier matching with NHS approval and delivery-time data
- Order staging, receipt generation, and supplier email drafting

## Project structure

```text
NHS_FLOW/
|- app.py
|- main.py
|- generate_data.py
|- requirements.txt
|- .env
`- core/
   |- agents/
   |- data/
   |- realtime_ops.py
   |- session_variables/
   `- tools/
```

## Requirements

- Python 3.12+
- An OpenAI API key in `.env`

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

Run the generator to create fresh JSON datasets:

```bash
python generate_data.py
```

This writes files such as:

- `core/data/inventory.json`
- `core/data/suppliers.json`
- `core/data/beds.json`
- `core/data/staff.json`
- `core/data/equipment.json`
- `core/data/occupancy_history.json`

## Run the app

Start the Streamlit dashboard:

```bash
streamlit run app.py
```

Start the CLI workflow:

```bash
python main.py
```

## Notes

- The main user experience is the Streamlit app in `app.py`.
- The live operations board uses a simulated hospital clock and refresh cycle defined in `core/realtime_ops.py`.
- The repository currently contains some legacy hard-coded data paths in older helper files. The dataset generator itself writes to `core/data/`.

## Dependencies

The project currently uses:

- `openai`
- `python-dotenv`
- `pandas`
- `numpy`
- `streamlit`
- `altair<5`
