from __future__ import annotations

import sqlite3
from pathlib import Path


def main() -> None:
    db_path = Path(__file__).resolve().parents[1] / "data" / "hotel_rms.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        print("hotel_id, arrival_month, orders, room_nights, total_room_revenue")
        for row in conn.execute(
            """
            SELECT
                hotel_id,
                SUBSTR(arrival_date, 1, 7) AS arrival_month,
                COUNT(*) AS orders,
                ROUND(SUM(room_nights), 2) AS room_nights,
                ROUND(SUM(total_room_revenue), 2) AS total_room_revenue
            FROM hotel_orders
            GROUP BY hotel_id, arrival_month
            ORDER BY hotel_id, arrival_month
            """
        ):
            print(row)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
