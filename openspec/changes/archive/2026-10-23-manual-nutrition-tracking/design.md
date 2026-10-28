## Context

See `proposal.md` for motivation and `specs/nutrition-tracking/spec.md` for observable behavior. The backend uses FastAPI, async SQLAlchemy sessions, Pydantic v2 schemas, and PostgreSQL; authentication derives the owner from `get_current_user`. Database changes are delivered as explicit SQL files under `migrations/`, and users execute those migrations themselves. The frontend is a vanilla JavaScript single-page app with page navigation in `frontend/app.js` and a shared authenticated `request()` helper.

## Goals / Non-Goals

**Goals:**
- Keep nutrition records private to the authenticated account at every read and mutation boundary.
- Make daily totals reproducible from persisted user-entered values.
- Keep manual recording usable without any external food database or AI service.
- Provide visible loading, empty, validation, and error states in the nutrition page.

**Non-Goals:**
- Food-photo upload, OCR/image recognition, automated nutrition estimation, barcode lookup, or meal recommendations.
- Daily calorie/macronutrient targets, charts, or cross-day analytics.
- Automatic execution of PostgreSQL migrations or destructive schema changes.

## Decisions

1. **Use one row per manually entered food.** Store an owner ID, selected calendar date, one of four meal categories (`breakfast`, `lunch`, `dinner`, `snack`), food name, positive amount, unit, calories, protein, carbohydrates, fat, and creation/update timestamps. This keeps the data simple to edit and makes each line item auditable. A meal-level JSON blob was considered but rejected because row-level ownership checks, validation, updates, and totals are easier to enforce and query relationally.

2. **Use PostgreSQL `DATE` for the consumed day and exact numeric columns for user-entered values.** The MVP is organized by a user-selected calendar date rather than time-of-day analytics, so a timezone conversion must not move a record to a neighboring day. Use fixed-precision numeric values for amount and nutrition, and return totals calculated from those persisted values. The frontend can show decimal values without inventing a precision beyond what is saved.

3. **Derive ownership only from authentication and scope every query by `user_id`.** Create requests reject extra fields; update/delete lookup uses both record ID and authenticated owner and returns 404 for missing or foreign records. The client never supplies an authoritative owner ID.

4. **Expose a daily read model with totals and records, plus record CRUD.** `GET /nutrition/daily?date=YYYY-MM-DD` returns an empty list and zero totals for a day without entries. `POST /nutrition/records` creates a row; `PUT` and `DELETE /nutrition/records/{record_id}` edit or remove an owned row. A separate summary-only endpoint was rejected because the page always needs both the rows and their totals.

5. **Add the nutrition page as an independent navigation route.** The page defaults to the browser's local current date, lets the user change dates, enter/edit/delete individual foods, and refreshes both rows and totals after every successful mutation. Keep the API date as `YYYY-MM-DD`; do not convert it through UTC.

6. **Use an explicit, additive SQL migration.** Create `kh_nutrition_record` with constraints for supported meal categories, positive amount, nonnegative nutrient values, owner foreign key, and `(user_id, record_date, created_at, id)` lookup index. The migration is idempotent and contains no seed or data rewrite. Do not run it automatically from application startup.

## Risks / Trade-offs

- **[User-entered values can be inaccurate]** → Label values as manually entered and do not present them as verified or AI-estimated.
- **[Date handling can shift entries across days]** → Persist a `DATE` selected by the client and validate it as a calendar date; avoid timezone conversion for this field.
- **[A missed owner filter could expose private health data]** → Centralize owner-scoped queries and test foreign-owner reads, updates, deletes, and daily totals.
- **[The schema will not exist until the user runs the migration]** → Include the exact migration command and acceptance steps in the final handoff; report that the API requires migration before use.
- **[Frontend `app.js` and shared page files already contain uncommitted work]** → Make narrowly scoped additions, inspect diffs before editing, and do not reset or overwrite unrelated changes.

## Migration Plan

1. Deliver an idempotent SQL migration that creates the nutrition table and owner/date index.
2. The user runs it against the configured PostgreSQL database using the project's existing Docker/psql workflow.
3. Deploy/restart the backend and frontend; verify create, daily read, update, delete, and account isolation.
4. Rollback, if needed, is a separately reviewed SQL operation that drops only the newly created nutrition table; it is not run by the application or this change.
