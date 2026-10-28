## Context

The project already has account-scoped saved training plans and a dashboard, but no training-record model or statistics API. PostgreSQL schema changes are delivered as explicit SQL migrations, which the operator applies during acceptance.

## Goals / Non-Goals

**Goals:**
- Provide a server-persisted start/complete lifecycle for workouts based on saved plan days.
- Store performed data separately from the reusable plan definition.
- Derive history and dashboard metrics from completed records, scoped by authenticated user.

**Non-Goals:**
- Nutrition logging, meal recognition, calendar scheduling, social sharing, or coach/admin analytics.
- Editing saved plans as a side effect of workout completion.
- Estimating volume for exercises whose load or repetition count is not numeric.

## Decisions

- Add `kh_training_record` with owner, nullable plan reference, plan-day label, status, timestamps, duration, optional body weight, and JSONB performed exercises. This preserves the reusable plan and captures actual performance.
- Starting a workout snapshots the selected plan day's exercise names and prescriptions into an in-progress record. Completion replaces only the performed values after schema validation.
- Workout duration is derived server-side from the persisted start timestamp and completion timestamp; clients cannot submit or override elapsed duration.
- Expose `/training/workouts` lifecycle/history/delete routes and `/training/stats` for derived summaries. Ownership always comes from JWT; queries filter by `user_id`.
- Calculate statistics from completed records in the service layer using explicit time boundaries; do not persist aggregates that could become stale after deletion.
- Use a migration with foreign keys and constraints. Do not rely on startup `create_all` to mutate deployed databases.
- Build the MVP into the existing training page and dashboard, following the current vanilla JavaScript patterns.

## Risks / Trade-offs

- JSONB exercise snapshots are flexible but make database-level per-set analytics harder → validate the structure at the API boundary and calculate MVP totals from snapshots.
- Local timezone affects calendar week/streak boundaries → use the server's configured local date consistently and test boundary logic.
- In-progress records can be abandoned → expose them with explicit resume/cancel actions; cancelled and in-progress records do not count toward statistics.

## Migration Plan

1. Apply the new SQL migration to create the workout-record table.
2. Deploy backend routes and frontend controls.
3. Verify start, completion, account isolation, deletion, and dashboard recalculation.
4. Rollback by removing the new routes/UI and, only if data disposal is intended, dropping the new table after backup.
