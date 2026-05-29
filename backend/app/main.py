import os
import math
import json
import re
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Annotated
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen

import psycopg
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
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
    competitor_market_rate: float | None = None
    competitor_average_rate: float | None = None
    competitor_min_rate: float | None = None
    competitor_max_rate: float | None = None
    competitor_adjustment_amount: int = 0
    competitor_logic: list[str] = []
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


class CompetitorHotelRecord(BaseModel):
    id: str
    name: str
    district: str
    ctrip_hotel_id: str | None = None
    ctrip_url: str | None = None
    active: bool = True
    room_type_count: int = 0


class CompetitorRoomTypeRecord(BaseModel):
    id: int
    competitor_hotel_id: str
    competitor_hotel_name: str
    name: str
    ctrip_room_id: str | None = None
    normalized_name: str | None = None
    active: bool = True


class CompetitorRoomTypeCreate(BaseModel):
    competitor_hotel_id: str
    name: str
    ctrip_room_id: str | None = None
    normalized_name: str | None = None


class CompetitorMappingRecord(BaseModel):
    id: int
    hotel_id: str
    room_type_id: str
    room_type_name: str
    competitor_room_type_id: int
    competitor_hotel_id: str
    competitor_hotel_name: str
    competitor_room_type_name: str
    priority: int
    weight: float
    notes: str | None = None


class CompetitorMappingCreate(BaseModel):
    hotel_id: str
    room_type_id: str
    competitor_room_type_id: int
    priority: int = 1
    weight: float = 1
    notes: str | None = None


class CompetitorRateObservationRecord(BaseModel):
    id: int
    competitor_room_type_id: int
    competitor_hotel_name: str
    competitor_room_type_name: str
    stay_date: date
    check_in: date
    check_out: date
    price: float
    currency: str
    source: str
    source_url: str | None = None
    collected_at: str


class CompetitorRateObservationCreate(BaseModel):
    competitor_room_type_id: int
    stay_date: date
    price: float
    currency: str = "CNY"
    source: str = "manual"
    source_url: str | None = None


class CtripCollectionRequest(BaseModel):
    hotel_ids: list[str] | None = None
    calendar_days: int = 90
    skip_import: bool = False
    timeout_seconds: int = 3600


class CtripCollectionJobRecord(BaseModel):
    id: str
    status: str
    started_at: str
    finished_at: str | None = None
    hotel_ids: list[str] | None = None
    calendar_days: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    exit_code: int | None = None


app = FastAPI(
    title="Macau CTS Hotel RMS API",
    version="0.1.0",
    description="Prototype API for 90-day hotel pricing recommendations.",
)

CTRIP_COLLECTION_JOBS: dict[str, CtripCollectionJobRecord] = {}

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


@app.get("/competitors/hotels", response_model=list[CompetitorHotelRecord])
def list_competitor_hotels() -> list[CompetitorHotelRecord]:
    query = """
        SELECT h.id, h.name, h.district, h.ctrip_hotel_id, h.ctrip_url, h.active,
               COUNT(r.id) AS room_type_count
        FROM competitor_hotels h
        LEFT JOIN competitor_room_types r ON r.competitor_hotel_id = h.id AND r.active = TRUE
        GROUP BY h.id, h.name, h.district, h.ctrip_hotel_id, h.ctrip_url, h.active
        ORDER BY h.name
    """
    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
    except Exception:
        return []

    return [
        CompetitorHotelRecord(
            id=row[0],
            name=row[1],
            district=row[2],
            ctrip_hotel_id=row[3],
            ctrip_url=row[4],
            active=bool(row[5]),
            room_type_count=int(row[6]),
        )
        for row in rows
    ]


@app.get("/competitors/room-types", response_model=list[CompetitorRoomTypeRecord])
def list_competitor_room_types(
    competitor_hotel_id: str | None = None,
) -> list[CompetitorRoomTypeRecord]:
    params = []
    where_clause = "WHERE r.active = TRUE"
    if competitor_hotel_id:
        where_clause += " AND r.competitor_hotel_id = %s"
        params.append(competitor_hotel_id)

    query = f"""
        SELECT r.id, r.competitor_hotel_id, h.name AS competitor_hotel_name,
               r.name, r.ctrip_room_id, r.normalized_name, r.active
        FROM competitor_room_types r
        JOIN competitor_hotels h ON h.id = r.competitor_hotel_id
        {where_clause}
        ORDER BY h.name, r.name
    """
    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
    except Exception:
        return []

    return [
        CompetitorRoomTypeRecord(
            id=int(row[0]),
            competitor_hotel_id=row[1],
            competitor_hotel_name=row[2],
            name=row[3],
            ctrip_room_id=row[4],
            normalized_name=row[5],
            active=bool(row[6]),
        )
        for row in rows
    ]


