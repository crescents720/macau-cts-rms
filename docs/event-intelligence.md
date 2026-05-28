# Event Intelligence

The event system is designed so external information can be collected safely before it affects pricing.

## Flow

```text
Source collection -> event candidate -> dedupe/review -> confirmed event -> pricing impact
```

Only `confirmed` events are used by the pricing model.

## Tables

- `venue_locations`: known Macau venues and approximate coordinates
- `hotel_locations`: hotel coordinates used for distance impact
- `external_event_sources`: source metadata
- `external_events`: event candidates and confirmed events
- `event_hotel_impacts`: per-hotel impact weights derived from event type, level, and distance

## Manual Import

Apply schema:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\apply_event_schema.py
```

Import CSV:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\import_external_events.py --csv ..\data\sample_external_events.csv
```

CSV fields:

```text
name,event_type,start_date,end_date,venue_id,source_name,source_type,source_url,confidence_score,impact_level,base_weight,status,notes
```

Recommended statuses:

- `candidate`: stored for review, does not affect pricing
- `confirmed`: affects pricing
- `rejected`: ignored
- `expired`: retained but ignored

## Pricing Use

For each stay date and hotel, the model queries confirmed external events active on that date. Each event contributes a per-hotel `final_weight`, with a cap of 35% for external event premium.

Built-in public holidays and external events are additive, with a combined event premium cap of 50%.

