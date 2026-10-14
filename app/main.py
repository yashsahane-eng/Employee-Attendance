"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import date, datetime, timedelta, timezone
from pydoc import doc
from threading import local
from tracemalloc import start
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictInt , Field ,model_validator
from bson.json_util import dumps, loads

from fastapi.responses import JSONResponse
from pymongo.errors import DuplicateKeyError
from fastapi.responses import Response


from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException , Query, Response  #Added Query import to use in list_employees endpoint
from pydantic import BaseModel
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017")) 
db = client[os.getenv("MONGO_DB", "attendance_db")]
db.employees.create_index("emp_code", unique=True)

db.attendance_logs.create_index(
    [("emp_code", 1), ("date", 1)],
    unique=True
)
db.attendance_logs.create_index([
    ("date", -1),
    ("emp_code", 1)
])

db.employees.create_index([
    ("department", 1),
    ("joined_on", 1)
])
IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def compute_late_minutes(
    
    punch_in: datetime, shift_start: str, shift_end: str
) -> int:
    
    punch_in = punch_in.replace(microsecond=0)
    local_time = punch_in.astimezone(IST)

    start_h, start_m = map(int, shift_start.split(":"))
    end_h, end_m = map(int, shift_end.split(":"))

    start = local_time.replace(
        hour=start_h, minute=start_m, second=0, microsecond=0
    )

    # If this is an overnight shift and punch-in is
    # before the shift end, the shift started yesterday.
    if end_h * 60 + end_m <= start_h * 60 + start_m:
        if local_time.hour * 60 + local_time.minute < end_h * 60 + end_m:
            start -= timedelta(days=1)

    elapsed_seconds = (local_time - start).total_seconds()
    minutes = int(elapsed_seconds // 60)
#This preserves the 10-minute grace period while correctly returning 10 for a punch at 09:40:01 when the shift starts at 09:30.
    return minutes if elapsed_seconds > 600 else 0





def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    # Normalize both datetimes to UTC before subtraction
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)
    else:
        punch_in = punch_in.astimezone(timezone.utc)

    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=timezone.utc)
    else:
        punch_out = punch_out.astimezone(timezone.utc)

    seconds = Decimal(str((punch_out - punch_in).total_seconds()))
    hours = seconds / Decimal("3600")

    return float(
        hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )




