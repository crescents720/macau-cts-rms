from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = [
    "月份",
    "订单号",
    "抵店日期",
    "离店日期",
    "订单状态",
    "销售协议",
    "房类",
    "收费房类",
    "房价代码",
    "房晚数",
    "房数",
    "房价",
    "总房租",
    "市场类别",
    "客人来源",
    "包价套票",
]

COLUMN_MAP = {
    "月份": "month_label",
    "订单号": "order_no",
    "抵店日期": "arrival_date",
    "离店日期": "departure_date",
    "订单状态": "order_status",
    "销售协议": "sales_contract",
    "房类": "room_type",
    "收费房类": "charged_room_type",
    "房价代码": "rate_code",
    "房晚数": "room_nights",
    "房数": "room_count",
    "房价": "room_rate",
    "总房租": "total_room_revenue",
    "市场类别": "market_segment",
    "客人来源": "guest_source",
    "包价套票": "package_plan",
}

WORKBOOKS = {
    "emperor": Path(r"D:\Meng's Workspace\酒店自营包销数据分析\帝濠\帝濠酒店订单数据分析.xlsx"),
    "beverly": Path(r"D:\Meng's Workspace\酒店自营包销数据分析\富豪\富豪酒店订单数据分析.xlsx"),
    "riviera": Path(r"D:\Meng's Workspace\酒店自营包销数据分析\濠璟\濠璟酒店订单数据分析.xlsx"),
    "kyoto": Path(r"D:\Meng's Workspace\酒店自营包销数据分析\京都酒店订单数据分析.xlsx"),
}

HOTELS = [
    ("kyoto", "京都酒店", "澳门半岛"),
    ("emperor", "帝濠酒店", "澳门半岛"),
    ("riviera", "濠璟酒店", "西湾"),
    ("beverly", "富豪酒店", "澳门半岛"),
]


@dataclass(frozen=True)
class ImportResult:
    hotel_id: str
    rows: int
    source_file: Path


