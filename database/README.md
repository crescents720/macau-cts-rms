# Database Notes

The MVP can start with in-memory demo data. The production direction is PostgreSQL with these core tables:

- hotels
- room_types
- rate_plans
- daily_rates
- occupancy_snapshots
- competitor_rates
- weather_daily
- border_crossing_daily
- events
- holidays
- pricing_recommendations

Future time-series tables such as rates, occupancy, and competitor prices can use TimescaleDB hypertables.

