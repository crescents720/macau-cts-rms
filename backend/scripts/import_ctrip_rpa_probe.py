from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import psycopg


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Ctrip RPA probe JSON into competitor tables.")
    parser.add_argument("json_path")
    parser.add_argument("--competitor-hotel-id", default=None)
    args = parser.parse_args()

    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    competitor_hotel_id = args.competitor_hotel_id or payload["hotel_id"]
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://hotel_rms:hotel_rms_dev@localhost:5432/hotel_rms",
    )

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            imported = import_payload(cursor, payload, competitor_hotel_id)
        conn.commit()

    print(json.dumps(imported, ensure_ascii=False, indent=2))


def import_payload(cursor: Any, payload: dict[str, Any], competitor_hotel_id: str) -> dict[str, int]:
    room_types = 0
    observations = 0
    for day in payload.get("daily_rates", []):
        stay_date = day["stay_date"]
        check_out = day["check_out"]
        for candidate in day.get("room_rate_candidates", []):
            room_type_id = upsert_room_type(cursor, competitor_hotel_id, candidate["room_name"])
            room_types += 1
            cursor.execute(
                """
                INSERT INTO competitor_rate_observations (
                    competitor_room_type_id, stay_date, check_in, check_out, price,
                    currency, source, source_url, raw_payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    room_type_id,
                    stay_date,
                    stay_date,
                    check_out,
                    candidate["price"],
                    candidate.get("currency") or "CNY",
                    "ctrip_rpa",
                    payload.get("source_url"),
                    json.dumps(candidate, ensure_ascii=False),
                ),
            )
            observations += 1
    return {"room_type_rows_seen": room_types, "rate_observations_inserted": observations}


def upsert_room_type(cursor: Any, competitor_hotel_id: str, room_name: str) -> int:
    cursor.execute(
        """
        INSERT INTO competitor_room_types (competitor_hotel_id, name, normalized_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (competitor_hotel_id, name) DO UPDATE
        SET active = TRUE,
            normalized_name = EXCLUDED.normalized_name,
            last_seen_at = now()
        RETURNING id
        """,
        (competitor_hotel_id, room_name, room_name),
    )
    return int(cursor.fetchone()[0])


if __name__ == "__main__":
    main()