def compute_overtime( #Your current function always puts the shift end on date_str, but for an overnight shift, the end time belongs to the next calendar day.
    punch_out: datetime,
    shift_start: str,
    shift_end: str,
    date_str: str
) -> int:
    start_h, start_m = map(int, shift_start.split(":"))
    end_h, end_m = map(int, shift_end.split(":"))

    end_date = datetime.fromisoformat(date_str).replace(tzinfo=IST)

    if end_h * 60 + end_m <= start_h * 60 + start_m:
        end_date += timedelta(days=1)

    end = end_date.replace(
        hour=end_h, minute=end_m, second=0, microsecond=0
    )

    punch_out = punch_out.replace(microsecond=0)
    minutes = int((punch_out - end).total_seconds() // 60)

    return minutes if minutes >= 30 else 0



# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$") #This enforces the required format: EMP followed by 4–6 digits
    name: str =Field(min_length=1, max_length=100)  #This ensures overly long names are rejected before they reach the database.
    email: str=Field(min_length=1,max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
)
    department: str=Field(min_length=1, max_length=50)
    shift_start: str = Field(default="09:30",pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    shift_end: str =Field(default="18:30",pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    joined_on: date
    @model_validator(mode="after")
    def validate_shift_times(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end cannot be equal")
        return self
   


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[StrictInt] = None
    status: str = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[StrictInt] = None

class RegularizeIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[StrictInt] = None
    punch_out: Optional[StrictInt] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)






# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(503, "database unavailable")

@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["joined_on"] = body.joined_on.isoformat()
    doc["created_at"] = datetime.now(timezone.utc) #without a timezone creates a naive datetime. The contract requires created_at to be stored as a UTC datetime.
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int =Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)): #page must be at least 1.page_size must be between 1 and 100.
    q = {}
    if department:
        q["department"] = department
    #skip = page * page_size      #The expected behaviour is to return employees 1–10 and MongoDB skips the first 10 employees and returns employees 11–20.
    skip=(page -1)*page_size
    #total = db.employees.count_documents({}) : Suppose the database has 50 employees, but only 12 belong to Engineering. The client requests:only engineering students .
    total = db.employees.count_documents(q) 
    #items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size).sort("emp_code", 1))  #The API contract requires employees to be sorted by emp_code in ascending order.
    
    items = list(db.employees.find(q, {"_id": 0}).sort("emp_code", 1).skip(skip).limit(page_size))   #MongoDB may return records in an inconsistent order between requests, causing employees to appear on the wrong page or be repeated.

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code}) #If the employee doesn't exist, emp is None, and the application can crash with an unhandled error.
    if not emp:
        raise HTTPException(404, "employee not found") 
    # Validate punch-in status
    if body.status not in ["PRESENT", "WFH", "ON_DUTY"]:
        raise HTTPException(422, "invalid attendance status")
    #find_one() returns None when no employee matches. The explicit check stops execution and returns HTTP 404 instead of allowing a TypeError later.
    #There are two problems here:- datetime.fromtimestamp() uses the machine's local timezone.- datetime.now() also depends on the machine's local timezone.
    if body.punched_at is not None:
        if body.punched_at < 100_000_000_000:
         raise HTTPException(422, "punched_at must be epoch milliseconds")


    if body.punched_at is not None:
        if body.punched_at < 100_000_000_000:
            raise HTTPException(422, "punched_at must be epoch milliseconds")

        try:#When punched_at is omitted, the server uses the current time. When it's provided, the server validates and converts the epoch milliseconds.
            ts = datetime.fromtimestamp(body.punched_at / 1000, IST)
        except (ValueError, OverflowError, OSError):
            raise HTTPException(422, "punched_at is out of range")
    else:
        ts = datetime.now(IST)

    ts = ts.replace(microsecond=0)

    local_ts = ts.astimezone(IST)

    start_minutes = (
        int(emp["shift_start"][:2]) * 60
        + int(emp["shift_start"][3:])
)
    end_minutes = (
        int(emp["shift_end"][:2]) * 60
        + int(emp["shift_end"][3:])
)
    punch_minutes = local_ts.hour * 60 + local_ts.minute

    attendance_date = local_ts.date()

    if end_minutes <= start_minutes and punch_minutes < end_minutes:
        attendance_date -= timedelta(days=1)

    d = attendance_date.isoformat()

    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")

    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            ts, emp["shift_start"], emp["shift_end"]
    ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
}

    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this date")

    doc.pop("_id", None)
    doc["punch_in"] = int(ts.timestamp() * 1000)

    return doc

