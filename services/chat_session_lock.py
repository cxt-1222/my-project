"""Process-local, non-blocking locks for active chat streams.

This manager deliberately stores only currently-held keys. It is safe for the
current single-Uvicorn-worker deployment; use a distributed lock before scaling
the application to multiple worker processes or replicas.
"""

from __future__ import annotations

from threading import Lock


class ChatSessionLockManager:
    """Try-lock each authenticated user's chat session without a global queue."""

    def __init__(self) -> None:
        self._active: dict[tuple[int, int], object] = {}
        # FastAPI async routes normally execute on one event loop, but the
        # short critical section is protected in case a sync caller is added.
        self._guard = Lock()

    def try_acquire(self, user_id: int, session_id: int) -> object | None:
        key = (int(user_id), int(session_id))
        with self._guard:
            if key in self._active:
                return None
            token = object()
            self._active[key] = token
            return token

    def release(self, user_id: int, session_id: int, token: object) -> bool:
        key = (int(user_id), int(session_id))
        with self._guard:
            # A stale cleanup must not release a newer request's lease.
            if self._active.get(key) is not token:
                return False
            del self._active[key]
            return True

    def is_locked(self, user_id: int, session_id: int) -> bool:
        with self._guard:
            return (int(user_id), int(session_id)) in self._active


chat_session_locks = ChatSessionLockManager()
