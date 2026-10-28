## Why

Saved plans currently cannot be used to log completed workouts, so the dashboard has no trustworthy training history or progress statistics. This change closes that gap with account-scoped workout records tied to saved plans where applicable.

## What Changes

- Add a workout lifecycle for starting and completing a session from a saved plan, recording performed exercises, sets, reps, load, duration, and optional body weight.
- Add account-scoped workout history and deletion, with statistics derived from completed records.
- Replace the dashboard's training placeholder metrics with real weekly count, streak, duration, volume, and recorded body-weight change.
- Add a migration and regression tests; retain existing plan generation and CRUD behavior.

## Capabilities

### New Capabilities
- `training-checkin-statistics`: Start, complete, review, and delete account-owned workout records, and display derived progress statistics.

### Modified Capabilities

## Impact

- Backend: training API, SQLAlchemy model/schema/service, PostgreSQL migration, router/model registration.
- Frontend: training page workout execution/history and dashboard statistics.
- Tests: ownership, lifecycle, validation, aggregation, and UI interaction coverage.