@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")

    if body.punched_at is not None:
        if body.punched_at < 100_000_000_000:
            raise HTTPException(422, "punched_at must be epoch milliseconds")
        try:
            ts = datetime.fromtimestamp(body.punched_at / 1000, timezone.utc)
        except (ValueError, OverflowError, OSError):
            raise HTTPException(422, "punched_at is out of range")
    else:
        ts = datetime.now(timezone.utc)

    ts = ts.replace(microsecond=0)

    punch_in_record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$ne": None, "$lte": ts},
        },
        sort=[("punch_in", -1)],
    )

    if not punch_in_record:
        raise HTTPException(404, "no matching punch-in found")

    punch_in_time = punch_in_record["punch_in"]
    if punch_in_time.tzinfo is None:
        punch_in_time = punch_in_time.replace(tzinfo=timezone.utc)

    punch_in_time = punch_in_time.replace(microsecond=0)

    if punch_in_record.get("punch_out") is not None:
        raise HTTPException(409, "already punched out")

    elapsed_seconds = (ts - punch_in_time).total_seconds()
    if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:
        raise HTTPException(422, "invalid punch-out time")

    work_hours = compute_work_hours(punch_in_time, ts)
    overtime_minutes = compute_overtime(
        ts,
        emp["shift_start"],
        emp["shift_end"],
        punch_in_record["date"],
    )
    half_day = work_hours < 4.50

    result = db.attendance_logs.update_one(
        {
            "_id": punch_in_record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    if result.modified_count != 1:
        raise HTTPException(409, "attendance record was already updated")

    return {
        "emp_code": body.emp_code,
        "date": punch_in_record["date"],
        "punch_in": int(punch_in_time.timestamp() * 1000),
        "punch_out": int(ts.timestamp() * 1000),
        "status": punch_in_record["status"],
        "work_hours": work_hours,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
        "late_minutes": punch_in_record.get("late_minutes", 0),
        "history": punch_in_record.get("history", []),
    }


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: date,
    body: RegularizeIn
):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")

    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date.isoformat()
    })
    if not record:
        raise HTTPException(404, "attendance record not found")

    supplied = body.model_fields_set

    if body.status is not None and body.status not in [
        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
    ]:
        raise HTTPException(422, "invalid attendance status")

    if "punch_in" in supplied and body.punch_in is None:
        raise HTTPException(422, "punch_in cannot be null")

    if "punch_out" in supplied and body.punch_out is None:
        raise HTTPException(422, "punch_out cannot be null")

    status = body.status if body.status is not None else record["status"]

    if status in ["ABSENT", "LEAVE"]:
        if "punch_in" in supplied or "punch_out" in supplied:
            raise HTTPException(
                422, "punch times cannot be supplied with ABSENT or LEAVE"
            )
        punch_in = None
        punch_out = None
    else:
        punch_in = (
            datetime.fromtimestamp(body.punch_in / 1000, timezone.utc)
            if "punch_in" in supplied else record.get("punch_in")
        )
        punch_out = (
            datetime.fromtimestamp(body.punch_out / 1000, timezone.utc)
            if "punch_out" in supplied else record.get("punch_out")
        )

        if not punch_in:
            raise HTTPException(422, "presence status requires punch_in")

        punch_in_ist = punch_in.replace(tzinfo=timezone.utc).astimezone(IST)
        if punch_in_ist.date().isoformat() != date.isoformat():
            raise HTTPException(
                422, "punch_in must be on the attendance date in IST"
            )

        if punch_out:
            if punch_out.tzinfo is None:
                punch_out = punch_out.replace(tzinfo=timezone.utc)

            punch_in_utc = (
                punch_in.replace(tzinfo=timezone.utc)
                if punch_in.tzinfo is None else punch_in.astimezone(timezone.utc)
            )
            punch_out_utc = (
                punch_out.replace(tzinfo=timezone.utc)
                if punch_out.tzinfo is None else punch_out.astimezone(timezone.utc)
            )

            elapsed = (punch_out_utc - punch_in_utc).total_seconds()
            if elapsed <= 0 or elapsed > 24 * 60 * 60:
                raise HTTPException(422, "invalid punch-out time")

    if punch_in and status not in ["ABSENT", "LEAVE"]:
        late_minutes = compute_late_minutes(
            punch_in, emp["shift_start"], emp["shift_end"]
        )
    else:
        late_minutes = 0

    if punch_in and punch_out:
        work_hours = compute_work_hours(punch_in, punch_out)
        overtime_minutes = compute_overtime(
            punch_out, emp["shift_start"], emp["shift_end"], date.isoformat()
        )
        half_day = work_hours < 4.50
    else:
        work_hours = None
        overtime_minutes = 0
        half_day = False

    new_values = {
        "status": status,
        "punch_in": punch_in,
        "punch_out": punch_out,
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    changes = {}
    for field, new_value in new_values.items():
        old_value = record.get(field)
        if field in ["punch_in", "punch_out"]:
            old_ms = (
                int(old_value.replace(tzinfo=timezone.utc).timestamp() * 1000)
                if old_value else None
            )
            new_ms = (
                int(new_value.replace(tzinfo=timezone.utc).timestamp() * 1000)
                if new_value else None
            )
            if old_ms != new_ms:
                changes[field] = {"from": old_ms, "to": new_ms}
        elif old_value != new_value:
            changes[field] = {"from": old_value, "to": new_value}

    if not changes:
        raise HTTPException(422, "request does not change the record")

    history_entry = {
        "at": datetime.now(timezone.utc),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }

    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "history": record.get("history", []),
        },
        {
            "$set": new_values,
            "$push": {"history": history_entry},
        },
    )

    if result.modified_count != 1:
        raise HTTPException(409, "attendance record changed; retry the request")

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated.pop("_id", None)

    for field in ["punch_in", "punch_out"]:
        value = updated.get(field)
        updated[field] = (
            int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)
            if value else None
        )

    for entry in updated.get("history", []):
        at = entry.get("at")
        if at:
            entry["at"] = int(
                at.replace(tzinfo=timezone.utc).timestamp() * 1000
            )

    return updated




