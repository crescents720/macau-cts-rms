# Macau CTS Hotel RMS

Revenue management prototype for Macau CTS hotels:

- Kyoto Hotel
- Emperor Hotel
- Hotel Riviera Macau
- Hotel Beverly Plaza

The first milestone is a working 90-day pricing recommendation dashboard with a FastAPI backend and a Next.js frontend.

## Tech Stack

- Backend: Python, FastAPI, psycopg, PostgreSQL
- Frontend: Next.js, React, TypeScript
- Database: PostgreSQL via Docker Compose
- Event intelligence: built-in holiday calendar, manual event review, Macau Government Tourism Office event source
- Future analytics: pandas, scikit-learn, LightGBM or XGBoost

## Project Layout

```text
hotel-rms/
  backend/      FastAPI API and pricing recommendation logic
  frontend/     Next.js management dashboard
  database/     PostgreSQL schema and Docker Compose setup
  data/         Sample event source data
  docs/         Product and architecture notes
```

## Features

- 90-day room-rate recommendation dashboard
- Dynamic room-type catalog for Kyoto, Emperor, Riviera, and Beverly Plaza
- Historical same-date and weekday/weekend base-rate comparison
- Built-in Macau and Mainland China holiday premium logic
- External event review workflow with hotel-specific impact weights
- Macau Government Tourism Office "What's On" event source ingestion
- Human-in-the-loop Ctrip RPA proof of concept for competitor rates

## Local Development

Database:

```powershell
cd database
docker compose up -d
```

Backend:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-db.txt
python scripts\apply_event_schema.py
python scripts\apply_competitor_schema.py
uvicorn app.main:app --port 8003
```

Frontend:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Then open `http://localhost:3000`.
