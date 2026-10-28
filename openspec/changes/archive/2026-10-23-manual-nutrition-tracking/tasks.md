## 1. Persistence and API

- [x] 1.1 Add nutrition record model and register it for SQLAlchemy metadata loading.
- [x] 1.2 Add Pydantic create/update/response/daily-summary schemas with strict field, date, meal, and nutrient validation.
- [x] 1.3 Add an idempotent PostgreSQL migration for the account-owned nutrition table, constraints, and user/date index.
- [x] 1.4 Implement authenticated create, daily list/summary, update, and delete endpoints with owner-scoped queries.
- [x] 1.5 Add backend tests for validation, create/update/delete, daily totals, empty dates, and cross-account isolation.

## 2. Nutrition Management UI

- [x] 2.1 Add an accessible nutrition page and navigation entry with selected-date control, manual-entry form, totals, and record list.
- [x] 2.2 Implement create/edit/delete interactions using the authenticated API helper and refresh the selected day's data after mutations.
- [x] 2.3 Add responsive styles and explicit loading, empty, validation, and request-error states.
- [x] 2.4 Add frontend tests for daily totals, escaped record rendering, date handling, and form payload validation.

## 3. Verification and Handoff

- [x] 3.1 Run nutrition tests and the relevant backend/frontend regression suites; inspect the scoped diff.
- [x] 3.2 Validate OpenSpec artifacts and document the manual database migration and user acceptance steps.
