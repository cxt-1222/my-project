## Purpose

This capability lets authenticated users use a meal photo to create an editable nutrition-record draft, review the model output, and save only the values they explicitly confirm.

## ADDED Requirements

### Requirement: Users can preview nutrition extracted from a meal photo
The system MUST let an authenticated user upload a supported meal image and request a recognition preview. Before upload, the user MUST be told that the image is sent to the configured vision provider and stored in the application's private object storage. The system MUST validate the image type and size, associate the uploaded image and preview with the authenticated account, and return one or more recognized food items with their estimated meal, amount, unit, calories, protein, carbohydrate, and fat values. Recognition output MUST be labeled as an estimate and MUST NOT be presented as verified nutrition data.

#### Scenario: Create a recognition preview
- **WHEN** an authenticated user uploads a valid JPEG, PNG, or WebP meal image and a configured vision model returns valid food items
- **THEN** the system stores the private image and preview under that account and returns an editable preview without creating nutrition records

#### Scenario: Disclose image processing before upload
- **WHEN** a user views the meal-photo upload control
- **THEN** the interface states that the image will be sent to the configured vision provider and stored in private object storage

#### Scenario: Reject an unsupported or oversized image
- **WHEN** a user uploads a non-image file, an unsupported image type, or an image larger than the supported limit
- **THEN** the system rejects the upload without creating a preview or nutrition record

#### Scenario: Handle unavailable or invalid recognition
- **WHEN** the vision model is not configured, fails, times out, or returns no parseable food items
- **THEN** the system returns an explicit error and does not create nutrition records

#### Scenario: Keep previews private
- **WHEN** a user requests or accesses a preview owned by another account or a nonexistent preview
- **THEN** the system returns not found and does not reveal the image or recognition values

### Requirement: Users can retrieve only their own private meal photo
The system MUST require authentication to retrieve a stored meal photo and MUST verify that the preview belongs to the authenticated user before reading the object from private storage. The response MUST use the stored image content type, disable shared caching, and prevent MIME sniffing.

#### Scenario: Retrieve an owned meal photo
- **WHEN** an authenticated user requests the image for their own active or confirmed preview
- **THEN** the system streams the image through the API with private no-store caching and `X-Content-Type-Options: nosniff`

#### Scenario: Reject another user's meal photo before storage access
- **WHEN** an authenticated user requests an image for a preview owned by another account or a nonexistent preview
- **THEN** the system returns not found without requesting the image object from private storage

### Requirement: Users can edit and confirm photo recognition results
The system MUST let the owner edit the returned food items and confirm them for saving. Confirmation MUST validate the edited values using the same nutrition rules as manual records, create one nutrition record per confirmed food item, associate those records with the source photo, and mark the preview as confirmed. Uploading or previewing a photo MUST NOT save records automatically.

#### Scenario: Confirm edited recognition results
- **WHEN** the preview owner submits valid edited food items, a selected date, and meal values for confirmation
- **THEN** the system persists the edited items as account-owned nutrition records associated with the source photo

#### Scenario: Reject invalid confirmation values
- **WHEN** confirmation contains blank names, invalid meals or dates, nonpositive amounts, negative nutrients, or no food items
- **THEN** the system rejects confirmation and leaves the preview unconfirmed without creating partial records

#### Scenario: Prevent repeated confirmation
- **WHEN** a user confirms an already confirmed preview
- **THEN** the system rejects the request and does not create duplicate nutrition records

#### Scenario: Cancel an unconfirmed preview
- **WHEN** the owner cancels a preview that has not been confirmed
- **THEN** the system removes the preview from future access and deletes its stored image when object storage is available

#### Scenario: Serialize cancellation and confirmation
- **WHEN** the owner submits cancellation and confirmation for the same pending preview concurrently
- **THEN** the system serializes both state transitions so only one can succeed; a confirmed preview cannot later be cancelled, and a cancelled preview cannot create nutrition records