@app.post("/competitors/room-types", response_model=CompetitorRoomTypeRecord)
def create_competitor_room_type(room_type: CompetitorRoomTypeCreate) -> CompetitorRoomTypeRecord:
    with _db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM competitor_hotels WHERE id = %s", (room_type.competitor_hotel_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=400, detail="Unknown competitor hotel")
            cursor.execute(
                """
                INSERT INTO competitor_room_types (
                    competitor_hotel_id, name, ctrip_room_id, normalized_name
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (competitor_hotel_id, name) DO UPDATE
                SET ctrip_room_id = EXCLUDED.ctrip_room_id,
                    normalized_name = EXCLUDED.normalized_name,
                    active = TRUE,
                    last_seen_at = now()
                RETURNING id
                """,
                (
                    room_type.competitor_hotel_id,
                    room_type.name.strip(),
                    room_type.ctrip_room_id or None,
                    room_type.normalized_name or room_type.name.strip(),
                ),
            )
            room_type_id = int(cursor.fetchone()[0])
        conn.commit()

    created = next(
        item for item in list_competitor_room_types(room_type.competitor_hotel_id)
        if item.id == room_type_id
    )
    return created


@app.delete("/competitors/room-types/{room_type_id}")
def delete_competitor_room_type(room_type_id: int) -> dict[str, str]:
    with _db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM room_type_competitor_mappings WHERE competitor_room_type_id = %s",
                (room_type_id,),
            )
            cursor.execute(
                """
                UPDATE competitor_room_types
                SET active = FALSE,
                    last_seen_at = now()
                WHERE id = %s
                """,
                (room_type_id,),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Competitor room type not found")
        conn.commit()
    return {"status": "deleted"}


@app.get("/competitors/mappings", response_model=list[CompetitorMappingRecord])
def list_competitor_mappings(
    hotel_id: str | None = None,
    room_type_id: str | None = None,
) -> list[CompetitorMappingRecord]:
    params = []
    where_clause = ""
    if hotel_id:
        where_clause = "WHERE m.hotel_id = %s"
        params.append(hotel_id)
    if room_type_id:
        where_clause += " AND " if where_clause else "WHERE "
        where_clause += "m.room_type_id = %s"
        params.append(room_type_id)

    query = f"""
        SELECT m.id, m.hotel_id, m.room_type_id, r.competitor_hotel_id,
               h.name AS competitor_hotel_name, r.id AS competitor_room_type_id,
               r.name AS competitor_room_type_name, m.priority, m.weight, m.notes
        FROM room_type_competitor_mappings m
        JOIN competitor_room_types r ON r.id = m.competitor_room_type_id
        JOIN competitor_hotels h ON h.id = r.competitor_hotel_id
        {where_clause}
        ORDER BY m.hotel_id, m.room_type_id, m.priority, h.name
    """
    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
    except Exception:
        return []

    room_names = {room.id: room.name for room in ROOM_TYPES}
    return [
        CompetitorMappingRecord(
            id=int(row[0]),
            hotel_id=row[1],
            room_type_id=row[2],
            room_type_name=room_names.get(row[2], row[2]),
            competitor_hotel_id=row[3],
            competitor_hotel_name=row[4],
            competitor_room_type_id=int(row[5]),
            competitor_room_type_name=row[6],
            priority=int(row[7]),
            weight=float(row[8]),
            notes=row[9],
        )
        for row in rows
    ]


@app.post("/competitors/mappings", response_model=CompetitorMappingRecord)
def create_competitor_mapping(mapping: CompetitorMappingCreate) -> CompetitorMappingRecord:
    if not any(room.id == mapping.room_type_id and room.hotel_id == mapping.hotel_id for room in ROOM_TYPES):
        raise HTTPException(status_code=400, detail="Unknown local room type")
    with _db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO room_type_competitor_mappings (
                    hotel_id, room_type_id, competitor_room_type_id, priority, weight, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (hotel_id, room_type_id, competitor_room_type_id) DO UPDATE
                SET priority = EXCLUDED.priority,
                    weight = EXCLUDED.weight,
                    notes = EXCLUDED.notes
                RETURNING id
                """,
                (
                    mapping.hotel_id,
                    mapping.room_type_id,
                    mapping.competitor_room_type_id,
                    mapping.priority,
                    mapping.weight,
                    mapping.notes,
                ),
            )
            mapping_id = int(cursor.fetchone()[0])
        conn.commit()

    created = next(item for item in list_competitor_mappings() if item.id == mapping_id)
    return created


@app.delete("/competitors/mappings/{mapping_id}")
def delete_competitor_mapping(mapping_id: int) -> dict[str, str]:
    with _db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM room_type_competitor_mappings WHERE id = %s", (mapping_id,))
        conn.commit()
    return {"status": "deleted"}


@app.get("/competitors/rates", response_model=list[CompetitorRateObservationRecord])
def list_competitor_rates(
    room_type_id: str | None = None,
    days: Annotated[int, Query(ge=1, le=180)] = 90,
) -> list[CompetitorRateObservationRecord]:
    params: list = [date.today(), date.today() + timedelta(days=days)]
    mapping_join = ""
    where_extra = ""
    if room_type_id:
        mapping_join = """
            JOIN room_type_competitor_mappings m
              ON m.competitor_room_type_id = o.competitor_room_type_id
        """
        where_extra = "AND m.room_type_id = %s"
        params.append(room_type_id)

    query = f"""
        SELECT o.id, o.competitor_room_type_id, h.name, r.name, o.stay_date,
               o.check_in, o.check_out, o.price, o.currency, o.source, o.source_url,
               o.collected_at::text
        FROM competitor_rate_observations o
        JOIN competitor_room_types r ON r.id = o.competitor_room_type_id
        JOIN competitor_hotels h ON h.id = r.competitor_hotel_id
        {mapping_join}
        WHERE o.stay_date BETWEEN %s AND %s
          {where_extra}
        ORDER BY o.stay_date, h.name, r.name, o.collected_at DESC
        LIMIT 300
    """
    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
    except Exception:
        return []

    return [
        CompetitorRateObservationRecord(
            id=int(row[0]),
            competitor_room_type_id=int(row[1]),
            competitor_hotel_name=row[2],
            competitor_room_type_name=row[3],
            stay_date=row[4],
            check_in=row[5],
            check_out=row[6],
            price=float(row[7]),
            currency=row[8],
            source=row[9],
            source_url=row[10],
            collected_at=row[11],
        )
        for row in rows
    ]


@app.post("/competitors/rates", response_model=CompetitorRateObservationRecord)
def create_competitor_rate(rate: CompetitorRateObservationCreate) -> CompetitorRateObservationRecord:
    with _db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO competitor_rate_observations (
                    competitor_room_type_id, stay_date, check_in, check_out,
                    price, currency, source, source_url
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    rate.competitor_room_type_id,
                    rate.stay_date,
                    rate.stay_date,
                    rate.stay_date + timedelta(days=1),
                    rate.price,
                    rate.currency,
                    rate.source,
                    rate.source_url,
                ),
            )
            rate_id = int(cursor.fetchone()[0])
        conn.commit()

    created = next(item for item in list_competitor_rates(days=180) if item.id == rate_id)
    return created


@app.post("/competitors/ctrip-collection", response_model=CtripCollectionJobRecord)
def start_ctrip_collection(
    request: CtripCollectionRequest,
    background_tasks: BackgroundTasks,
) -> CtripCollectionJobRecord:
    if request.calendar_days < 1 or request.calendar_days > 180:
        raise HTTPException(status_code=400, detail="calendar_days must be between 1 and 180")
    hotel_ids = [hotel_id.strip() for hotel_id in request.hotel_ids or [] if hotel_id.strip()]
    if not hotel_ids:
        hotel_ids = None
    job = CtripCollectionJobRecord(
        id=str(uuid.uuid4()),
        status="queued",
        started_at=datetime.now().isoformat(timespec="seconds"),
        hotel_ids=hotel_ids,
        calendar_days=request.calendar_days,
    )
    CTRIP_COLLECTION_JOBS[job.id] = job
    timeout_seconds = min(max(request.timeout_seconds, 60), 7200)
    background_tasks.add_task(
        _run_ctrip_collection_job,
        job.id,
        hotel_ids,
        request.calendar_days,
        request.skip_import,
        timeout_seconds,
    )
    return job


@app.get("/competitors/ctrip-collection/{job_id}", response_model=CtripCollectionJobRecord)
def get_ctrip_collection_job(job_id: str) -> CtripCollectionJobRecord:
    job = CTRIP_COLLECTION_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ctrip collection job not found")
    return job


def _run_ctrip_collection_job(
    job_id: str,
    hotel_ids: list[str] | None,
    calendar_days: int,
    skip_import: bool,
    timeout_seconds: int,
) -> None:
    job = CTRIP_COLLECTION_JOBS[job_id]
    job.status = "running"
    backend_dir = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "scripts/collect_ctrip_competitors.py",
        "--calendar-days",
        str(calendar_days),
    ]
    if hotel_ids:
        command.extend(["--hotel-ids", ",".join(hotel_ids)])
    if skip_import:
        command.append("--skip-import")

    try:
        completed = subprocess.run(
            command,
            cwd=backend_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        job.exit_code = completed.returncode
        job.stdout_tail = completed.stdout[-5000:]
        job.stderr_tail = completed.stderr[-5000:]
        job.status = "completed" if completed.returncode == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        job.exit_code = None
        job.stdout_tail = (exc.stdout or "")[-5000:] if isinstance(exc.stdout, str) else ""
        job.stderr_tail = (exc.stderr or "")[-5000:] if isinstance(exc.stderr, str) else ""
        job.stderr_tail = (job.stderr_tail + f"\nCtrip collection timed out after {timeout_seconds} seconds.").strip()
        job.status = "failed"
    finally:
        job.finished_at = datetime.now().isoformat(timespec="seconds")


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
    competitor_rates = _competitor_market_rates(
        hotel_id=hotel_id,
        room_type_id=room_type.id,
        stay_dates=stay_dates,
    )
    recommendations = [
        _build_recommendation(
            stay_date=stay_date,
            room_type=room_type,
            historical_base_rates=base_rates,
            historical_average_rate=historical_rates.get(stay_date),
            competitor_market=competitor_rates.get(stay_date),
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
    competitor_market: dict[str, float] | None = None,
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
    competitor_market_rate = competitor_market["median"] if competitor_market else None
    competitor_adjustment_amount, competitor_logic = _competitor_adjustment(
        recommended_rate=recommended_rate,
        competitor_market_rate=competitor_market_rate,
    )
    recommended_rate = max(0, recommended_rate + competitor_adjustment_amount)
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
    if competitor_logic:
        reasons.append("竞品价格护栏: " + "；".join(competitor_logic))
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
        competitor_market_rate=round(competitor_market_rate, 2)
        if competitor_market_rate is not None
        else None,
        competitor_average_rate=round(competitor_market["average"], 2)
        if competitor_market
        else None,
        competitor_min_rate=round(competitor_market["min"], 2)
        if competitor_market
        else None,
        competitor_max_rate=round(competitor_market["max"], 2)
        if competitor_market
        else None,
        competitor_adjustment_amount=competitor_adjustment_amount,
        competitor_logic=competitor_logic,
        change_percent=change_percent,
        confidence=round(min(confidence, 0.86), 2),
        reasons=reasons,
    )


def _round_rate(rate: float) -> int:
    return int(round(rate / 10) * 10)


def _competitor_adjustment(
    recommended_rate: int,
    competitor_market_rate: float | None,
) -> tuple[int, list[str]]:
    if competitor_market_rate is None:
        return 0, []

    lower_guardrail = competitor_market_rate * 0.85
    upper_guardrail = competitor_market_rate * 1.15
    if recommended_rate > upper_guardrail:
        target_rate = (recommended_rate + upper_guardrail) / 2
        adjustment = _round_rate(target_rate) - recommended_rate
        return adjustment, [
            f"竞品中位价约 MOP {competitor_market_rate:.0f}，原建议价高于市场上沿，温和下调 MOP {abs(adjustment)}"
        ]
    if recommended_rate < lower_guardrail:
        target_rate = (recommended_rate + lower_guardrail) / 2
        adjustment = _round_rate(target_rate) - recommended_rate
        return adjustment, [
            f"竞品中位价约 MOP {competitor_market_rate:.0f}，原建议价低于市场下沿，温和上调 MOP {adjustment}"
        ]
    return 0, [f"竞品中位价约 MOP {competitor_market_rate:.0f}，建议价处于市场区间内"]


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


def _competitor_market_rates(
    hotel_id: str,
    room_type_id: str,
    stay_dates: list[date],
) -> dict[date, dict[str, float]]:
    if not stay_dates:
        return {}

    placeholders = ", ".join(["%s"] * len(stay_dates))
    query = f"""
        SELECT latest.stay_date, latest.price
        FROM (
            SELECT DISTINCT ON (o.competitor_room_type_id, o.stay_date)
                   o.competitor_room_type_id, o.stay_date, o.price
            FROM competitor_rate_observations o
            JOIN room_type_competitor_mappings m
              ON m.competitor_room_type_id = o.competitor_room_type_id
            WHERE m.hotel_id = %s
              AND m.room_type_id = %s
              AND o.stay_date IN ({placeholders})
              AND o.price IS NOT NULL
            ORDER BY o.competitor_room_type_id, o.stay_date, o.collected_at DESC
        ) latest
    """
    params = [hotel_id, room_type_id, *stay_dates]

    try:
        with _db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
    except Exception:
        return {}

    prices_by_date: dict[date, list[float]] = {}
    for stay_date, price in rows:
        prices_by_date.setdefault(stay_date, []).append(float(price) * 1.1)
    return {
        stay_date: {
            "median": median(prices),
            "average": mean(prices),
            "min": min(prices),
            "max": max(prices),
        }
        for stay_date, prices in prices_by_date.items()
        if prices
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
