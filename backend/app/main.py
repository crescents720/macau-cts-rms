import os
import math
import json
import re
from datetime import date, timedelta
from statistics import mean
from typing import Annotated
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.catalog import ROOM_TYPE_DATA
from app.event_calendar import event_premium_for_date
from app.external_events import external_event_premium_for_date


class Hotel(BaseModel):
    id: str
    name: str
    district: str


class RoomType(BaseModel):
    id: str
    hotel_id: str
    code: str
    source_id: int
    name: str
    base_rate: int


class PriceRecommendation(BaseModel):
    stay_date: date
    hotel_id: str
    room_type_id: str
    day_type: str
    base_rate_source: str
    current_rate: int
    recommended_rate: int
    historical_average_rate: float | None = None
    historical_comparison_date: date | None = None
    event_premium_rate: float = 0
    event_adjustment_amount: int = 0
    event_names: list[str] = []
    event_logic: list[str] = []
    change_percent: float
    confidence: float
    reasons: list[str]


class EventHotelImpact(BaseModel):
    hotel_id: str
    distance_km: float | None
    final_weight: float
    logic: str | None = None


class VenueRecord(BaseModel):
    id: str
    name: str
    district: str
    latitude: float
    longitude: float
    default_impact_radius_km: float


class ExternalEventRecord(BaseModel):
    id: int
    name: str
    event_type: str
    start_date: date
    end_date: date
    venue_id: str | None = None
    venue_name: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    confidence_score: float
    impact_level: str
    base_weight: float
    status: str
    notes: str | None = None
    hotel_impacts: list[EventHotelImpact] = []


class ExternalEventUpsert(BaseModel):
    name: str
    event_type: str = "other"
    start_date: date
    end_date: date
    venue_id: str | None = None
    source_name: str = "Manual"
    source_type: str = "manual"
    source_url: str | None = None
    confidence_score: float = 0.7
    impact_level: str = "medium"
    base_weight: float = 0.08
    status: str = "candidate"
    notes: str | None = None


class EventStatusUpdate(BaseModel):
    status: str


class EventCollectionRequest(BaseModel):
    source_name: str = "Manual Web List"
    source_url: str | None = None
    content: str | None = None


class EventCollectionCandidate(BaseModel):
    name: str
    event_type: str
    start_date: date
    end_date: date
    venue_id: str | None = None
    venue_name: str | None = None
    source_name: str
    source_url: str | None = None
    confidence_score: float
    impact_level: str
    base_weight: float
    notes: str | None = None


class EventCollectionImportRequest(BaseModel):
    candidates: list[EventCollectionCandidate]


class MgtoCollectionRequest(BaseModel):
    days: int = 90
    lang: str = "zh-hant"


app = FastAPI(
    title="Macau CTS Hotel RMS API",
    version="0.1.0",
    description="Prototype API for 90-day hotel pricing recommendations.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HOTELS = [
    Hotel(id="kyoto", name="京都酒店", district="澳门半岛"),
    Hotel(id="emperor", name="帝濠酒店", district="澳门半岛"),
    Hotel(id="riviera", name="濠璟酒店", district="西湾"),
    Hotel(id="beverly", name="富豪酒店", district="澳门半岛"),
]

ROOM_TYPES = [RoomType(**room_type) for room_type in ROOM_TYPE_DATA]

IMPACT_LEVEL_MULTIPLIERS = {
    "minor": 0.65,
    "medium": 1.0,
    "major": 1.25,
    "citywide": 1.45,
}

EVENT_TYPE_RULES = [
    ("grand_prix", ("大赛车", "格兰披治", "grand prix"), "citywide", 0.18),
    ("concert", ("演唱会", "音乐会", "concert", "巡演"), "major", 0.12),
    ("exhibition", ("展览", "展会", "博览", "会展", "expo"), "medium", 0.08),
    ("festival", ("节庆", "节日", "嘉年华", "festival"), "medium", 0.07),
    ("sports", ("赛事", "比赛", "锦标赛", "sports"), "medium", 0.07),
]

