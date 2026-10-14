

This document records the defects I found while reviewing and testing the Employee Attendance & Analytics API. It explains what was wrong, how I noticed it, and how I fixed it. Some items still need further testing.

## 1. Defects Found and Fixes

### 1. Duplicate Employee Codes

**Where:** `create_employee()`

**What was wrong:** Two requests could try to create the same employee code at the same time.

**How I noticed it:** Sending simultaneous requests with the same `emp_code` could cause a duplicate database entry attempt.

**How I fixed it:** Added a unique index on `emp_code` and handled `DuplicateKeyError` by returning `409 Conflict`.

### 2. Employee Input Validation

**Where:** `EmployeeIn` model

**What was wrong:** Employee fields needed validation for their formats and allowed lengths.

**How I noticed it:** Invalid employee codes, malformed emails, empty names, and invalid shift times could be submitted.

**How I fixed it:** Added Pydantic validation rules for employee fields and shift times. More boundary testing is still needed.

### 3. Joining Date Format

**Where:** `create_employee()`

**What was wrong:** The Python `date` value needed to be converted to the format expected by the database.

**How I noticed it:** Creating an employee required checking the stored joining date and response.

**How I fixed it:** Converted `joined_on` to an ISO-format date string before inserting the employee.

### 4. Employee Creation Timestamp

**Where:** `create_employee()`

**What was wrong:** The creation timestamp needed consistent UTC handling and the required response format.

**How I noticed it:** Inspecting `created_at` in MongoDB and the API response.

**How I fixed it:** Stored `created_at` as a UTC datetime. Returning it in the required epoch-millisecond format still needs verification.

### 5. Employee Pagination and Filtering

**Where:** `list_employees()`

**What was wrong:** Pagination and total counts needed to respect the selected filters.

**How I noticed it:** Requesting later pages or filtering employees by department and comparing the results.

**How I fixed it:** Corrected the skip calculation and used the same filter for the total count.

### 6. Employee Sorting

**Where:** `list_employees()`

**What was wrong:** Employee results needed a consistent order across pages.

**How I noticed it:** Requesting multiple pages and checking the order of employee codes.

**How I fixed it:** Added ascending sorting by `emp_code`.

### 7. Missing Punch-in Timestamp

**Where:** `punch_in()`

**What was wrong:** A missing `punched_at` value could cause an error during timestamp conversion.

**How I noticed it:** Sending a punch-in request without `punched_at`.

**How I fixed it:** Used the current time when the timestamp is not provided.

### 8. Punch-in Timezone Handling

**Where:** `punch_in()`

**What was wrong:** Timestamp conversion could depend on the server's local timezone.

**How I noticed it:** Testing epoch-millisecond timestamps with explicit timezone handling.

**How I fixed it:** Used timezone-aware datetime conversion and IST for attendance-time calculations.

### 9. Invalid Punch-in Timestamps

**Where:** `punch_in()`

**What was wrong:** Timestamps supplied in seconds instead of milliseconds could be interpreted incorrectly.

**How I noticed it:** Submitting timestamps in seconds or values outside the supported range.

**How I fixed it:** Added a minimum timestamp check and error handling for invalid ranges. More edge-case testing is still needed.

### 10. Unknown Employee During Punch-in

**Where:** `punch_in()`

**What was wrong:** Punching in with a nonexistent employee code could lead to an error instead of a clear response.

**How I noticed it:** Sending a punch-in request with an unknown `emp_code`.

**How I fixed it:** Added an employee existence check that returns `404 Not Found`.

### 11. Duplicate Attendance Records

**Where:** `punch_in()` and database indexes

**What was wrong:** Repeated or simultaneous punch-in requests could attempt to create duplicate attendance records.

**How I noticed it:** Repeating a punch-in for the same employee and date.

**How I fixed it:** Added a unique compound index on `emp_code` and `date`, handled duplicate-key errors, and returned `409 Conflict`. A repeated punch-in was tested successfully; a concurrent-request test remains.

### 12. IST Attendance Dates and Late Minutes

**Where:** `punch_in()`

**What was wrong:** Attendance dates and late-minute calculations needed to handle IST and overnight shifts correctly.

**How I noticed it:** Testing punches around midnight and near the 10-minute grace-period boundary.

