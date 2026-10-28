## MODIFIED Requirements

### Requirement: Users can create and manage private nutrition records
The system MUST let an authenticated user create, list, update, and delete nutrition records belonging to that user. Each record MUST include a calendar date, meal category, food name, amount and unit, calories in kilocalories, and protein, carbohydrate, and fat in grams. Nutrition values MUST be supplied by the user or explicitly confirmed by the user from a photo preview; the system MUST NOT silently infer or replace them. A request MUST NOT be able to choose or change its owner. Photo-confirmed records MUST retain their source-photo association. Reading or modifying another user's record MUST return not found.

#### Scenario: Create a nutrition record
- **WHEN** an authenticated user submits a valid food, date, meal, amount, and nutrition values
- **THEN** the system saves the record under that authenticated account and returns the saved values

#### Scenario: Reject invalid nutrition data
- **WHEN** a request has a blank food name, invalid date or meal, nonpositive amount, negative nutrition values, or fields outside the supported schema
- **THEN** the system rejects the request without persisting a record

#### Scenario: List records for a selected date
- **WHEN** an authenticated user requests nutrition records for a calendar date
- **THEN** the system returns only that user's records for that date in a stable chronological order

#### Scenario: Update or delete an owned record
- **WHEN** an authenticated user updates or deletes one of their records
- **THEN** the system changes or removes only that record and subsequent reads reflect the change

#### Scenario: Preserve photo source on confirmed records
- **WHEN** a user confirms a photo recognition preview and later lists the resulting records
- **THEN** each created record identifies that it came from the confirmed source photo while remaining editable like a manual record

#### Scenario: Prevent cross-account access
- **WHEN** a user attempts to read, update, or delete another user's record or a nonexistent record
- **THEN** the system returns not found and leaves all records unchanged