MGTO_WHATSON_API = "https://www.macaotourism.gov.mo/api/enf/whatson"
MGTO_EVENT_URL = "https://www.macaotourism.gov.mo/zh-hant/events/whatson/{event_id}"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/hotels", response_model=list[Hotel])
def list_hotels() -> list[Hotel]:
    return HOTELS


@app.get("/room-types", response_model=list[RoomType])
def list_room_types(hotel_id: str | None = None) -> list[RoomType]:
    if hotel_id is None:
        return ROOM_TYPES
    return [room_type for room_type in ROOM_TYPES if room_type.hotel_id == hotel_id]


@app.get("/venues", response_model=list[VenueRecord])
def list_venues() -> list[VenueRecord]:
    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, name, district, latitude, longitude, default_impact_radius_km
                    FROM venue_locations
                    ORDER BY district, name
                    """
                )
                rows = cursor.fetchall()
    except Exception:
        return []

    return [
        VenueRecord(
            id=row[0],
            name=row[1],
            district=row[2],
            latitude=float(row[3]),
            longitude=float(row[4]),
            default_impact_radius_km=float(row[5]),
        )
        for row in rows
    ]


@app.get("/external-events", response_model=list[ExternalEventRecord])
def list_external_events(status: str = "candidate") -> list[ExternalEventRecord]:
    if status == "all":
        status_filter = ""
        params = []
    else:
        status_filter = "WHERE e.status = %s"
        params = [status]

    query = f"""
        SELECT
            e.id,
            e.name,
            e.event_type,
            e.start_date,
            e.end_date,
            e.venue_id,
            v.name AS venue_name,
            s.name AS source_name,
            e.source_url,
            e.confidence_score,
            e.impact_level,
            e.base_weight,
            e.status,
            e.notes
        FROM external_events e
        LEFT JOIN venue_locations v ON v.id = e.venue_id
        LEFT JOIN external_event_sources s ON s.id = e.source_id
        {status_filter}
        ORDER BY e.start_date, e.id
    """

    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                events = cursor.fetchall()
                impacts = _event_impacts(cursor, [row[0] for row in events])
    except Exception:
        return []

    return [
        ExternalEventRecord(
            id=row[0],
            name=row[1],
            event_type=row[2],
            start_date=row[3],
            end_date=row[4],
            venue_id=row[5],
            venue_name=row[6],
            source_name=row[7],
            source_url=row[8],
            confidence_score=float(row[9]),
            impact_level=row[10],
            base_weight=float(row[11]),
            status=row[12],
            notes=row[13],
            hotel_impacts=impacts.get(row[0], []),
        )
        for row in events
    ]


@app.post("/external-events", response_model=ExternalEventRecord)
def create_external_event(event: ExternalEventUpsert) -> ExternalEventRecord:
    event_id = _save_external_event(event)
    saved_event = _load_external_event(event_id)
    if saved_event is None:
        raise HTTPException(status_code=500, detail="Created event could not be loaded")
    return saved_event


@app.put("/external-events/{event_id}", response_model=ExternalEventRecord)
def update_external_event(event_id: int, event: ExternalEventUpsert) -> ExternalEventRecord:
    if _load_external_event(event_id) is None:
        raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")
    _save_external_event(event, event_id=event_id)
    saved_event = _load_external_event(event_id)
    if saved_event is None:
        raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")
    return saved_event


@app.post("/event-collection/preview", response_model=list[EventCollectionCandidate])
def preview_event_collection(request: EventCollectionRequest) -> list[EventCollectionCandidate]:
    content = request.content or ""
    if request.source_url and not content.strip():
        content = _fetch_webpage_text(request.source_url)
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content or source URL is required")
    return _extract_event_candidates(
        content=content,
        source_name=request.source_name,
        source_url=request.source_url,
    )


@app.post("/event-collection/import", response_model=list[ExternalEventRecord])
def import_event_collection(request: EventCollectionImportRequest) -> list[ExternalEventRecord]:
    imported: list[ExternalEventRecord] = []
    for candidate in request.candidates:
        event_id = _save_external_event(
            ExternalEventUpsert(
                name=candidate.name,
                event_type=candidate.event_type,
                start_date=candidate.start_date,
                end_date=candidate.end_date,
                venue_id=candidate.venue_id,
                source_name=candidate.source_name,
                source_type="manual_web",
                source_url=candidate.source_url,
                confidence_score=candidate.confidence_score,
                impact_level=candidate.impact_level,
                base_weight=candidate.base_weight,
                status="candidate",
                notes=candidate.notes,
            )
        )
        saved_event = _load_external_event(event_id)
        if saved_event is not None:
            imported.append(saved_event)
    return imported


@app.post("/event-collection/mgto/preview", response_model=list[EventCollectionCandidate])
def preview_mgto_events(request: MgtoCollectionRequest) -> list[EventCollectionCandidate]:
    if request.days < 1 or request.days > 180:
        raise HTTPException(status_code=400, detail="Days must be between 1 and 180")
    return _fetch_mgto_event_candidates(days=request.days, lang=request.lang)


@app.post("/external-events/{event_id}/status", response_model=ExternalEventRecord)
def update_external_event_status(event_id: int, update: EventStatusUpdate) -> ExternalEventRecord:
    allowed_statuses = {"candidate", "confirmed", "rejected", "expired"}
    if update.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status: {update.status}")

    with _db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE external_events
                SET status = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (update.status, event_id),
            )
        conn.commit()

    event = next((item for item in list_external_events(status="all") if item.id == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")
    return event


@app.get("/recommendations", response_model=list[PriceRecommendation])
def list_recommendations(
    hotel_id: Annotated[str, Query()] = "kyoto",
    room_type_id: Annotated[str | None, Query()] = None,
    days: Annotated[int, Query(ge=1, le=180)] = 90,
) -> list[PriceRecommendation]:
    hotel_room_types = [candidate for candidate in ROOM_TYPES if candidate.hotel_id == hotel_id]
    room_type = next(
        (candidate for candidate in hotel_room_types if candidate.id == room_type_id),
        hotel_room_types[0] if hotel_room_types else None,
    )
    if room_type is None:
        return []

    today = date.today()
    stay_dates = [today + timedelta(days=offset) for offset in range(days)]
    base_rates = _historical_base_rates(
        hotel_id=hotel_id,
        room_type_code=room_type.code,
        target_year=today.year - 1,
    )
    historical_rates = _historical_average_rates(
        hotel_id=hotel_id,
        room_type_code=room_type.code,
        stay_dates=stay_dates,
    )
    recommendations = [
        _build_recommendation(
            stay_date=stay_date,
            room_type=room_type,
            historical_base_rates=base_rates,
            historical_average_rate=historical_rates.get(stay_date),
        )
        for stay_date in stay_dates
    ]
    return recommendations


def _event_impacts(cursor, event_ids: list[int]) -> dict[int, list[EventHotelImpact]]:
    if not event_ids:
        return {}

    placeholders = ", ".join(["%s"] * len(event_ids))
    cursor.execute(
        f"""
        SELECT event_id, hotel_id, distance_km, final_weight, logic
        FROM event_hotel_impacts
        WHERE event_id IN ({placeholders})
        ORDER BY hotel_id
        """,
        event_ids,
    )
    impacts: dict[int, list[EventHotelImpact]] = {}
    for event_id, hotel_id, distance_km, final_weight, logic in cursor.fetchall():
        impacts.setdefault(event_id, []).append(
            EventHotelImpact(
                hotel_id=hotel_id,
                distance_km=float(distance_km) if distance_km is not None else None,
                final_weight=float(final_weight),
                logic=logic,
            )
        )
    return impacts


def _load_external_event(event_id: int) -> ExternalEventRecord | None:
    events = list_external_events(status="all")
    return next((event for event in events if event.id == event_id), None)


def _save_external_event(event: ExternalEventUpsert, event_id: int | None = None) -> int:
    allowed_statuses = {"candidate", "confirmed", "rejected", "expired"}
    allowed_impact_levels = set(IMPACT_LEVEL_MULTIPLIERS)
    if event.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status: {event.status}")
    if event.impact_level not in allowed_impact_levels:
        raise HTTPException(status_code=400, detail=f"Invalid impact level: {event.impact_level}")
    if event.end_date < event.start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")
    if not 0 <= event.confidence_score <= 1:
        raise HTTPException(status_code=400, detail="Confidence score must be between 0 and 1")
    if not 0 <= event.base_weight <= 0.35:
        raise HTTPException(status_code=400, detail="Base weight must be between 0 and 0.35")

    with _db_connection() as conn:
        with conn.cursor() as cursor:
            if event.venue_id:
                cursor.execute("SELECT 1 FROM venue_locations WHERE id = %s", (event.venue_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=400, detail=f"Unknown venue: {event.venue_id}")

            source_id = _upsert_event_source(cursor, event)
            if event_id is None:
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
                    _event_values(event, source_id),
                )
                saved_event_id = int(cursor.fetchone()[0])
            else:
                cursor.execute(
                    """
                    UPDATE external_events
                    SET name = %s,
                        event_type = %s,
                        start_date = %s,
                        end_date = %s,
                        venue_id = %s,
                        source_id = %s,
                        source_url = %s,
                        confidence_score = %s,
                        impact_level = %s,
                        base_weight = %s,
                        status = %s,
                        notes = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (*_event_values(event, source_id), event_id),
                )
                saved_event_id = event_id

            _rebuild_event_impacts(cursor, saved_event_id, event)
        conn.commit()

    return saved_event_id


