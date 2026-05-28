from __future__ import annotations

import sqlite3
from pathlib import Path


def main() -> None:
    db_path = Path(__file__).resolve().parents[1] / "data" / "hotel_rms.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        print("rows by hotel:")
        for row in conn.execute(
            """
            SELECT
                hotel_id,
                COUNT(*) AS orders,
                MIN(arrival_date) AS first_arrival,
                MAX(arrival_date) AS last_arrival,
                ROUND(SUM(room_nights), 2) AS room_nights,
                ROUND(SUM(total_room_revenue), 2) AS total_room_revenue
            FROM hotel_orders
            GROUP BY hotel_id
            ORDER BY hotel_id
            """
        ):
            print(row)

        print("monthly sample:")
        for row in conn.execute(
            """
            SELECT
                hotel_id,
                SUBSTR(arrival_date, 1, 7) AS arrival_month,
                COUNT(*) AS orders,
                ROUND(SUM(total_room_revenue), 2) AS total_room_revenue
            FROM hotel_orders
            GROUP BY hotel_id, arrival_month
            ORDER BY hotel_id, arrival_month
            LIMIT 12
            """
        ):
            print(row)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
