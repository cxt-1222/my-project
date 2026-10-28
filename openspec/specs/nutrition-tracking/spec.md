# nutrition-tracking Specification

## Purpose

This capability lets each authenticated user manually record foods and their nutrition values, manage those records, and review daily intake totals without implying that values were automatically verified or estimated.

## Requirements

### Requirement: Users can create and manage private nutrition records
The system MUST let an authenticated user create, list, update, and delete nutrition records belonging to that user. Each record MUST include a calendar date, meal category, food name, amount and unit, calories in kilocalories, and protein, carbohydrate, and fat in grams. Nutrition values MUST be supplied by the user; the system MUST NOT silently infer or replace them. A request MUST NOT be able to choose or change its owner. Reading or modifying another user's record MUST return not found.

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

#### Scenario: Prevent cross-account access
- **WHEN** a user attempts to read, update, or delete another user's record or a nonexistent record
- **THEN** the system returns not found and leaves all records unchanged

### Requirement: Users can view daily nutrition totals
The system MUST provide the selected calendar date's saved food records and totals for calories, protein, carbohydrates, and fat, calculated only from that user's records for that date. An empty date MUST return zero totals and an empty record list. Editing or deleting a record MUST be reflected in the next summary response.

#### Scenario: Calculate totals for a day
- **WHEN** an authenticated user requests a daily summary for a date with nutrition records
- **THEN** the system returns that date's records and sums each saved calories and macronutrient value for that account

#### Scenario: Return an empty-day summary
- **WHEN** an authenticated user requests a date with no nutrition records
- **THEN** the system returns an empty record list and zero for each daily total

#### Scenario: Isolate daily totals by account
- **WHEN** multiple accounts have records on the same date
- **THEN** each account's summary includes only its own records

#### Scenario: Refresh totals after record changes
- **WHEN** a user edits or deletes a nutrition record and requests that date's summary again
- **THEN** the returned records and totals reflect the persisted change