def _event_values(event: ExternalEventUpsert, source_id: int) -> tuple:
    return (
        event.name.strip(),
        event.event_type,
        event.start_date,
        event.end_date,
        event.venue_id or None,
        source_id,
        event.source_url or None,
        event.confidence_score,
        event.impact_level,
        event.base_weight,
        event.status,
        event.notes or None,
    )


def _upsert_event_source(cursor, event: ExternalEventUpsert) -> int:
    cursor.execute(
        """
        INSERT INTO external_event_sources (name, source_type, base_url, trust_score)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (name, source_type, (COALESCE(base_url, ''))) DO UPDATE
        SET trust_score = EXCLUDED.trust_score
        RETURNING id
        """,
        (
            event.source_name or "Manual",
            event.source_type or "manual",
            event.source_url or None,
            event.confidence_score,
        ),
    )
    return int(cursor.fetchone()[0])


def _rebuild_event_impacts(cursor, event_id: int, event: ExternalEventUpsert) -> None:
    cursor.execute("DELETE FROM event_hotel_impacts WHERE event_id = %s", (event_id,))
    hotels = _load_location_map(cursor, "hotel_locations", "hotel_id")
    venues = _load_location_map(cursor, "venue_locations", "id")
    venue = venues.get(event.venue_id or "")
    multiplier = IMPACT_LEVEL_MULTIPLIERS.get(event.impact_level, 1.0)

    for hotel_id, hotel in hotels.items():
        if venue:
            distance_km = _haversine_km(
                hotel["latitude"],
                hotel["longitude"],
                venue["latitude"],
                venue["longitude"],
            )
            radius_km = venue.get("default_impact_radius_km", 8)
            distance_factor = _distance_factor(distance_km, radius_km)
        else:
            distance_km = None
            distance_factor = 0.35

        final_weight = min(event.base_weight * multiplier * distance_factor, 0.35)
        logic = f"base {event.base_weight:.1%} × level {multiplier:.2f} × distance {distance_factor:.2f}"
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
                round(distance_km, 3) if distance_km is not None else None,
                round(distance_factor, 4),
                round(final_weight, 4),
                logic,
            ),
        )