@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    #Just like /employees, these currently accept invalid values such as page=0 and page_size=500 unless you add validation. Since you want easy fixes without new imports, we can reuse Query
    page: int = Query(default=1, ge=1),  #page must be at least 1.
    page_size: int = Query(default=20, ge=1, le=100)  #page_size must be between 1 and 100.
):
    for value in [date_from, date_to]:
        if value is not None:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail="Dates must use YYYY-MM-DD format"
            )

    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must be before or equal to date_to"
    )

    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        allowed_statuses = [
        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
    ]
        if status not in allowed_statuses:
            raise HTTPException(422, "invalid attendance status") #Without this check, a request with an unsupported status silently returns an empty list instead of the required 422.

        q["status"] = status
 
    total = db.attendance_logs.count_documents(q)

    page_docs = list(
        db.attendance_logs.find(q, {"_id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
)

    for d in page_docs:
        d.setdefault("history", [])
        d.setdefault("half_day", False)
        
        d["punch_in"] = int(d["punch_in"].replace(tzinfo=timezone.utc).timestamp() * 1000) if d.get("punch_in") else None
        d["punch_out"] = int(d["punch_out"].replace(tzinfo=timezone.utc).timestamp() * 1000) if d.get("punch_out") else None
#The API loads every matching attendance record into Python memory before sorting and paginating. The contract expects this endpoint to handle approximately 100,000 records efficiently.
#- count_documents(q) returns the total matching records without loading them all.
#- .sort() applies the required ordering: date descending, then employee code ascending.
#- .skip() and .limit() retrieve only the requested page.
#- history and half_day defaults handle legacy documents.
#- The timestamp conversions ensure the punch fields are returned as epoch milliseconds.
#The last loop handles only the two punch fields. The complete endpoint still needs conversion of history[].at, nested history[].changes, and other timestamp fields to satisfy the full contract. We can address that separately.
    return {
        "items": page_docs,
        "total": total,
        "page": page,
        "page_size": page_size,
}



@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(
    emp_code: str,
    month: str = Query(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$"
    )
):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")

    year, month_num = map(int, month.split("-"))
    month_start = date(year, month_num, 1)

    if month_num == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_num + 1, 1)

    month_end = next_month - timedelta(days=1)

    joined_on = emp["joined_on"]
    if isinstance(joined_on, str):
        joined_on = date.fromisoformat(joined_on)

    # Count weekdays from the employee's joining date.
    working_days = 0
    current = max(month_start, joined_on)

    while current <= month_end:
        if current.weekday() < 5:
            working_days += 1
        current += timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": month_start.isoformat(),
                    "$lt": next_month.isoformat()
                }
            }
        },
        {
            "$addFields": {
                "_attendance_day": {
                    "$dateFromString": {
                        "dateString": "$date",
                        "format": "%Y-%m-%d"
                    }
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {"$gte": [
                                        {"$dayOfWeek": "$_attendance_day"}, 2
                                    ]},
                                    {"$lte": [
                                        {"$dayOfWeek": "$_attendance_day"}, 6
                                    ]}
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                            1,
                            0
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                }
            }
        }
    ]

    results = list(db.attendance_logs.aggregate(pipeline))
    stats = results[0] if results else {}

    present_days = stats.get("present_days", 0)

    attendance_pct = None
    if working_days > 0:
        attendance_pct = float(
            (
                Decimal(str(present_days)) * Decimal("100")
                / Decimal(working_days)
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )
        )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": stats.get("leave_days", 0),
        "late_count": stats.get("late_count", 0),
        "total_late_minutes": stats.get("total_late_minutes", 0),
        "total_overtime_minutes": stats.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct
    }