**How I fixed it:** Added IST attendance-date handling, overnight-shift logic, and the 10-minute late-arrival grace rule. Broader testing is still needed.

### 13. Unknown Employee or Missing Punch-in During Punch-out

**Where:** `punch_out()`

**What was wrong:** The endpoint needed to handle unknown employees and missing matching punch-ins safely.

**How I noticed it:** Trying to punch out with an unknown employee or without a matching punch-in.

**How I fixed it:** Added explicit checks that return `404 Not Found`. These cases still need dedicated tests.

### 14. Invalid Punch-out Times

**Where:** `punch_out()`

**What was wrong:** Invalid punch-out times could produce negative or unreasonable work durations.

**How I noticed it:** Submitting a punch-out at or before punch-in, or more than 24 hours later.

**How I fixed it:** Added checks requiring positive elapsed time and limiting the duration to 24 hours. Dedicated tests are still needed.

### 15. Work-hour Rounding

**Where:** `compute_work_hours()`

**What was wrong:** Work hours needed consistent decimal rounding using the assignment's required rule.

**How I noticed it:** Testing durations near half-up rounding boundaries.

**How I fixed it:** Used `Decimal` and `ROUND_HALF_UP` to round work hours to two decimal places.

### 16. Timezone Error in Work-hour Calculation

**Where:** `compute_work_hours()`

**What was wrong:** Python could not subtract a timezone-naive datetime from a timezone-aware datetime.

**How I noticed it:** The PATCH request returned `500 Internal Server Error` with `TypeError: can't subtract offset-naive and offset-aware datetimes`.

**How I fixed it:** Normalized both datetimes to UTC before subtraction. The PATCH request then returned `200 OK`. This assumes naive stored datetimes represent UTC.

### 17. Overnight Overtime Calculation

**Where:** `compute_overtime()`

**What was wrong:** For overnight shifts, the shift-end time belongs to the following calendar day.

**How I noticed it:** Checking overtime calculations for shifts that cross midnight.

**How I fixed it:** Added logic to move the shift-end time to the next day when the shift is overnight. Overtime is counted only when it reaches 30 minutes. Further testing is needed.

### 18. Late-minute Calculation

**Where:** `compute_late_minutes()`

**What was wrong:** Late-arrival calculations needed to apply the 10-minute grace period correctly.

**How I noticed it:** Comparing punches within the grace period with punches just beyond it.

**How I fixed it:** Corrected the elapsed-time calculation and applied the 10-minute grace rule.

### 19. Attendance Date Validation

**Where:** `list_attendance()`

**What was wrong:** Invalid date strings and reversed date ranges needed to be rejected.

**How I noticed it:** Sending `date_from=abc` or a start date later than the end date.

**How I fixed it:** Added date-format and range validation that returns `422 Unprocessable Entity`. Impossible calendar dates and combined-filter cases need further testing.

### 20. Attendance Filtering, Sorting, and Pagination

**Where:** `list_attendance()`

**What was wrong:** Filters, total counts, sorting, and pagination needed to work together correctly.

**How I noticed it:** Combining employee, date-range, and status filters and checking the returned records and total.

**How I fixed it:** Added database-level filtering, counting, sorting, skipping, and limiting. More combined-filter and sorting tests are needed.

### 21. Loading Too Many Attendance Records

**Where:** `list_attendance()`

**What was wrong:** Loading all matching attendance records into Python before sorting and pagination would use unnecessary memory.

**How I noticed it:** Reviewing the query and considering its behaviour with a large dataset.

**How I fixed it:** Moved sorting and pagination into the MongoDB query so only the requested page is loaded.

### 22. Attendance Response Format

**Where:** `list_attendance()`

**What was wrong:** The response could expose MongoDB's internal ID or return timestamps in the wrong format.

**How I noticed it:** Inspecting the JSON response for `_id`, punch timestamps, and missing legacy fields.

**How I fixed it:** Excluded `_id`, converted punch times to epoch milliseconds, and added defaults for `history` and `half_day`. Other timestamp fields still need review.

### 23. Attendance Regularization

**Where:** `regularize_attendance()`

**What was wrong:** Attendance corrections needed validation, recalculation of derived fields, and a record of who made each change and why.

**How I noticed it:** Testing a PATCH request and checking the updated attendance record and history.

