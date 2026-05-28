from __future__ import annotations

import os
from pathlib import Path

import psycopg


def main() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://hotel_rms:hotel_rms_dev@localhost:5432/hotel_rms",
    )
    schema_path = Path(__file__).resolve().parents[2] / "database" / "event_schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute(schema)
        conn.commit()
    print(f"Applied event schema from {schema_path}")


if __name__ == "__main__":
    main()