@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$"
    ),
    department: Optional[str] = None
):
    year, month_num = map(int, month.split("-"))
    month_start = date(year, month_num, 1)

    if month_num == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_num + 1, 1)

    month_end = next_month - timedelta(days=1)

    employee_match = {
        "joined_on": {"$lte": month_end.isoformat()}
}

    if department is not None:
        employee_match["department"] = department

    pipeline = [
        {"$match": employee_match},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$employee_code"]},
                                    {"$gte": ["$date", month_start.isoformat()]},
                                    {"$lt": ["$date", next_month.isoformat()]}
                                ]
                            }
                        }
                    },
                    {
                        "$addFields": {
                            "_day": {
                                "$dayOfWeek": {
                                    "$dateFromString": {
                                        "dateString": "$date"
                                    }
                                }
                            }
                        }
                    }
                ],
                "as": "logs"
            }
        },
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$addToSet": "$emp_code"},
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$logs.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                    {"$gte": ["$logs._day", 2]},
                                    {"$lte": ["$logs._day", 6]}
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "work_hours_values": {
                    "$push": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$logs.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                    {"$ne": [{"$ifNull": ["$logs.work_hours", None]}, None]}
                                ]
                            },
                            "$logs.work_hours",
                            None
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]},
                            1,
                            0
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$logs.late_minutes", 0]}
                },
                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },
                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "ON_DUTY"]},
                            1,
                            0
                        ]
                    }
                }
            }
        },
        {"$sort": {"_id": 1}}
    ]

    rows = list(db.employees.aggregate(pipeline))

    items = []
    for row in rows:
        hours = [
            value for value in row["work_hours_values"]
            if value is not None
        ]

        avg_work_hours = None
        if hours:
            avg_work_hours = float(
                (
                    sum(Decimal(str(value)) for value in hours)
                    / Decimal(len(hours))
                ).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP
                )
            )

        items.append({
            "department": row["_id"],
            "headcount": len(row["headcount"]),
            "present_days": row["present_days"],
            "avg_work_hours": avg_work_hours,
            "late_count": row["late_count"],
            "total_late_minutes": row["total_late_minutes"],
            "leave_count": row["leave_count"],
            "on_duty_count": row["on_duty_count"]
        })

    return {"month": month, "items": items}



@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None
):
    year, month_num = map(int, month.split("-"))

    if month_num == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_num + 1, 1)

    month_start = date(year, month_num, 1).isoformat()
    next_month_start = next_month.isoformat()

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": month_start,
                    "$lt": next_month_start
                },
                "late_minutes": {"$gt": 0}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"}
            }
        },
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]

    if department is not None:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    rows = list(db.attendance_logs.aggregate(pipeline))

    items = []
    previous_total = None
    current_rank = 0

    for index, row in enumerate(rows, start=1):
        total = row["total_late_minutes"]

        if total != previous_total:
            current_rank = index

        if current_rank > limit:
            break

        items.append({
            "rank": current_rank,
            "emp_code": row["_id"],
            "name": row["employee"]["name"],
            "department": row["employee"]["department"],
            "total_late_minutes": total
        })

        previous_total = total

    return {
        "month": month,
        "items": items
    }



