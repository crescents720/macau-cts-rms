# Architecture

## Phase 1

- FastAPI provides hotel, room type, and recommendation APIs.
- Next.js provides the revenue management dashboard.
- Recommendation logic starts as transparent business rules.

## Phase 2

- PostgreSQL stores hotel inventory, historical prices, and recommendation runs.
- Data import supports CSV and Excel from hotel teams.
- Basic forecasting compares target dates with historical same-date and same-weekday performance.

## Phase 3

- Crawlers collect competitor prices, event calendars, weather, transport, border-crossing data, and news signals.
- Celery schedules recurring data collection and recommendation jobs.
- AI explains price movements and summarizes external market factors.

