from __future__ import annotations

import argparse
import csv
import math
import os
from datetime import date
from pathlib import Path
from typing import Any

import psycopg


IMPACT_LEVEL_MULTIPLIERS = {
    "minor": 0.65,
    "medium": 1.0,
    "major": 1.25,
    "citywide": 1.45,
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def distance_factor(distance_km: float, radius_km: float) -> float:
    if distance_km <= 1:
        return 1.0
    if distance_km <= 3:
        return 0.75
    if distance_km <= radius_km:
        return 0.5
    if distance_km <= radius_km + 4:
        return 0.25
    return 0.12


def parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).resolve().parents[2] / "data" / "sample_external_events.csv"),
    )
    args = parser.parse_args()

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://hotel_rms:hotel_rms_dev@localhost:5432/hotel_rms",
    )
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            import_events(cursor, Path(args.csv))
        conn.commit()


def import_events(cursor: Any, csv_path: Path) -> None:
    hotels = load_locations(cursor, "hotel_locations", "hotel_id")
    venues = load_locations(cursor, "venue_locations", "id")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            source_id = upsert_source(cursor, row)
            event_id = upsert_event(cursor, row, source_id)
            rebuild_impacts(cursor, event_id, row, hotels, venues)
            print(f"Imported event {event_id}: {row['name']}")


def load_locations(cursor: Any, table: str, id_column: str) -> dict[str, dict[str, Any]]:
    cursor.execute(f"SELECT {id_column}, latitude, longitude FROM {table}")
    return {
        str(row[0]): {"latitude": float(row[1]), "longitude": float(row[2])}
        for row in cursor.fetchall()
    }


def upsert_source(cursor: Any, row: dict[str, str]) -> int:
    cursor.execute(
        """
        INSERT INTO external_event_sources (name, source_type, base_url, trust_score)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (name, source_type, (COALESCE(base_url, ''))) DO UPDATE
        SET trust_score = EXCLUDED.trust_score
        RETURNING id
        """,
        (
            row.get("source_name") or "Manual",
            row.get("source_type") or "manual",
            row.get("source_url") or None,
            float(row.get("confidence_score") or 0.7),
        ),
    )
    return int(cursor.fetchone()[0])


def upsert_event(cursor: Any, row: dict[str, str], source_id: int) -> int:
    cursor.execute(
        """
        INSERT INTO external_events (
            name, event_type, start_date, end_date, venue_id, source_id, source_url,
            confidence_score, impact_level, base_weight, status, notes
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (name, start_date, end_date, (COALESCE(venue_id, ''))) DO UPDATE
        SET event_type = EXCLUDED.event_type,
            source_id = EXCLUDED.source_id,
            source_url = EXCLUDED.source_url,
            confidence_score = EXCLUDED.confidence_score,
            impact_level = EXCLUDED.impact_level,
            base_weight = EXCLUDED.base_weight,
            status = EXCLUDED.status,
            notes = EXCLUDED.notes,
            updated_at = now()
        RETURNING id
        """,
        (
            row["name"],
            row.get("event_type") or "other",
            parse_date(row["start_date"]),
            parse_date(row["end_date"]),
            row.get("venue_id") or None,
            source_id,
            row.get("source_url") or None,
            float(row.get("confidence_score") or 0.7),
            row.get("impact_level") or "medium",
            float(row.get("base_weight") or 0.08),
            row.get("status") or "candidate",
            row.get("notes") or None,
        ),
    )
    return int(cursor.fetchone()[0])


def rebuild_impacts(
    cursor: Any,
    event_id: int,
    row: dict[str, str],
    hotels: dict[str, dict[str, Any]],
    venues: dict[str, dict[str, Any]],
) -> None:
    cursor.execute("DELETE FROM event_hotel_impacts WHERE event_id = %s", (event_id,))
    venue = venues.get(row.get("venue_id", ""))
    base_weight = float(row.get("base_weight") or 0.08)
    impact_level = row.get("impact_level") or "medium"
    multiplier = IMPACT_LEVEL_MULTIPLIERS.get(impact_level, 1.0)

    for hotel_id, hotel in hotels.items():
        if venue:
            dist = haversine_km(
                hotel["latitude"],
                hotel["longitude"],
                venue["latitude"],
                venue["longitude"],
            )
            factor = distance_factor(dist, radius_km=8)
        else:
            dist = None
            factor = 0.35

        final_weight = min(base_weight * multiplier * factor, 0.35)
        logic = (
            f"base {base_weight:.1%} × level {multiplier:.2f} × distance {factor:.2f}"
        )
        cursor.execute(
            """
            INSERT INTO event_hotel_impacts (
                event_id, hotel_id, distance_km, distance_factor, final_weight, logic
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                event_id,
                hotel_id,
                round(dist, 3) if dist is not None else None,
                factor,
                round(final_weight, 4),
                logic,
            ),
        )


if __name__ == "__main__":
    main()
