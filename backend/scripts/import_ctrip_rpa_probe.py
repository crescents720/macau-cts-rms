from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
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
            update_competitor_hotel_metadata(cursor, payload, competitor_hotel_id)
            imported = import_payload(cursor, payload, competitor_hotel_id)
        conn.commit()

    print(json.dumps(imported, ensure_ascii=False, indent=2))


def update_competitor_hotel_metadata(
    cursor: Any,
    payload: dict[str, Any],
    competitor_hotel_id: str,
) -> None:
    resolved_url = payload.get("resolved_hotel_url") or payload.get("source_url")
    resolved_hotel_id = payload.get("resolved_ctrip_hotel_id")
    if not resolved_url and not resolved_hotel_id:
        return
    cursor.execute(
        """
        UPDATE competitor_hotels
        SET ctrip_url = COALESCE(%s, ctrip_url),
            ctrip_hotel_id = COALESCE(%s, ctrip_hotel_id),
            updated_at = now()
        WHERE id = %s
        """,
        (resolved_url, resolved_hotel_id, competitor_hotel_id),
    )


def import_payload(cursor: Any, payload: dict[str, Any], competitor_hotel_id: str) -> dict[str, int]:
    if payload.get("strategy") == "ctrip_multiplier":
        return import_multiplier_payload(cursor, payload, competitor_hotel_id)
    return import_daily_scan_payload(cursor, payload, competitor_hotel_id)


def import_daily_scan_payload(cursor: Any, payload: dict[str, Any], competitor_hotel_id: str) -> dict[str, int]:
    room_types = 0
    observations = 0
    for day in payload.get("daily_rates", []):
        stay_date = day["stay_date"]
        check_out = day["check_out"]
        for candidate in day.get("room_rate_candidates", []):
            room_type_id = upsert_room_type(cursor, competitor_hotel_id, candidate["room_name"])
            room_types += 1
            insert_rate_observation(
                cursor=cursor,
                room_type_id=room_type_id,
                stay_date=stay_date,
                check_out=check_out,
                price=candidate["price"],
                currency=candidate.get("currency") or "CNY",
                source="ctrip_rpa",
                source_url=payload.get("source_url"),
                raw_payload=candidate,
            )
            observations += 1
    return {"room_type_rows_seen": room_types, "rate_observations_inserted": observations}


def import_multiplier_payload(cursor: Any, payload: dict[str, Any], competitor_hotel_id: str) -> dict[str, int]:
    room_types = 0
    observations = 0
    observed = 0
    estimated = 0

    for sample_key in ["weekday_sample", "weekend_sample"]:
        sample = payload.get(sample_key)
        if not sample:
            continue
        stay_date = sample["stay_date"]
        check_out = _next_day(stay_date)
        multipliers = sample.get("multipliers", {})
        for candidate in sample.get("room_rates", []):
            room_type_id = upsert_room_type(cursor, competitor_hotel_id, candidate["room_name"])
            room_types += 1
            raw_payload = {
                **candidate,
                "strategy": payload.get("strategy"),
                "sample_kind": sample_key,
                "day_type": sample.get("day_type"),
                "base_price": sample.get("base_price"),
                "multiplier": multipliers.get(candidate["room_name"]),
            }
            insert_rate_observation(
                cursor=cursor,
                room_type_id=room_type_id,
                stay_date=stay_date,
                check_out=check_out,
                price=candidate["price"],
                currency=candidate.get("currency") or "CNY",
                source="ctrip_rpa_observed",
                source_url=payload.get("source_url"),
                raw_payload=raw_payload,
            )
            observations += 1
            observed += 1

    for estimate in payload.get("estimated_room_rates", []):
        room_type_id = upsert_room_type(cursor, competitor_hotel_id, estimate["room_name"])
        room_types += 1
        stay_date = estimate["stay_date"]
        insert_rate_observation(
            cursor=cursor,
            room_type_id=room_type_id,
            stay_date=stay_date,
            check_out=_next_day(stay_date),
            price=estimate["estimated_price"],
            currency=estimate.get("currency") or "CNY",
            source="ctrip_rpa_estimated",
            source_url=payload.get("source_url"),
            raw_payload={**estimate, "strategy": payload.get("strategy")},
        )
        observations += 1
        estimated += 1

    return {
        "room_type_rows_seen": room_types,
        "rate_observations_inserted": observations,
        "observed_rate_observations_inserted": observed,
        "estimated_rate_observations_inserted": estimated,
    }


def insert_rate_observation(
    cursor: Any,
    room_type_id: int,
    stay_date: str,
    check_out: str,
    price: int,
    currency: str,
    source: str,
    source_url: str | None,
    raw_payload: dict[str, Any],
) -> None:
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
            price,
            currency,
            source,
            source_url,
            json.dumps(raw_payload, ensure_ascii=False),
        ),
    )


def _next_day(value: str) -> str:
    return (date.fromisoformat(value) + timedelta(days=1)).isoformat()


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