def load_orders(hotel_id: str, path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="订单数据")
    df = df.dropna(how="all")

    if "房数" not in df.columns:
        df["房数"] = 1

    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"{path} missing columns: {missing}")

    df = df[REQUIRED_COLUMNS].copy()
    df = df.rename(columns=COLUMN_MAP)
    df.insert(0, "source_row", df.index + 2)
    df.insert(0, "hotel_id", hotel_id)

    df["order_no"] = df["order_no"].map(clean_text)
    for column in [
        "month_label",
        "order_status",
        "sales_contract",
        "room_type",
        "charged_room_type",
        "rate_code",
        "market_segment",
        "guest_source",
        "package_plan",
    ]:
        df[column] = df[column].map(clean_text)

    for column in ["arrival_date", "departure_date"]:
        df[column] = pd.to_datetime(df[column], errors="coerce").dt.date

    for column in ["room_nights", "room_count", "room_rate", "total_room_revenue"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df[df["order_no"].notna() & df["arrival_date"].notna() & df["departure_date"].notna()]
    return df


def clean_text(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None


def import_sqlite(db_path: Path, replace: bool) -> list[ImportResult]:
    if replace and db_path.exists():
        db_path.unlink()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        create_sqlite_schema(conn)
        return import_with_pandas(conn, dialect="sqlite")
    finally:
        conn.close()


def create_sqlite_schema(conn: sqlite3.Connection) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "database" / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    schema = schema.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    schema = schema.replace("TIMESTAMPTZ", "TEXT")
    schema = schema.replace("now()", "CURRENT_TIMESTAMP")
    schema = "\n".join(
        line for line in schema.splitlines() if "ON CONFLICT (id) DO UPDATE" not in line
    )
    schema = schema.replace("SET name = EXCLUDED.name,", "")
    schema = schema.replace("    district = EXCLUDED.district;", "")
    conn.executescript(schema)
    conn.commit()


def import_postgres(database_url: str, replace: bool) -> list[ImportResult]:
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    schema_path = Path(__file__).resolve().parents[2] / "database" / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    with engine.begin() as conn:
        if replace:
            conn.execute(text("DROP TABLE IF EXISTS hotel_orders CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS order_import_runs CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS hotels CASCADE"))
        conn.execute(text(schema))

    return import_postgres_with_sqlalchemy(engine)


def import_postgres_with_sqlalchemy(engine: Any) -> list[ImportResult]:
    from sqlalchemy import text

    results = []
    with engine.begin() as conn:
        for hotel_id, name, district in HOTELS:
            conn.execute(
                text(
                    """
                    INSERT INTO hotels (id, name, district) VALUES (:id, :name, :district)
                    ON CONFLICT (id) DO UPDATE
                    SET name = EXCLUDED.name,
                        district = EXCLUDED.district
                    """
                ),
                {"id": hotel_id, "name": name, "district": district},
            )

        for hotel_id, path in WORKBOOKS.items():
            orders = load_orders(hotel_id, path)
            import_run_id = conn.execute(
                text(
                    """
                    INSERT INTO order_import_runs (source_file, source_sheet, row_count)
                    VALUES (:source_file, :source_sheet, :row_count)
                    RETURNING id
                    """
                ),
                {
                    "source_file": str(path),
                    "source_sheet": "订单数据",
                    "row_count": len(orders),
                },
            ).scalar_one()
            orders["import_run_id"] = import_run_id
            orders.to_sql("hotel_orders", conn, if_exists="append", index=False, method="multi", chunksize=1000)
            results.append(ImportResult(hotel_id=hotel_id, rows=len(orders), source_file=path))

    return results


def import_with_pandas(conn: Any, dialect: str) -> list[ImportResult]:
    results = []
    for hotel_id, name, district in HOTELS:
        if dialect == "postgres":
            execute(
                conn,
                dialect,
                """
                INSERT INTO hotels (id, name, district) VALUES (?, ?, ?)
                ON CONFLICT (id) DO UPDATE
                SET name = EXCLUDED.name,
                    district = EXCLUDED.district
                """,
                (hotel_id, name, district),
            )
        else:
            execute(
                conn,
                dialect,
                "INSERT OR IGNORE INTO hotels (id, name, district) VALUES (?, ?, ?)",
                (hotel_id, name, district),
            )

    for hotel_id, path in WORKBOOKS.items():
        orders = load_orders(hotel_id, path)
        import_run_id = create_import_run(conn, dialect, path, len(orders))
        orders["import_run_id"] = import_run_id
        orders.to_sql("hotel_orders", conn, if_exists="append", index=False)
        results.append(ImportResult(hotel_id=hotel_id, rows=len(orders), source_file=path))

    commit(conn)
    return results


def create_import_run(conn: Any, dialect: str, source_file: Path, row_count: int) -> int:
    if dialect == "postgres":
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO order_import_runs (source_file, source_sheet, row_count)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (str(source_file), "订单数据", row_count),
        )
        return int(cursor.fetchone()[0])

    cursor = conn.execute(
        """
        INSERT INTO order_import_runs (source_file, source_sheet, row_count)
        VALUES (?, ?, ?)
        """,
        (str(source_file), "订单数据", row_count),
    )
    return int(cursor.lastrowid)


def execute(conn: Any, dialect: str, sql: str, params: tuple[Any, ...]) -> None:
    if dialect == "postgres":
        sql = sql.replace("?", "%s")
        cursor = conn.cursor()
        cursor.execute(sql, params)
    else:
        conn.execute(sql, params)


def commit(conn: Any) -> None:
    if hasattr(conn, "commit"):
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["sqlite", "postgres"], default="sqlite")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--sqlite-path",
        default=str(Path(__file__).resolve().parents[2] / "database" / "hotel_rms.sqlite"),
    )
    args = parser.parse_args()

    if args.target == "postgres":
        database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://hotel_rms:hotel_rms_dev@localhost:5432/hotel_rms",
        )
        results = import_postgres(database_url, replace=args.replace)
    else:
        results = import_sqlite(Path(args.sqlite_path), replace=args.replace)

    for result in results:
        print(f"{result.hotel_id}: {result.rows} rows from {result.source_file}")


if __name__ == "__main__":
    main()
