CREATE TABLE IF NOT EXISTS hotel_locations (
    hotel_id TEXT PRIMARY KEY REFERENCES hotels(id),
    latitude NUMERIC(10, 7) NOT NULL,
    longitude NUMERIC(10, 7) NOT NULL,
    district TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS venue_locations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    district TEXT NOT NULL,
    latitude NUMERIC(10, 7) NOT NULL,
    longitude NUMERIC(10, 7) NOT NULL,
    default_impact_radius_km NUMERIC(8, 2) NOT NULL DEFAULT 6,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS external_event_sources (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    base_url TEXT,
    trust_score NUMERIC(4, 3) NOT NULL DEFAULT 0.700,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_event_sources_unique
    ON external_event_sources (name, source_type, COALESCE(base_url, ''));

CREATE TABLE IF NOT EXISTS external_events (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    venue_id TEXT REFERENCES venue_locations(id),
    source_id BIGINT REFERENCES external_event_sources(id),
    source_url TEXT,
    confidence_score NUMERIC(4, 3) NOT NULL DEFAULT 0.700,
    impact_level TEXT NOT NULL DEFAULT 'medium',
    base_weight NUMERIC(6, 4) NOT NULL DEFAULT 0.0800,
    status TEXT NOT NULL DEFAULT 'candidate',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (status IN ('candidate', 'confirmed', 'rejected', 'expired'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_events_unique
    ON external_events (name, start_date, end_date, COALESCE(venue_id, ''));

CREATE TABLE IF NOT EXISTS event_hotel_impacts (
    event_id BIGINT NOT NULL REFERENCES external_events(id) ON DELETE CASCADE,
    hotel_id TEXT NOT NULL REFERENCES hotels(id),
    distance_km NUMERIC(8, 3),
    distance_factor NUMERIC(6, 4) NOT NULL DEFAULT 1,
    final_weight NUMERIC(6, 4) NOT NULL,
    logic TEXT,
    PRIMARY KEY (event_id, hotel_id)
);

CREATE INDEX IF NOT EXISTS idx_external_events_date_status
    ON external_events (status, start_date, end_date);

CREATE INDEX IF NOT EXISTS idx_event_hotel_impacts_hotel
    ON event_hotel_impacts (hotel_id);

INSERT INTO hotel_locations (hotel_id, latitude, longitude, district, notes) VALUES
    ('kyoto', 22.1902000, 113.5433000, '澳门半岛', 'Approximate coordinates for pricing impact distance model'),
    ('emperor', 22.1915000, 113.5486000, '澳门半岛', 'Approximate coordinates for pricing impact distance model'),
    ('beverly', 22.1919000, 113.5489000, '澳门半岛', 'Approximate coordinates for pricing impact distance model'),
    ('riviera', 22.1846000, 113.5369000, '西湾', 'Approximate coordinates for pricing impact distance model')
ON CONFLICT (hotel_id) DO UPDATE
SET latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    district = EXCLUDED.district,
    notes = EXCLUDED.notes;

INSERT INTO venue_locations (id, name, district, latitude, longitude, default_impact_radius_km, notes) VALUES
    ('guia-circuit', '澳门东望洋赛道', '澳门半岛', 22.1953000, 113.5493000, 8, 'Macau Grand Prix primary impact area'),
    ('galaxy-arena', '银河综艺馆', '路氹', 22.1488000, 113.5528000, 7, 'Large concert and entertainment venue'),
    ('venetian-arena', '威尼斯人综艺馆', '路氹', 22.1477000, 113.5629000, 7, 'Large concert and entertainment venue'),
    ('studio-city-event-center', '新濠影汇综艺馆', '路氹', 22.1396000, 113.5633000, 7, 'Large concert and entertainment venue'),
    ('macau-tower', '澳门旅游塔', '南湾', 22.1800000, 113.5378000, 5, 'Event and convention venue'),
    ('tap-seac-square', '塔石广场', '澳门半岛', 22.1992000, 113.5460000, 5, 'Public cultural event area')
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    district = EXCLUDED.district,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    default_impact_radius_km = EXCLUDED.default_impact_radius_km,
    notes = EXCLUDED.notes;
