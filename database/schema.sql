CREATE TABLE IF NOT EXISTS hotels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    district TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_import_runs (
    id BIGSERIAL PRIMARY KEY,
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS hotel_orders (
    id BIGSERIAL PRIMARY KEY,
    hotel_id TEXT NOT NULL REFERENCES hotels(id),
    source_row INTEGER NOT NULL,
    month_label TEXT,
    order_no TEXT NOT NULL,
    arrival_date DATE NOT NULL,
    departure_date DATE NOT NULL,
    order_status TEXT,
    sales_contract TEXT,
    room_type TEXT,
    charged_room_type TEXT,
    rate_code TEXT,
    room_nights NUMERIC(10, 2),
    room_count NUMERIC(10, 2),
    room_rate NUMERIC(12, 2),
    total_room_revenue NUMERIC(14, 2),
    market_segment TEXT,
    guest_source TEXT,
    package_plan TEXT,
    import_run_id BIGINT REFERENCES order_import_runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (hotel_id, order_no, arrival_date, departure_date, room_type, charged_room_type, source_row)
);

CREATE INDEX IF NOT EXISTS idx_hotel_orders_hotel_arrival
    ON hotel_orders (hotel_id, arrival_date);

CREATE INDEX IF NOT EXISTS idx_hotel_orders_room_type
    ON hotel_orders (hotel_id, room_type);

CREATE INDEX IF NOT EXISTS idx_hotel_orders_market_source
    ON hotel_orders (market_segment, guest_source);

INSERT INTO hotels (id, name, district) VALUES
    ('kyoto', '京都酒店', '澳门半岛'),
    ('emperor', '帝濠酒店', '澳门半岛'),
    ('riviera', '濠璟酒店', '西湾'),
    ('beverly', '富豪酒店', '澳门半岛')
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    district = EXCLUDED.district;

