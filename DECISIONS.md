# DECISIONS.md

## 1. Indexes

I added a unique index on `emp_code` in the employees collection to make sure the same employee code cannot be registered twice.

In the attendance collection, I added a unique compound index on `emp_code` and `date`. This ensures that an employee can have only one attendance record per day.

I also added an index on `date` (descending) and `emp_code` (ascending) to support attendance listing and sorting. Another index on `department` and `joined_on` helps with employee filtering.

I did not add an index only on `late_minutes` because the leaderboard also filters attendance by month and groups records by employee. I would check the actual query plans before deciding whether another index is needed.

## 2. Handling Simultaneous Punch-ins

Two requests for the same employee could arrive at almost the same time. Both requests might check for an existing record before either one inserts it.

To handle this, I rely on the unique compound index instead of depending only on the initial check. MongoDB allows only one insert, and the other request gets a duplicate-key error. My code catches this error and returns `409 Conflict`.

This approach prevents duplicate attendance records even when requests arrive simultaneously.

## 3. Leaderboard Ties

If two employees have the same total late minutes, they receive the same rank. The next rank is skipped, following competition-style ranking.

For example, if two employees share rank 1, the next employee receives rank 3.

The limit is applied after calculating the ranks in the application code. This means that if multiple employees tie at the cutoff rank, all of them are included in the response.

## 4. Department Headcount

The department summary starts with the employees collection and then looks up their attendance records for the selected month.

I chose this approach because headcount should not depend on whether an employee has attendance records. Employees who joined on or before the last day of the selected month are counted, even if they have no attendance logs.

The aggregation preserves employees with no matching attendance records, and the final headcount is calculated using unique employee codes.

## 5. Handling Future Growth

If the data grows by 100 times, I would first check which queries are taking the most time and examine their execution statistics.

I would focus on the attendance list, monthly analytics, leaderboard, and department summary. I would compare the number of documents examined with the number of results returned, then improve the indexes or aggregation pipelines where needed.

I would make changes based on actual query performance instead of adding indexes without checking whether they help.

## 6. Attendance Regularization

For attendance regularization, I added a PATCH endpoint that allows selected attendance fields to be corrected without replacing the entire record.

The endpoint validates the requested changes, recalculates the related attendance values, and records the reason, person making the change, timestamp, and changed fields in the history.

I tested the endpoint and received `200 OK`. The update also uses a conditional database update to detect certain concurrent changes and return `409 Conflict` rather than silently overwriting a record that has changed.

Further concurrency testing is still needed to confirm this behaviour under simultaneous requests.

## 7. Query Explain Endpoint

I added an explain endpoint to inspect MongoDB query execution statistics for the supported API operations.

These statistics can help identify which indexes MongoDB uses and how many documents it examines. The explain pipelines still need to be aligned with the actual analytics queries before their results can be treated as a complete explanation of those endpoints.

My next step is to make the explain pipelines match the real queries and use the results to identify performance improvements.