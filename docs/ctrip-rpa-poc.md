# Ctrip RPA PoC

The Ctrip collector is a human-in-the-loop RPA probe. It is intentionally conservative:

- It uses a dedicated Edge browser profile under `backend/data/browser-profiles/ctrip-edge`.
- The user handles login, captcha, consent, and any account prompts manually.
- The script does not bypass anti-bot controls.
- Output files are written under `backend/data/ctrip-rpa-probes`, which is ignored by Git.

## Probe One Hotel Page

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\ctrip_rpa_probe.py --pause-seconds 90
```

If a Ctrip login page appears, scan the QR code with the Ctrip app. The profile keeps the login session for later runs.

The probe writes:

- full-page screenshot
- visible text
- HTML snapshot
- JSON with room and price candidates

## Scan Future Dates

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\ctrip_rpa_probe.py --pause-seconds 3 --scan-days 2 --scan-delay-seconds 8
```

This direct scan changes `checkIn` and `checkOut` in the URL one day at a time, then reads the visible room prices. It is useful for small checks, but it is too chatty for a full 90-day run.

## Multiplier Strategy

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\ctrip_rpa_probe.py --pause-seconds 3 --multiplier-strategy --calendar-days 90 --scan-delay-seconds 8
```

For hotels that do not have a stored Ctrip URL yet, let the script read the competitor hotel name from the database and resolve the Ctrip detail page from search results:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\ctrip_rpa_probe.py --hotel-id rio --hotel-name-from-db --pause-seconds 3 --multiplier-strategy --calendar-days 90 --scan-delay-seconds 8
```

The preferred PoC strategy is:

- Read all visible room prices for the start date.
- Read all visible room prices for the nearest opposite day type, so both weekday and weekend have a sample.
- Compute each room type as a multiplier of that date's lowest visible room price.
- Open the Ctrip calendar and read daily hotel-level minimum prices.
- Estimate future room-type prices by applying weekday/weekend multipliers to each calendar minimum price.

This reduces page visits sharply. It keeps observed sample prices and estimated future prices separate in the JSON.

## Batch Collection

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\collect_ctrip_competitors.py --calendar-days 90
```

The batch collector reads active competitor hotels from the database, resolves each hotel by name on Ctrip, runs the multiplier strategy, and imports the resulting JSON into the competitor pricing tables. To test only one or two hotels:

```powershell
.\.venv\Scripts\python.exe scripts\collect_ctrip_competitors.py --hotel-ids rio,sintra --calendar-days 14
```

## Import Probe Result

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\import_ctrip_rpa_probe.py data\ctrip-rpa-probes\<scan-file>.json
```

This imports:

- competitor room types
- direct scan observations with `source = ctrip_rpa`
- multiplier sample observations with `source = ctrip_rpa_observed`
- multiplier estimates with `source = ctrip_rpa_estimated`

It does not automatically map competitor room types to local hotel room types. Those mappings remain a manual review step in the `竞品价格` workspace.

## Current PoC Result

The first successful test against 澳门金龙酒店 read two stay dates and five visible room types per date:

- 高级大床房
- 高级双床房
- 海景豪华双床房
- 海景豪华大床房
- 豪华双床房

The multiplier strategy test read 87 valid calendar minimum-price dates from 2026-05-29 through 2026-08-25 and generated 435 estimated room-type rates from two sample dates. Two implausibly low calendar values were filtered out as parsing noise.
