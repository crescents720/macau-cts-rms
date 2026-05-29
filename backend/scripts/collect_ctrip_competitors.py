from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Ctrip competitor rates by hotel name.")
    parser.add_argument("--hotel-ids", default=None, help="Comma-separated competitor hotel ids. Defaults to all active hotels.")
    parser.add_argument("--calendar-days", type=int, default=90)
    parser.add_argument("--pause-seconds", type=int, default=3)
    parser.add_argument("--scan-delay-seconds", type=int, default=8)
    parser.add_argument("--skip-import", action="store_true")
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parents[1]
    requested_ids = {
        hotel_id.strip()
        for hotel_id in (args.hotel_ids or "").split(",")
        if hotel_id.strip()
    }
    hotels = list_competitor_hotels(requested_ids)
    summaries = []

    for hotel in hotels:
        print(f"=== Collecting {hotel['id']} {hotel['name']} ===", flush=True)
        probe_command = [
            sys.executable,
            "scripts/ctrip_rpa_probe.py",
            "--hotel-id",
            hotel["id"],
            "--hotel-name-from-db",
            "--pause-seconds",
            str(args.pause_seconds),
            "--multiplier-strategy",
            "--calendar-days",
            str(args.calendar_days),
            "--scan-delay-seconds",
            str(args.scan_delay_seconds),
        ]
        probe = subprocess.run(
            probe_command,
            cwd=backend_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        print(probe.stdout, flush=True)
        if probe.stderr:
            print(probe.stderr, file=sys.stderr, flush=True)
        if probe.returncode != 0:
            summaries.append({"hotel_id": hotel["id"], "status": "probe_failed"})
            continue

        json_path = extract_json_path(probe.stdout)
        if not json_path:
            summaries.append({"hotel_id": hotel["id"], "status": "json_path_missing"})
            continue

        import_status = "skipped"
        if not args.skip_import:
            importer = subprocess.run(
                [sys.executable, "scripts/import_ctrip_rpa_probe.py", json_path],
                cwd=backend_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            print(importer.stdout, flush=True)
            if importer.stderr:
                print(importer.stderr, file=sys.stderr, flush=True)
            import_status = "imported" if importer.returncode == 0 else "import_failed"

        summaries.append({"hotel_id": hotel["id"], "status": "collected", "json_path": json_path, "import": import_status})

    print(json.dumps({"hotels": summaries}, ensure_ascii=False, indent=2))


def list_competitor_hotels(requested_ids: set[str]) -> list[dict[str, Any]]:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://hotel_rms:hotel_rms_dev@localhost:5432/hotel_rms",
    )
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name
                FROM competitor_hotels
                WHERE active = TRUE
                ORDER BY name
                """
            )
            rows = cursor.fetchall()
    hotels = [{"id": str(row[0]), "name": str(row[1])} for row in rows]
    if requested_ids:
        hotels = [hotel for hotel in hotels if hotel["id"] in requested_ids]
    return hotels


def extract_json_path(output: str) -> str | None:
    match = re.search(r'"json_path"\s*:\s*"(?P<path>[^"]+)"', output)
    if not match:
        return None
    return json.loads(f'"{match.group("path")}"')


if __name__ == "__main__":
    main()
