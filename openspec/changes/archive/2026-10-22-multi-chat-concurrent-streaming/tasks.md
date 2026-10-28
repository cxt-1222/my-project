## 1. Runtime State Model

- [x] 1.1 Replace page-wide `state.isStreaming` with per-session stream records keyed by `session_id`, including controller, status, accumulated text, sources, error, request generation and account generation.
- [x] 1.2 Add helpers to create, read, update, finish and invalidate a session stream without mutating another session's record.
- [x] 1.3 Define the same-session submission guard so a second request is rejected with a visible message and is never queued.

## 2. Concurrent Stream UI

- [x] 2.1 Refactor `streamAnswer()` to reserve the target session before any asynchronous work, use its own `AbortController`, and process SSE events only when the request and account generations still match.
- [x] 2.2 Replace the global typing DOM id with session-aware rendering; render the active session's in-progress answer while keeping background session state in memory.
- [x] 2.3 Update session switching and message rendering so switching away and back restores each session's in-progress text, sources, completion state and error state.
- [x] 2.4 Make the send control reflect only the active session's lock; allow sending in another session while a different session is streaming.
- [x] 2.5 Handle logout, account changes, session deletion, timeout, abort and late SSE events without writing to a new account or deleted/different session.
- [x] 2.6 Isolate unsent composer drafts by session and restore them when switching sessions.
- [x] 2.7 Patch only the active streamed answer node for each SSE delta; preserve chat history DOM and user scroll position.

## 3. Backend Concurrency Verification

- [x] 3.1 Add or update backend regression coverage proving different `session_id` values can enter the async stream path concurrently without a global application queue.
- [x] 3.2 Add a per-`(user_id, session_id)` backend try-lock; reject same-session overlap with a clear conflict, release the lock on success/error/disconnect, and allow different sessions to proceed concurrently.
- [x] 3.3 Verify the existing SSE event names, authentication behavior, source payloads and completed message persistence remain compatible.

## 4. Frontend Tests

- [x] 4.1 Add a controllable SSE/mock-stream test for two sessions where both streams run at the same time and finish in opposite order.
- [x] 4.2 Test switching between two active sessions and verify deltas, sources, final answers and errors remain session-local.
- [x] 4.3 Test same-session duplicate submission, independent submission in another session, timeout/error isolation, logout cancellation, deletion protection and refresh behavior.
- [x] 4.4 Test streamed answer patching preserves the chat container and row, and respects manual scroll position.

## 5. Manual Acceptance

- [x] 5.1 Start the local frontend and backend and create two new chat sessions in the same page.
- [x] 5.2 Ask a slow/long question in session A, switch to session B before A completes, and submit another question; verify both requests generate without waiting for a global queue.
- [x] 5.3 Switch between A and B while both are generating; verify text and source references never cross sessions and both final answers are saved in their own histories.
- [x] 5.4 Submit a second question in A while A is still generating; verify it is rejected with a clear message and is not silently queued.
- [x] 5.5 Verify one failed/timeout stream does not stop the other, then verify logout and session deletion do not allow late output to appear elsewhere.
