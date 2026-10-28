## 1. Recognition persistence and model boundary

- [x] 1.1 Add the nutrition-photo model, register it with SQLAlchemy metadata, and add the additive PostgreSQL migration for photo previews and nutrition-record source association.
- [x] 1.2 Add strict schemas for photo preview responses, normalized food items, and confirmation requests.
- [x] 1.3 Add the configured vision-model adapter with bounded image validation, JSON extraction, and explicit provider/configuration errors.
- [x] 1.4 Implement authenticated preview, retrieval, cancellation, and confirmation endpoints with RustFS storage, an owner-checked authenticated image proxy, and transactional record creation.
- [x] 1.5 Add backend tests for image validation, model parsing, preview-not-saved behavior, confirmation, duplicate confirmation, failure handling, and cross-account isolation.

## 2. Nutrition page photo workflow

- [x] 2.1 Add a meal-photo upload and estimate notice to the nutrition page without removing the manual-entry workflow.
- [x] 2.2 Add editable recognition-result rows and explicit confirm/cancel behavior that calls the preview and confirmation APIs.
- [x] 2.3 Add loading, empty, unsupported-file, unavailable-model, parse-error, and confirmation-error states with responsive styles.
- [x] 2.4 Add frontend tests for escaped model text, editable item payloads, cancel behavior, and no-auto-save state.

## 3. Verification and handoff

- [x] 3.1 Run backend and frontend regression tests, statically inspect migration syntax without applying it, and inspect the scoped diff.
- [x] 3.2 Document the vision-model environment variable, migration command, and photo-recognition acceptance steps.