@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to")
):
    if to_date < from_date:
        raise HTTPException(422, "to must be on or after from")

    days_count = (to_date - from_date).days + 1

    if days_count > 92:
        raise HTTPException(422, "date range cannot exceed 92 days")

    if not db.employees.find_one({"department": department}):
        raise HTTPException(404, "department not found")

    pipeline = [
        {
            "$documents": [{}]
        },
        {
            "$set": {
                "days": {
                    "$map": {
                        "input": {"$range": [0, days_count]},
                        "as": "offset",
                        "in": {
                            "$dateAdd": {
                                "startDate": {
                                    "$dateFromString": {
                                        "dateString": from_date.isoformat()
                                    }
                                },
                                "unit": "day",
                                "amount": "$$offset"
                            }
                        }
                    }
                }
            }
        },
        {"$unwind": "$days"},
        {
            "$set": {
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$days",
                        "timezone": "UTC"
                    }
                },
                "is_working_day": {
                    "$and": [
                        {"$gte": [{"$dayOfWeek": "$days"}, 2]},
                        {"$lte": [{"$dayOfWeek": "$days"}, 6]}
                    ]
                }
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"day": "$date"},
                "pipeline": [
                    {
                        "$match": {
                            "department": department,
                            "$expr": {
                                "$lte": ["$joined_on", "$$day"]
                            }
                        }
                    },
                    {"$project": {"_id": 0, "emp_code": 1}}
                ],
                "as": "active_employees"
            }
        },
        {
            "$set": {
                "headcount": {"$size": "$active_employees"},
                "employee_codes": {
                    "$map": {
                        "input": "$active_employees",
                        "as": "employee",
                        "in": "$$employee.emp_code"
                    }
                }
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {
                    "day": "$date",
                    "codes": "$employee_codes"
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$date", "$$day"]},
                                    {"$in": ["$emp_code", "$$codes"]}
                                ]
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"]
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {"$eq": ["$half_day", True]},
                                                0.5,
                                                1
                                            ]
                                        },
                                        0
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$gt": [
                                                {"$ifNull": ["$late_minutes", 0]},
                                                0
                                            ]
                                        },
                                        1,
                                        0
                                    ]
                                }
                            }
                        }
                    }
                ],
                "as": "daily_metrics"
            }
        },
        {
            "$set": {
                "present_count": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$daily_metrics.present_count", 0]},
                        0
                    ]
                },
                "late_count": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$daily_metrics.late_count", 0]},
                        0
                    ]
                }
            }
        },
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]}
                            ]
                        },
                        {
                            "$round": [
                                {"$divide": ["$present_count", "$headcount"]},
                                4
                            ]
                        },
                        None
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"days": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {
                            "documents": [-6, 0]
                        }
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": 1,
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": {
                    "$cond": [
                        {"$ne": ["$moving_avg_7d", None]},
                        {"$round": ["$moving_avg_7d", 4]},
                        None
                    ]
                }
            }
        },
        {"$sort": {"date": 1}}
    ]

    items = list(db.aggregate(pipeline))

    return {
        "department": department,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "items": items
    }


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    allowed = [
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend"
    ]

    if endpoint not in allowed:
        raise HTTPException(422, "invalid endpoint")

    if endpoint == "attendance_list":
        query = {}

        if emp_code:
            query["emp_code"] = emp_code
        if date_from:
            query["date"] = {"$gte": date_from.isoformat()}
        if date_to:
            query.setdefault("date", {})["$lte"] = date_to.isoformat()
        if status:
            query["status"] = status

        explanation = db.command(
            "explain",
            {
                "find": "attendance_logs",
                "filter": query,
                "sort": {"date": -1, "emp_code": 1},
                "skip": (page - 1) * page_size,
                "limit": page_size
            },
            verbosity="executionStats"
        )
        collection = "attendance_logs"

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(422, "emp_code and month are required")

        year, month_num = map(int, month.split("-"))
        start = date(year, month_num, 1)
        end = date(year + (month_num == 12), month_num % 12 + 1, 1)

        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {
                        "$gte": start.isoformat(),
                        "$lt": end.isoformat()
                    }
                }
            },
            {"$sort": {"date": 1}}
        ]

        explanation = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            verbosity="executionStats"
        )
        collection = "attendance_logs"

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(422, "month is required")

        year, month_num = map(int, month.split("-"))
        start = date(year, month_num, 1).isoformat()
        end = date(year + (month_num == 12), month_num % 12 + 1, 1).isoformat()

        pipeline = [
            {
                "$match": {
                    **({"department": department} if department else {}),
                    "joined_on": {"$lt": end}
                }
            },
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "logs"
                }
            }
        ]

        explanation = db.command(
            "explain",
            {
                "aggregate": "employees",
                "pipeline": pipeline,
                "cursor": {}
            },
            verbosity="executionStats"
        )
        collection = "employees"

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(422, "month is required")

        year, month_num = map(int, month.split("-"))
        start = date(year, month_num, 1).isoformat()
        end = date(year + (month_num == 12), month_num % 12 + 1, 1).isoformat()

        pipeline = [
            {
                "$match": {
                    "date": {"$gte": start, "$lt": end},
                    "late_minutes": {"$gt": 0}
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"}
                }
            },
            {"$sort": {"total_late_minutes": -1, "_id": 1}},
            {"$limit": limit}
        ]

        explanation = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            verbosity="executionStats"
        )
        collection = "attendance_logs"

    else:
        if not department or not from_date or not to_date:
            raise HTTPException(422, "department, from and to are required")

        if to_date < from_date or (to_date - from_date).days + 1 > 92:
            raise HTTPException(422, "invalid date range")

        pipeline = [
            {
                "$match": {
                    "department": department,
                    "joined_on": {"$lte": to_date.isoformat()}
                }
            },
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "logs"
                }
            }
        ]

        explanation = db.command(
            "explain",
            {
                "aggregate": "employees",
                "pipeline": pipeline,
                "cursor": {}
            },
            verbosity="executionStats"
        )
        collection = "employees"





    return Response(
        content=dumps({
            "endpoint": endpoint,
            "collection": collection,
            "explain": explanation
    }),
        media_type="application/json"
)





# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
