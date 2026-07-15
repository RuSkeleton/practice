"""Простой in-memory rate limit для одного процесса FastAPI.

Проект разворачивается как один экземпляр на ПК HR, поэтому локального
ограничителя достаточно. При переходе на несколько workers/серверов состояние
нужно перенести в Redis или другой общий storage.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class RateLimitState:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    """Считает только явно зарегистрированные неудачные попытки."""

    def __init__(self, *, max_attempts: int, window_seconds: int) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be greater than zero")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")

        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> RateLimitState:
        now = monotonic()
        with self._lock:
            attempts = self._attempts[key]
            self._prune(attempts, now)

            if len(attempts) < self.max_attempts:
                return RateLimitState(allowed=True)

            retry_after = max(
                1,
                int(self.window_seconds - (now - attempts[0])) + 1,
            )
            return RateLimitState(
                allowed=False,
                retry_after_seconds=retry_after,
            )

    def record_failure(self, key: str) -> None:
        now = monotonic()
        with self._lock:
            attempts = self._attempts[key]
            self._prune(attempts, now)
            attempts.append(now)

            # Защита от бесконечного роста при ошибке вызывающего кода.
            while len(attempts) > self.max_attempts:
                attempts.popleft()

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _prune(self, attempts: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
