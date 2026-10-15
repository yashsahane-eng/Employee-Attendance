# Employee Attendance & Analytics API

A small backend built with Python, FastAPI and MongoDB. Employees punch in and out, managers can correct records, and the API gives attendance reports.

## How to run

You need Python 3.11 or newer and MongoDB 6.0 or newer (the free MongoDB Atlas tier works).

1. Install the packages:

   pip install -r requirements.txt

2. Set two environment variables:
   - `MONGO_URI` – your MongoDB connection string
   - `MONGO_DB` – the database name (for example `attendance_db`)

   If they are not set, the app uses `mongodb://localhost:27017` and `attendance_db`.
3. Start the server:

   uvicorn app.main:app --port 8000

   If `uvicorn` is not found, use `python -m uvicorn app.main:app --port 8000`.
4. Open `http://127.0.0.1:8000/docs` to try the endpoints.

The indexes are created automatically when the app starts. No manual steps are needed.

Optional: `python sample_seed.py` loads the small sample data from the kit.

## What is built

All endpoints in the contract are written:

- `GET /health`
- `POST /employees`, `GET /employees`
- `POST /attendance/punch-in`, `POST /attendance/punch-out`
- `PATCH /attendance/{emp_code}/{date}` (manual correction with history)
- `GET /attendance`
- `GET /analytics/employees/{emp_code}/monthly`
- `GET /analytics/departments/summary`
- `GET /analytics/leaderboard/late`
- `GET /analytics/departments/{department}/trend`
- `GET /admin/explain/{endpoint}`

I tested the main flows by hand in `/docs`. I did not test every edge case, and I did not test with 100,000 records.

## How it works

- Times are stored in UTC. The attendance date and shift times use IST. The API sends and receives times as epoch milliseconds.
- Overnight shifts are handled: a punch-in after midnight can belong to the previous day's record.
- Work hours are rounded to 2 decimals, half up.
- Unique indexes stop duplicate employee codes and duplicate attendance records for the same employee and date. A duplicate returns 409.
- The reports are MongoDB aggregation pipelines.

## Known issues

- The explain endpoint builds simplified versions of some queries, not exactly the same ones the analytics endpoints run.
- The trend endpoint rounds with MongoDB's `$round`, which rounds exact ties to the even number. In rare cases this can differ from       half-up rounding.
- Correction history times may not be converted to epoch milliseconds in every response.
- Not tested: heavy concurrent requests and large data volumes.

All code is in `app/main.py`. No `.env` file or secrets are in this repository.



[![Architecture diagram of yashsahane-eng/employee-attendance](https://gitdiagram.com/yashsahane-eng/employee-attendance/diagram.png)](https://gitdiagram.com/yashsahane-eng/employee-attendance?utm_source=readme&utm_medium=picture)