def _load_location_map(cursor, table: str, id_column: str) -> dict[str, dict[str, float]]:
    extra_column = ", default_impact_radius_km" if table == "venue_locations" else ""
    cursor.execute(f"SELECT {id_column}, latitude, longitude{extra_column} FROM {table}")
    locations: dict[str, dict[str, float]] = {}
    for row in cursor.fetchall():
        location = {
            "latitude": float(row[1]),
            "longitude": float(row[2]),
        }
        if table == "venue_locations":
            location["default_impact_radius_km"] = float(row[3])
        locations[str(row[0])] = location
    return locations


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


def _distance_factor(distance_km: float, radius_km: float) -> float:
    if distance_km <= 1:
        return 1.0
    if distance_km <= 3:
        return 0.75
    if distance_km <= radius_km:
        return 0.5
    if distance_km <= radius_km + 4:
        return 0.25
    return 0.12


def _fetch_webpage_text(url: str) -> str:
    try:
        request = Request(url, headers={"User-Agent": "Macau-CTS-RMS/0.1"})
        with urlopen(request, timeout=12) as response:
            raw = response.read(1_000_000)
            content_type = response.headers.get_content_charset() or "utf-8"
    except (URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Unable to fetch source URL: {exc}") from exc

    html = raw.decode(content_type, errors="ignore")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    return re.sub(r"\n{2,}", "\n", text)


def _extract_event_candidates(
    content: str,
    source_name: str,
    source_url: str | None,
) -> list[EventCollectionCandidate]:
    venues = _venue_lookup()
    candidates: list[EventCollectionCandidate] = []
    seen: set[tuple[str, date, date, str | None]] = set()

    for line in _candidate_lines(content):
        date_range = _extract_date_range(line)
        if date_range is None:
            continue
        event_type, impact_level, base_weight = _classify_event(line)
        venue_id, venue_name = _match_venue(line, venues)
        name = _clean_event_name(line)
        confidence = 0.45 + (0.2 if venue_id else 0) + (0.2 if event_type != "other" else 0)
        confidence = min(confidence, 0.92)
        key = (name, date_range[0], date_range[1], venue_id)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            EventCollectionCandidate(
                name=name,
                event_type=event_type,
                start_date=date_range[0],
                end_date=date_range[1],
                venue_id=venue_id,
                venue_name=venue_name,
                source_name=source_name or "Manual Web List",
                source_url=source_url,
                confidence_score=round(confidence, 2),
                impact_level=impact_level,
                base_weight=base_weight,
                notes=f"由采集文本自动识别: {line[:180]}",
            )
        )
    return candidates[:30]


