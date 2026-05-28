CREATE TABLE IF NOT EXISTS competitor_hotels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    district TEXT NOT NULL,
    ctrip_hotel_id TEXT,
    ctrip_url TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS competitor_room_types (
    id BIGSERIAL PRIMARY KEY,
    competitor_hotel_id TEXT NOT NULL REFERENCES competitor_hotels(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    ctrip_room_id TEXT,
    normalized_name TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (competitor_hotel_id, name)
);

CREATE TABLE IF NOT EXISTS room_type_competitor_mappings (
    id BIGSERIAL PRIMARY KEY,
    hotel_id TEXT NOT NULL REFERENCES hotels(id),
    room_type_id TEXT NOT NULL,
    competitor_room_type_id BIGINT NOT NULL REFERENCES competitor_room_types(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 1,
    weight NUMERIC(6, 4) NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (hotel_id, room_type_id, competitor_room_type_id)
);

CREATE TABLE IF NOT EXISTS competitor_collection_runs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS competitor_rate_observations (
    id BIGSERIAL PRIMARY KEY,
    competitor_room_type_id BIGINT NOT NULL REFERENCES competitor_room_types(id) ON DELETE CASCADE,
    stay_date DATE NOT NULL,
    check_in DATE NOT NULL,
    check_out DATE NOT NULL,
    price NUMERIC(12, 2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    tax_included BOOLEAN,
    breakfast_included BOOLEAN,
    refundable BOOLEAN,
    source TEXT NOT NULL DEFAULT 'manual',
    source_url TEXT,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    collection_run_id BIGINT REFERENCES competitor_collection_runs(id),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (competitor_room_type_id, stay_date, source, collected_at)
);

CREATE INDEX IF NOT EXISTS idx_competitor_rate_observations_room_date
    ON competitor_rate_observations (competitor_room_type_id, stay_date);

CREATE INDEX IF NOT EXISTS idx_room_type_competitor_mappings_room
    ON room_type_competitor_mappings (hotel_id, room_type_id);

INSERT INTO competitor_hotels (id, name, district, ctrip_hotel_id, ctrip_url, notes) VALUES
    ('golden-dragon', '澳门金龙酒店', '澳门半岛', '345757', 'https://hotels.ctrip.com/hotels/detail/?cityEnName=Macau&cityId=59&hotelId=345757', 'Initial competitor set'),
    ('rio', '澳门利澳酒店', '澳门半岛', NULL, NULL, 'Initial competitor set'),
    ('sintra', '澳门新丽华酒店', '澳门半岛', NULL, NULL, 'Initial competitor set'),
    ('grand-emperor', '澳门英皇娱乐酒店', '澳门半岛', NULL, NULL, 'Initial competitor set'),
    ('metropark', '澳门维景酒店', '澳门半岛', NULL, NULL, 'Initial competitor set'),
    ('fortune', '澳门财神酒店', '澳门半岛', NULL, NULL, 'Initial competitor set'),
    ('guia', '东望洋酒店', '澳门半岛', NULL, NULL, 'Initial competitor set')
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    district = EXCLUDED.district,
    ctrip_hotel_id = COALESCE(competitor_hotels.ctrip_hotel_id, EXCLUDED.ctrip_hotel_id),
    ctrip_url = COALESCE(competitor_hotels.ctrip_url, EXCLUDED.ctrip_url),
    active = TRUE,
    notes = EXCLUDED.notes,
    updated_at = now();
