# Aviation Data Visualization & Predictive Scheduling System

A Streamlit application for airline operators, dispatchers, and aviation analysts to ingest, structure, and visualize flight schedule and operational data — with a machine-learning pipeline in progress for automated daily tail (aircraft registration) assignment.

The platform ingests historical flight data from the [Flightradar24 API](https://fr24api.flightradar24.com/docs/endpoints/flight-summary) ("Flight Summary Light"), stores it in Supabase/Postgres, and lets users build schedules, compare airline operators, and monitor fleet status through interactive dashboards.

## Project Roadmap & Current Status

The system is being built in three phases:

* **Phase 1 (current):** Interface development, data ingestion/processing, and visualization.
* **Phase 2:** Machine learning model training and predictive engineering.
* **Phase 3:** Automated daily schedule suggestions and corrections.

Since production-ready ML requires extensive historical data, an operational branch is available in the meantime for ingesting, structuring, and comparing operational metrics across airlines.

## Features

- **Operator Admin** — create/edit airline operator profiles (with subsidiaries), each backed by a 7-day automatic historical flight backfill from the FR24 API, with resumable incremental syncs (`pages/operators.py`, `pages/operator_profiles.py`).
- **Flight Input Pipeline** — a two-stage guided workflow that maps newly discovered aircraft registrations to fleet variants, then builds scheduled routes (local→UTC time conversion, blocktime, route category, domestic/international, day-of-week) from raw historical flights (`pages/flight_input_handler.py`).
- **Per-Operator Dashboard** — schedule tables, OTP/delay analytics, hub detection, multi-leg route sequencing, aircraft type breakdowns, and airport/country coverage (`pages/dashboard_sub.py`).
- **Comparative Dashboard** — side-by-side strategic comparison of 2+ airlines: fleet uniformity, turnaround efficiency, route overlap/competition matrix, and a hub-and-spoke network map (`pages/dashboard_overall.py`).
- **Fleet Status & Map** — live fleet readiness table (current location, previous arrival, next-ready time) plus a 3D `pydeck` arc map of recent aircraft movements (`pages/fleet_details.py`, `map_component.py`).
- **Aircraft Type Reference** — CRUD for the aircraft type/variant reference table used across turnaround and range calculations (`pages/aircraft_type.py`).
- **Daily Prediction (WIP)** — UI to trigger ML-based tail assignment for tomorrow's schedule and run a post-flight audit/retrain cycle (`pages/daily_prediction.py`, see [Known Limitations](#known-limitations--wip-notes)).
- **PIN-gated admin actions** — editing profiles, inputting flights, and deleting records require an admin PIN checked against Streamlit secrets.

## Tech Stack

- **Frontend/App:** [Streamlit](https://streamlit.io/) (multi-page app)
- **Database:** [Supabase](https://supabase.com/) (Postgres) — accessed via the `supabase` client for CRUD, and directly via `SQLAlchemy`/`psycopg2` for raw SQL (map queries)
- **Data processing:** `pandas`, `numpy`
- **Visualization:** `plotly`, `pydeck`
- **External data:** [Flightradar24 API](https://fr24api.flightradar24.com/) (`fr24sdk` / direct REST calls), `airportsdata`, `pycountry`, `pytz`
- **ML (in progress):** `scikit-learn` (encoding/pipelines), `lightgbm`, `joblib` (model persistence)

## Project Structure

```
.
├── app.py                        # Homepage / entry point
├── utils.py                      # Supabase & SQLAlchemy connections, page setup, global CSS
├── func.py                       # Time/timezone conversion, airport/operator lookups, day-of-week, cargo/domestic helpers
├── data_handler.py               # Cached data-fetch layer (operators, schedules, history, fleet, airports) + merge/turnaround processing
├── map_component.py              # Direct SQL query + pydeck 3D arc map for fleet movement
├── api_flight_handler.py         # FR24 API client, airport auto-sync, historical ingestion pipeline (resumable)
├── daily_pipeline.py             # Phase 4/5: fetch candidate flights/fleet, run ML inference for tail assignment
├── feedback_loop.py              # Phase 6: audit predictions vs. actuals, log corrections, retrain LightGBM models
├── training.py                   # (currently empty — reserved for standalone model training)
├── pages/
│   ├── operators.py              # Operator profile list / navigation hub
│   ├── operator_profiles.py      # Add/edit operator + subsidiaries, triggers historical ingestion
│   ├── aircraft_type.py          # Aircraft type/variant reference table CRUD
│   ├── flight_input_handler.py   # Fleet variant mapping + scheduled route builder
│   ├── dashboard_sub.py          # Per-operator detailed analytics dashboard
│   ├── dashboard_overall.py      # Cross-operator comparative dashboard
│   ├── fleet_details.py          # Fleet status table + flight-path map
│   └── daily_prediction.py       # ML tail-assignment trigger + audit UI (WIP)
├── .streamlit/
│   ├── config.toml               # Streamlit server/client config
│   └── secrets.toml              # Local secrets (gitignored)
├── .devcontainer/devcontainer.json
└── requirements.txt
```

## Data Model (Supabase tables referenced in code)

| Table | Purpose |
|---|---|
| `operators` | Airline operator profiles (ICAO/IATA codes, country, subsidiary linkage) |
| `aircraft_type` | Reference table: variant → manufacturer, type code, body type/category, range category |
| `fleet` | Aircraft registrations mapped to an operator + variant + minimum turnaround time |
| `fleet_status` | Live/derived fleet readiness (current airport, next-ready time, previous arrival) |
| `flight_list` | Scheduled routes (departure/arrival airports, times, route type/category, day of week, used variants) |
| `historical_flight_input` | Raw ingested flight legs from the FR24 API (also stores audit corrections) |
| `airport_list` | Airport reference data (ICAO/IATA, city, country, timezone, coordinates) |
| `airport_operators` | Per-operator airport visit/frequency counts |
| `flight_logs` | Source table for the fleet movement map (`map_component.py`) |
| `predict_reg` | ML-predicted tail assignments per flight |
| `correction_logs` | Prediction-vs-actual audit results used to measure model accuracy |

A Postgres RPC function, `sync_flight_pipeline`, is invoked from `flight_input_handler.py` to persist newly defined routes.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure secrets

Create `.streamlit/secrets.toml` (gitignored) with:

```toml
# Supabase client (CRUD access)
SUPABASE_URL = "https://<project>.supabase.co"
SUPABASE_KEY = "<service-or-anon-key>"

# Direct Postgres connection (used by map_component.py via SQLAlchemy)
user = "<db-user>"
password = "<db-password>"
host = "<db-host>"
port = "<db-port>"
dbname = "<db-name>"

# Flightradar24 API
FR24_API_TOKEN = "<your-fr24-api-token>"

# Admin PIN gating profile edits, flight input, and deletions
ADMIN_PIN = "<choose-a-pin>"
```

### 3. Run the app

```bash
streamlit run app.py
```

The app runs on port `8501` by default. A `.devcontainer` config is provided for GitHub Codespaces / VS Code Dev Containers.

## Typical Workflow

1. **Add an operator** (`Admin → Add Profile`): enter ICAO/IATA/country. Creating a profile triggers an automatic 7-day historical ingestion from FR24; failed ingestion rolls back the newly created operator record.
2. **Map fleet & build routes** (`Input Flights`, PIN-protected): assign discovered tail numbers to aircraft variants, then define scheduled local departure/arrival times for newly discovered routes. The system converts to UTC, computes blocktime, route category (short/medium/long haul), and domestic/international classification.
3. **Explore dashboards**: use the per-operator dashboard for detailed OTP/turnaround/route analytics, or the comparative dashboard to benchmark multiple airlines side by side.
4. **Monitor fleet**: check `Fleet Details` for current aircraft locations, readiness times, and a 3D map of recent movements.
5. **(WIP) Generate predictions**: from an operator's dashboard, trigger tomorrow's ML-based tail assignment and later run the audit/retrain cycle once flights have landed.

## Known Limitations / WIP Notes

- `pages/daily_prediction.py` imports `fetch_mock_fr24_data` from `api_flight_handler.py`, but that module only defines `fetch_fr24_data` — the audit trigger will raise an `ImportError` until this is reconciled.
- The audit UI in `pages/daily_prediction.py` currently overwrites the real `evaluate_predictions` result with hardcoded mock accuracy numbers for UI testing.
- `training.py` is currently empty; standalone model training is currently handled inline by `retrain_models_from_history()` in `feedback_loop.py`.
- `retrain_models_from_history()` mocks several joined feature columns (day of week, route type/category, ground time) rather than deriving them from real joined data — flagged in-code as a structural placeholder.
- ML models are persisted to `model_registry/<model|encoder>_<operator_icao>.pkl` via `joblib`; this directory is not currently tracked in the repo and must exist for Phase 4/5 to run.