def _fetch_mgto_event_candidates(days: int, lang: str) -> list[EventCollectionCandidate]:
    start = date.today()
    end = start + timedelta(days=days)
    candidates: list[EventCollectionCandidate] = []
    seen_ids: set[str] = set()

    for month in _months_between(start, end):
        payload = _fetch_json(
            MGTO_WHATSON_API,
            {"lang": lang, "m": month.strftime("%Y%m")},
        )
        for item in payload.get("results", []):
            event_id = str(item.get("id") or "")
            if not event_id or event_id in seen_ids:
                continue
            seen_ids.add(event_id)
            candidate = _mgto_item_to_candidate(item, start, end)
            if candidate is not None:
                candidates.append(candidate)

    candidates.sort(key=lambda candidate: (candidate.start_date, candidate.name))
    return candidates[:120]


def _mgto_item_to_candidate(
    item: dict,
    window_start: date,
    window_end: date,
) -> EventCollectionCandidate | None:
    date_ranges = item.get("eventDateRange") or []
    if date_ranges:
        parsed_ranges = [
            (date.fromisoformat(row[0]), date.fromisoformat(row[1]))
            for row in date_ranges
            if len(row) >= 2
        ]
    elif item.get("eventDate") and "~" in str(item["eventDate"]):
        start_value, end_value = str(item["eventDate"]).split("~", 1)
        parsed_ranges = [(date.fromisoformat(start_value), date.fromisoformat(end_value))]
    elif item.get("eventDate"):
        event_date = date.fromisoformat(str(item["eventDate"]))
        parsed_ranges = [(event_date, event_date)]
    else:
        return None

    overlapping_ranges = [
        row for row in parsed_ranges if row[1] >= window_start and row[0] <= window_end
    ]
    if not overlapping_ranges:
        return None

    start_date = min(row[0] for row in overlapping_ranges)
    end_date = max(row[1] for row in overlapping_ranges)
    name = str(item.get("name") or "").strip()
    if not name:
        return None

    location_names = [
        str(location.get("name") or "")
        for location in item.get("location", [])
        if isinstance(location, dict)
    ]
    combined_text = " ".join(
        [
            name,
            str(item.get("shortDesc") or ""),
            " ".join(location_names),
            " ".join(type_item.get("name", "") for type_item in item.get("types", [])),
        ]
    )
    event_type, impact_level, base_weight = _classify_mgto_event(item, combined_text)
    venue_id, venue_name = _match_venue(combined_text, _venue_lookup())
    confidence = 0.86 if venue_id else 0.72
    event_id = str(item.get("id") or "")
    source_url = MGTO_EVENT_URL.format(event_id=event_id) if event_id else MGTO_WHATSON_API

    return EventCollectionCandidate(
        name=name,
        event_type=event_type,
        start_date=start_date,
        end_date=end_date,
        venue_id=venue_id,
        venue_name=venue_name,
        source_name="澳門旅遊局旅遊快訊",
        source_url=source_url,
        confidence_score=confidence,
        impact_level=impact_level,
        base_weight=base_weight,
        notes=f"官方旅遊快訊自動采集；原始日期: {item.get('showDate') or item.get('eventDate')}",
    )


