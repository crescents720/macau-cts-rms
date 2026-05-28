# Hotel Orders Database

The first local order database has been built from the four 2025 Excel workbooks.

## Source Workbooks

- 帝濠: `D:\Meng's Workspace\酒店自营包销数据分析\帝濠\帝濠酒店订单数据分析.xlsx`
- 富豪: `D:\Meng's Workspace\酒店自营包销数据分析\富豪\富豪酒店订单数据分析.xlsx`
- 濠璟: `D:\Meng's Workspace\酒店自营包销数据分析\濠璟\濠璟酒店订单数据分析.xlsx`
- 京都: `D:\Meng's Workspace\酒店自营包销数据分析\京都酒店订单数据分析.xlsx`

All imports read the `订单数据` sheet.

## Normalized Columns

The `hotel_orders` table keeps these normalized fields:

- `hotel_id`
- `month_label`
- `order_no`
- `arrival_date`
- `departure_date`
- `order_status`
- `sales_contract`
- `room_type`
- `charged_room_type`
- `rate_code`
- `room_nights`
- `room_count`
- `room_rate`
- `total_room_revenue`
- `market_segment`
- `guest_source`
- `package_plan`

京都 has extra personal and operational columns in the workbook. Those columns are intentionally trimmed during import.

富豪 lacks `房数`; the importer fills `room_count = 1`.

## Immediate Local Database

SQLite verification database:

```text
backend/data/hotel_rms.sqlite
```

Rebuild it:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\import_orders.py --target sqlite --replace --sqlite-path data\hotel_rms.sqlite
```

Verify it:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\verify_orders_db.py
```

## PostgreSQL Direction

Navicat Premium Lite is a database client. It can connect to PostgreSQL, but it does not run the PostgreSQL server itself.

The project includes a Docker-based PostgreSQL setup:

```powershell
cd database
docker compose up -d
```

Connection settings for Navicat:

- Host: `localhost`
- Port: `5432`
- Database: `hotel_rms`
- User: `hotel_rms`
- Password: `hotel_rms_dev`

After PostgreSQL is running, import the Excel data:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\import_orders.py --target postgres --replace
```

