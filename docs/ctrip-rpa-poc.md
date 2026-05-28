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

The first working approach is not calendar scraping. Instead, the script changes `checkIn` and `checkOut` in the URL one day at a time, then reads the visible room prices.

## Import Probe Result

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\import_ctrip_rpa_probe.py data\ctrip-rpa-probes\<scan-file>.json
```

This imports:

- competitor room types
- competitor rate observations with `source = ctrip_rpa`

It does not automatically map competitor room types to local hotel room types. Those mappings remain a manual review step in the `竞品价格` workspace.

## Current PoC Result

The first successful test against 澳门金龙酒店 read two stay dates and five visible room types per date:

- 高级大床房
- 高级双床房
- 海景豪华双床房
- 海景豪华大床房
- 豪华双床房

The date calendar opens, but its date cells do not expose reliable per-day prices in accessible text or HTML. The URL-per-date approach is currently more stable.