def _classify_mgto_event(item: dict, text: str) -> tuple[str, str, float]:
    type_names = {str(type_item.get("name") or "") for type_item in item.get("types", [])}
    if "體育" in type_names or "Sports" in type_names:
        return "sports", "major", 0.1
    if "表演" in type_names or "Performances" in type_names:
        return "concert", "major", 0.12
    if "展覽" in type_names or "Exhibitions" in type_names:
        return "exhibition", "medium", 0.07
    if "節日盛事" in type_names or "Events & Festivals" in type_names:
        return "festival", "medium", 0.08
    return _classify_event(text)


def _months_between(start: date, end: date) -> list[date]:
    months = []
    current = date(start.year, start.month, 1)
    final = date(end.year, end.month, 1)
    while current <= final:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def _fetch_json(url: str, params: dict[str, str]) -> dict:
    target = f"{url}?{urlencode(params)}"
    try:
        request = Request(target, headers={"User-Agent": "Macau-CTS-RMS/0.1", "Accept": "application/json"})
        with urlopen(request, timeout=18) as response:
            return json.loads(response.read().decode("utf-8", errors="ignore"))
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Unable to fetch MGTO event source: {exc}") from exc


def _candidate_lines(content: str) -> list[str]:
    lines = []
    for raw_line in re.split(r"[\n\r]+", content):
        line = re.sub(r"\s+", " ", raw_line).strip(" -—\t")
        if 8 <= len(line) <= 240 and re.search(r"\d{1,4}[年./-]\d{1,2}|月\d{1,2}日|\d{1,2}月\d{1,2}", line):
            lines.append(line)
    return lines


def _extract_date_range(line: str) -> tuple[date, date] | None:
    today = date.today()
    year_match = re.search(r"(20\d{2})\s*年", line)
    default_year = int(year_match.group(1)) if year_match else today.year
    range_match = re.search(
        r"(?:(20\d{2})[年./-])?(\d{1,2})[月./-](\d{1,2})日?\s*(?:至|到|-|—|~)\s*(?:(20\d{2})[年./-])?(\d{1,2})[月./-](\d{1,2})日?",
        line,
    )
    if range_match:
        start_year = int(range_match.group(1) or default_year)
        end_year = int(range_match.group(4) or start_year)
        try:
            return (
                date(start_year, int(range_match.group(2)), int(range_match.group(3))),
                date(end_year, int(range_match.group(5)), int(range_match.group(6))),
            )
        except ValueError:
            return None

    single_match = re.search(
        r"(?:(20\d{2})[年./-])?(\d{1,2})[月./-](\d{1,2})日?",
        line,
    )
    if not single_match:
        return None
    event_year = int(single_match.group(1) or default_year)
    try:
        event_date = date(event_year, int(single_match.group(2)), int(single_match.group(3)))
    except ValueError:
        return None
    return event_date, event_date