**How I fixed it:** Added the PATCH endpoint with input validation, recalculation of derived fields, and a history entry. The successful request returned `200 OK`, but all edge cases still need testing.

### 24. Concurrent Attendance Corrections

**Where:** `regularize_attendance()`

**What was wrong:** Concurrent corrections could overwrite each other or lose history entries.

**How I noticed it:** This issue was identified during code review; simultaneous corrections have not yet been tested.

**How I fixed it:** Added a conditional database update that returns `409 Conflict` if the expected record state no longer matches. Concurrent behaviour still needs verification.

### 25. Department Headcount

**Where:** `department_summary()`

**What was wrong:** Employees without attendance records could be omitted from department headcount.

**How I noticed it:** Checking how the aggregation handles an employee who joined before the end of the month but has no attendance logs.

**How I fixed it:** Started the aggregation from employees and preserved employees without matching attendance records. A dedicated test is still needed.

### 26. Leaderboard Ties

**Where:** `late_leaderboard()`

**What was wrong:** Employees with equal late-minute totals needed the same rank, and employees tied at the cutoff needed to be included.

**How I noticed it:** Reviewing the ranking logic and identifying the need for a tie-at-cutoff test.

**How I fixed it:** Implemented competition-style ranking and applied the cutoff after ranking. The tie-at-cutoff case still needs a dedicated test.

### 27. Department Trend and Missing Dates

**Where:** `department_trend()`

**What was wrong:** The trend needed to include dates without attendance records and calculate a seven-day moving average.

**How I noticed it:** Reviewing the aggregation for date generation and moving-average calculation.

**How I fixed it:** Added date generation, daily metrics, and a seven-day moving-average calculation. Missing-date and calculation tests remain.

### 28. Explain Endpoint

**Where:** `explain_endpoint()`

**What was wrong:** Some explain pipelines do not match the actual analytics queries, so their execution statistics may not represent the real endpoint behaviour.

**How I noticed it:** Comparing the explain pipelines with the actual endpoint filters, lookups, grouping, sorting, and limits.

**How I fixed it:** Identified the mismatches during code review. The explain pipelines still need to be aligned with the real queries.

### 29. Outdated TODO Comments

**Where:** Bottom of `main.py`

**What was wrong:** The TODO section still lists endpoints that have already been implemented.

**How I noticed it:** Reviewing the comments at the bottom of the file.

**How I fixed it:** Identified the outdated comments for cleanup. They still need to be removed or updated.

## 2. Items Reviewed That Were Not Considered Defects

### 1. Decimal Rounding

**Where:** `compute_work_hours()`

**What I checked:** Use of `Decimal` and `ROUND_HALF_UP`.

**Why it is not a defect:** This is intentional because the assignment requires explicit half-up rounding.

### 2. Attendance Unique Compound Index

**Where:** Attendance database indexes.

**What I checked:** One record per employee per attendance date.

**Why it is not a defect:** This is intentional and provides database-level protection against duplicate records.

### 3. Attendance Total Count

**Where:** `list_attendance()`

**What I checked:** Using `count_documents()` separately from the paginated query.

**Why it is not a defect:** This is a reasonable way to return the total number of matching records without loading every record into Python.

### 4. Leaderboard Ranking Cutoff

**Where:** `late_leaderboard()`

**What I checked:** Applying the rank cutoff after calculating competition ranks.

**Why it is not a defect:** This is intentional because employees tied at the cutoff rank must all be included.

### 5. Department Headcount Calculation

**Where:** `department_summary()`

**What I checked:** Starting from employees rather than attendance logs.

**Why it is not a defect:** This is intentional because department headcount must include employees with no attendance records.

### 6. Missing Punch-in Timestamp

**Where:** `punch_in()`

**What I checked:** Using the current time when `punched_at` is omitted.

**Why it is not a defect:** This is expected behaviour when the request does not supply a timestamp.

### 7. No-op Attendance Correction

**Where:** `regularize_attendance()`

**What I checked:** Rejecting a correction that makes no actual change.

**Why it is not a defect:** This is intentional because the contract requires a no-op correction to return `422 Unprocessable Entity`.

### 8. Attendance Date Storage

**Where:** Attendance data model.

**What I checked:** Storing attendance dates as `YYYY-MM-DD` strings.

**Why it is not a defect:** This matches the current data model and supports chronological comparisons when the format is consistent.

