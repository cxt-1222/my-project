## Purpose

This capability lets users execute saved training plans, keep account-private workout records, and see progress calculated from completed sessions rather than placeholder dashboard values.

## ADDED Requirements

### Requirement: Users can record completed workouts from saved plans
The system MUST let an authenticated user start a workout from one of their saved plans and complete it with the performed exercises, set counts, repetitions, loads, and optional body weight. Starting a workout MUST create an in-progress record; completing it MUST persist the final values, calculate duration from the server-side start and completion timestamps, and mark it completed. The plan template MUST remain unchanged; a completed record linked to a plan/day is the completion status for that workout instance.

#### Scenario: Start a planned workout
- **WHEN** a user selects a training day from a saved plan and starts it
- **THEN** the system creates an in-progress workout linked to that plan and day, containing that day's planned exercises

#### Scenario: Complete a workout with actual performance
- **WHEN** the user submits performed exercise details for an in-progress workout
- **THEN** the system saves the values, calculates elapsed duration on the server, marks the workout completed, and returns the completed record

#### Scenario: Reject invalid workout completion
- **WHEN** exercise values or required completion fields violate validation limits
- **THEN** the system rejects the request without marking the workout completed

#### Scenario: Cancel an abandoned workout
- **WHEN** the owner cancels an in-progress workout
- **THEN** the system marks it cancelled, excludes it from completed history and statistics, and allows the owner to start another workout

### Requirement: Workout history is private and manageable by its owner
The system MUST list and return only the authenticated user's workout records. Users MUST be able to delete their own completed records; deleting another user's record or a nonexistent record MUST return not found. In-progress workouts MUST NOT be deletable through the completed-history operation.

#### Scenario: List own workout history
- **WHEN** an authenticated user requests workout history
- **THEN** only that user's records are returned in reverse chronological order

#### Scenario: Prevent cross-account access
- **WHEN** a user requests or deletes a workout owned by another account
- **THEN** the system returns not found and leaves the record unchanged

#### Scenario: Delete a completed workout
- **WHEN** the owner deletes a completed workout
- **THEN** the record is removed and subsequent history and statistics no longer include it

### Requirement: Dashboard statistics reflect completed workout records
The system MUST calculate weekly completed workout count, current consecutive training-day streak, completed workout duration, training volume, and most frequent workout focus from account-owned completed records. Training volume MUST be calculated from recorded load multiplied by completed repetitions, excluding entries without a numeric load. Optional body-weight change MUST use the earliest and latest available recorded weights across completed records and be absent when fewer than two measurements exist. Calendar weeks and streak dates MUST use the application timezone consistently.

#### Scenario: Calculate current-week progress
- **WHEN** a user requests dashboard training statistics
- **THEN** the system returns current-calendar-week completed workout count, duration, load-based volume, and most frequent focus for that user

#### Scenario: Calculate consecutive training days
- **WHEN** completed workouts exist on consecutive calendar dates
- **THEN** the system reports the number of consecutive dates ending today, or yesterday if no workout has been completed today

#### Scenario: Handle missing load and weight data
- **WHEN** workout entries omit load or fewer than two body-weight measurements exist
- **THEN** volume excludes the unloaded entries and body-weight change is returned as unavailable

#### Scenario: Isolate statistics by account
- **WHEN** two users have different workout records
- **THEN** each user's statistics include only their own records