def _classify_event(line: str) -> tuple[str, str, float]:
    normalized = line.lower()
    for event_type, keywords, impact_level, base_weight in EVENT_TYPE_RULES:
        if any(keyword in normalized for keyword in keywords):
            return event_type, impact_level, base_weight
    return "other", "medium", 0.05


def _venue_lookup() -> dict[str, dict[str, str]]:
    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, name FROM venue_locations")
                rows = cursor.fetchall()
    except Exception:
        rows = []

    aliases = {
        "galaxy-arena": ["银河综艺馆", "银河", "galaxy arena"],
        "venetian-arena": ["威尼斯人综艺馆", "威尼斯人", "venetian"],
        "studio-city-event-center": ["新濠影汇综艺馆", "新濠影汇", "studio city"],
        "guia-circuit": ["东望洋赛道", "格兰披治", "大赛车", "guia circuit"],
        "macau-tower": ["澳门旅游塔", "旅游塔", "macau tower"],
        "tap-seac-square": ["塔石广场", "塔石", "tap seac"],
    }
    lookup = {}
    for venue_id, name in rows:
        names = [name, *aliases.get(str(venue_id), [])]
        lookup[str(venue_id)] = {"name": name, "aliases": "|".join(names)}
    return lookup


def _match_venue(line: str, venues: dict[str, dict[str, str]]) -> tuple[str | None, str | None]:
    normalized = line.lower()
    for venue_id, venue in venues.items():
        aliases = venue["aliases"].split("|")
        if any(alias and alias.lower() in normalized for alias in aliases):
            return venue_id, venue["name"]
    return None, None


def _clean_event_name(line: str) -> str:
    cleaned = re.sub(r"(?:(20\d{2})[年./-])?\d{1,2}[月./-]\d{1,2}日?", " ", line)
    cleaned = re.sub(r"\s*(至|到|-|—|~)\s*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ：:，,。-—")
    return cleaned[:80] or line[:80]


def _build_recommendation(
    stay_date: date,
    room_type: RoomType,
    historical_base_rates: dict[str, float],
    historical_average_rate: float | None = None,
) -> PriceRecommendation:
    weekday = stay_date.weekday()
    is_weekend = weekday in {4, 5}
    day_type = "weekend" if is_weekend else "weekday"
    dynamic_base_rate = historical_base_rates.get(day_type)
    base_rate_source = (
        f"上一年度{'周末' if is_weekend else '周中'}同房型平均房价"
        if dynamic_base_rate is not None
        else "房型目录临时基础价"
    )
    base_rate = _round_rate(dynamic_base_rate) if dynamic_base_rate is not None else room_type.base_rate
    is_holiday_window = (stay_date.month, stay_date.day) in {
        (1, 1),
        (5, 1),
        (10, 1),
        (12, 24),
        (12, 25),
        (12, 31),
    }

    demand_factors = [
        1.25 if is_holiday_window else 1.0,
        1.06 if stay_date.day in {8, 18, 28} else 1.0,
    ]
    demand_multiplier = mean(demand_factors)
    calendar_premium_rate, events, event_logic = event_premium_for_date(stay_date)
    external_premium_rate, external_events, external_logic = external_event_premium_for_date(
        hotel_id=room_type.hotel_id,
        stay_date=stay_date,
    )
    event_premium_rate = min(calendar_premium_rate + external_premium_rate, 0.5)
    combined_event_logic = [*event_logic, *external_logic]
    rate_before_events = base_rate * demand_multiplier
    event_adjustment_amount = _round_rate(rate_before_events * event_premium_rate)
    recommended_rate = _round_rate(rate_before_events + event_adjustment_amount)
    change_percent = round(
        ((recommended_rate - base_rate) / base_rate) * 100,
        1,
    )

    reasons = []
    if is_weekend:
        reasons.append("周末日期，基础房价采用上一年度周末同房型均价")
    else:
        reasons.append("周中日期，基础房价采用上一年度周中同房型均价")
    if is_holiday_window:
        reasons.append("节假日窗口期需求上升")
    if stay_date.day in {8, 18, 28}:
        reasons.append("历史上旬末/下旬末到访需求偏高")
    if events or external_events:
        event_names = [
            *[f"{event.region}{event.name}" for event in events],
            *[event.name for event in external_events],
        ]
        reasons.append(
            "事件溢价: "
            + "；".join(event_names)
            + f"，上调{event_premium_rate:.1%}"
        )
    if not reasons:
        reasons.append("维持基础价格，等待更多市场数据")

    confidence = (
        0.62
        + (0.08 if is_weekend else 0)
        + (0.1 if is_holiday_window else 0)
        + (0.04 if events else 0)
    )

    return PriceRecommendation(
        stay_date=stay_date,
        hotel_id=room_type.hotel_id,
        room_type_id=room_type.id,
        day_type=day_type,
        base_rate_source=base_rate_source,
        current_rate=base_rate,
        recommended_rate=recommended_rate,
        historical_average_rate=historical_average_rate,
        historical_comparison_date=_previous_year_date(stay_date)
        if historical_average_rate is not None
        else None,
        event_premium_rate=round(event_premium_rate, 4),
        event_adjustment_amount=event_adjustment_amount,
        event_names=[
            *[f"{event.region}{event.name}" for event in events],
            *[event.name for event in external_events],
        ],
        event_logic=combined_event_logic,
        change_percent=change_percent,
        confidence=round(min(confidence, 0.86), 2),
        reasons=reasons,
    )


