from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import psycopg


@dataclass(frozen=True)
class ExternalPricingEvent:
    name: str
    event_type: str
    venue_name: str | None
    impact_level: str
    weight: float
    confidence_score: float
    logic: str


def external_event_premium_for_date(
    hotel_id: str,
    stay_date: date,
) -> tuple[float, list[ExternalPricingEvent], list[str]]:
    query = """
        SELECT
            e.name,
            e.event_type,
            v.name AS venue_name,
            e.impact_level,
            i.final_weight,
            e.confidence_score,
            i.logic
        FROM external_events e
        JOIN event_hotel_impacts i ON i.event_id = e.id
        LEFT JOIN venue_locations v ON v.id = e.venue_id
        WHERE e.status = 'confirmed'
          AND i.hotel_id = %s
          AND %s BETWEEN e.start_date AND e.end_date
        ORDER BY i.final_weight DESC, e.confidence_score DESC
    """
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://hotel_rms:hotel_rms_dev@localhost:5432/hotel_rms",
    )
    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (hotel_id, stay_date))
                rows = cursor.fetchall()
    except Exception:
        return 0.0, [], []

    events = [
        ExternalPricingEvent(
            name=str(name),
            event_type=str(event_type),
            venue_name=str(venue_name) if venue_name else None,
            impact_level=str(impact_level),
            weight=float(weight),
            confidence_score=float(confidence_score),
            logic=str(logic) if logic else "",
        )
        for name, event_type, venue_name, impact_level, weight, confidence_score, logic in rows
    ]
    premium = min(sum(event.weight for event in events), 0.35)
    logic = [
        f"{event.name}"
        + (f" @ {event.venue_name}" if event.venue_name else "")
        + f": {event.impact_level} impact, confidence {event.confidence_score:.0%}, hotel weight {event.weight:.1%}"
        for event in events
    ]
    if sum(event.weight for event in events) > premium:
        logic.append(f"External event premium capped at {premium:.1%}")
    return premium, events, logic
