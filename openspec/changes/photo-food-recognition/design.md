## Context

The existing nutrition MVP stores user-entered values in PostgreSQL and the application already has authenticated RustFS object storage plus an OpenAI-compatible Qwen client configuration. There is no vision-model adapter or image-to-nutrition workflow. See `proposal.md` and the two delta specs for the observable behavior.

## Goals / Non-Goals

**Goals:**

- Keep photo recognition preview-only until the user explicitly confirms it.
- Keep images, previews, and resulting records scoped to the authenticated account.
- Reuse the existing RustFS and nutrition-record paths instead of introducing a second food-record format.
- Make model output parseable, validated, editable, and clearly labeled as an estimate.

**Non-Goals:**

- Medical nutrition advice, dietary diagnosis, barcode lookup, food database matching, or automatic daily targets.
- Background recognition jobs or multi-image meal albums in this MVP.
- Treating model estimates as authoritative nutrition facts.

## Decisions

1. **Use a persisted preview row.** Store the account owner, RustFS object key, content type, preview status, and normalized model payload in `kh_nutrition_photo`. This prevents an untrusted browser from inventing a preview ID or confirming another account's result, and lets a refresh continue a pending preview. Cancellation and confirmation lock the preview row while checking/updating status, so concurrent requests cannot both win. Cancellation marks the preview cancelled before removing the object; if object cleanup fails, a repeated cancellation can retry cleanup without creating a nutrition record. Confirmed previews cannot be cancelled.

2. **Attach confirmed records to the source photo.** Add nullable `source` and `photo_id` fields to `kh_nutrition_record`. Manual records keep `source = manual`; confirmation sets `source = photo` and the preview ID. Existing list, edit, delete, and daily-total behavior remains unchanged.

3. **Call a dedicated configured vision model.** Add optional `QWEN_VISION_MODEL_NAME` with no default model selected; the operator must explicitly configure a model supported by the existing Qwen-compatible endpoint. The adapter sends a data URL and a strict JSON-only extraction prompt. If configuration, provider response, or parsing is invalid, return a clear error and keep the preview free of nutrition records.

4. **Validate twice.** Normalize and validate model output before returning the preview, then validate user-edited confirmation payloads with the existing nutrition schema rules inside one database transaction. The confirmation endpoint never trusts an owner ID from the client.

5. **Proxy private image reads through the authenticated API.** The API returns an image endpoint and requires the normal Bearer token. Before reading from RustFS, it loads the preview by both preview ID and authenticated user ID. The frontend fetches the image with its auth header and displays a temporary Blob URL, revoking it when the preview changes or the account logs out. This avoids exposing presigned storage URLs and supports deployments where the browser cannot resolve the internal RustFS hostname.

6. **Keep the frontend in the existing nutrition page.** Add a photo-upload section, editable preview rows, explicit estimate labeling, confirm/cancel states, and request errors without changing the existing manual-entry form.

## Risks / Trade-offs

- **[Vision models can misidentify food or portions]** → Label every preview as estimated, require review, and never auto-save.
- **[Provider response formats can vary]** → Require JSON in the prompt and use bounded parsing with schema validation; reject malformed output.
- **[Private images can leak through browser or storage URLs]** → Keep buckets private, scope the proxy lookup by owner before storage access, return `private, no-store` with `nosniff`, and revoke frontend Blob URLs when no longer needed.
- **[A failed confirmation could create only some records]** → Insert all confirmed records and update preview status in one transaction.
- **[Optional vision configuration may be absent in existing deployments]** → Return a clear 503-style configuration error while leaving manual nutrition tracking available.

## Migration Plan

1. Apply the additive migration that creates `kh_nutrition_photo` and adds nullable source/photo fields and constraints to `kh_nutrition_record`.
2. Set `QWEN_VISION_MODEL_NAME` in the backend environment and restart the API.
3. Verify preview, edit, confirm, failure, and account-isolation flows.
4. Rollback, if required, by removing only the new photo table and the new nullable nutrition-record fields in a reviewed migration; do not remove existing manual records.
