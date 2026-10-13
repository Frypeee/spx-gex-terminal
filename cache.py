"""Потокобезпечний TTL-кеш зі «застарілим» резервом.

Якщо джерело не відповіло, повертаємо останні вдалі дані з позначкою про вік
і текстом помилки. Нічого не вигадуємо: якщо даних ніколи не було, value = None.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Fetched:
    value: Any
    age: float | None        # секунд з моменту вдалого завантаження
    error: str | None        # текст останньої помилки (якщо була)

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def stale(self) -> bool:
        return self.value is not None and self.error is not None


class TTLCache:
    RETRY_AFTER_FAIL = 15.0

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._fail: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._fail.clear()

    def get(self, key: str, ttl: float, fn: Callable[[], Any]) -> Fetched:
        now = time.time()
        with self._lock:
            hit = self._data.get(key)
            if hit and now - hit[0] < ttl:
                return Fetched(hit[1], now - hit[0], None)
            klock = self._key_locks.setdefault(key, threading.Lock())

        with klock:
            now = time.time()
            with self._lock:
                hit = self._data.get(key)
                if hit and now - hit[0] < ttl:
                    return Fetched(hit[1], now - hit[0], None)
                fail = self._fail.get(key)
            if fail and now - fail[0] < self.RETRY_AFTER_FAIL:
                return self._fallback(key, fail[1])
            try:
                value = fn()
            except Exception as exc:  # noqa: BLE001: джерела нестабільні, повертаємо резерв
                msg = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self._fail[key] = (time.time(), msg)
                return self._fallback(key, msg)
            with self._lock:
                self._data[key] = (time.time(), value)
                self._fail.pop(key, None)
            return Fetched(value, 0.0, None)

    def _fallback(self, key: str, msg: str) -> Fetched:
        with self._lock:
            hit = self._data.get(key)
        if hit:
            return Fetched(hit[1], time.time() - hit[0], msg)
        return Fetched(None, None, msg)


CACHE = TTLCache()