def _round_rate(rate: float) -> int:
    return int(round(rate / 10) * 10)


def _db_connection():
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://hotel_rms:hotel_rms_dev@localhost:5432/hotel_rms",
    )
    return psycopg.connect(database_url)


def _historical_average_rates(
    hotel_id: str,
    room_type_code: str,
    stay_dates: list[date],
) -> dict[date, float]:
    comparison_dates = [_previous_year_date(stay_date) for stay_date in stay_dates]
    if not comparison_dates:
        return {}

    placeholders = ", ".join(["%s"] * len(comparison_dates))
    query = f"""
        SELECT arrival_date, ROUND(AVG(room_rate)::numeric, 2) AS average_rate
        FROM hotel_orders
        WHERE hotel_id = %s
          AND (room_type = %s OR charged_room_type = %s)
          AND arrival_date IN ({placeholders})
          AND room_rate IS NOT NULL
        GROUP BY arrival_date
    """
    params = [hotel_id, room_type_code, room_type_code, *comparison_dates]

    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
    except Exception:
        return {}

    rates_by_comparison_date = {
        row[0]: float(row[1]) for row in rows if row[0] is not None and row[1] is not None
    }
    return {
        stay_date: rates_by_comparison_date[comparison_date]
        for stay_date, comparison_date in zip(stay_dates, comparison_dates)
        if comparison_date in rates_by_comparison_date
    }


def _historical_base_rates(
    hotel_id: str,
    room_type_code: str,
    target_year: int,
) -> dict[str, float]:
    query = """
        SELECT
            CASE
                WHEN EXTRACT(ISODOW FROM arrival_date) IN (5, 6) THEN 'weekend'
                ELSE 'weekday'
            END AS day_type,
            ROUND(AVG(room_rate)::numeric, 2) AS average_rate
        FROM hotel_orders
        WHERE hotel_id = %s
          AND (room_type = %s OR charged_room_type = %s)
          AND EXTRACT(YEAR FROM arrival_date) = %s
          AND room_rate IS NOT NULL
        GROUP BY day_type
    """
    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (hotel_id, room_type_code, room_type_code, target_year))
                rows = cursor.fetchall()
    except Exception:
        return {}

    return {str(day_type): float(average_rate) for day_type, average_rate in rows}


def _previous_year_date(stay_date: date) -> date:
    try:
        return stay_date.replace(year=stay_date.year - 1)
    except ValueError:
        return stay_date.replace(year=stay_date.year - 1, day=28)
