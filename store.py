"""Невелике сховище ключ-значення для акаунтів: Upstash Redis (REST) у продакшні, пам'ять/файл у розробці й тестах.

Інтерфейс однаковий: get/set/setnx/delete/incr/sadd/srem/smembers/lpush/lrange/mget.
Усі значення це рядки (JSON кодує викликач).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class StoreError(RuntimeError):
    """Сховище недоступне або повернуло помилку."""


class MemStore:
    """Сховище в пам'яті (опційно з дзеркалом у JSON-файлі). Не для продакшну: на Streamlit Cloud файли зникають."""
    persistent = False

    def __init__(self, path: str | Path | None = None):
        self._d: dict[str, str] = {}
        self._exp: dict[str, float] = {}
        self._sets: dict[str, set[str]] = {}
        self._lists: dict[str, list[str]] = {}
        self._lock = threading.RLock()
        self._path = Path(path) if path else None
        if self._path and self._path.exists():
            try:
                raw = json.loads(self._path.read_text("utf-8"))
                self._d = raw.get("d", {})
                self._exp = {k: float(v) for k, v in raw.get("exp", {}).items()}
                self._sets = {k: set(v) for k, v in raw.get("sets", {}).items()}
                self._lists = raw.get("lists", {})
            except Exception:  # noqa: BLE001
                pass

    def _flush(self) -> None:
        if not self._path:
            return
        try:
            self._path.write_text(json.dumps({"d": self._d, "exp": self._exp, "sets": {k: sorted(v) for k, v in self._sets.items()},
                                              "lists": self._lists}), "utf-8")
        except Exception:  # noqa: BLE001
            pass

    def _alive(self, key: str) -> bool:
        e = self._exp.get(key)
        if e is not None and e <= time.time():
            self._d.pop(key, None)
            self._exp.pop(key, None)
            return False
        return key in self._d

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._d[key] if self._alive(key) else None

    def mget(self, keys: list[str]) -> list[str | None]:
        return [self.get(k) for k in keys]

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        with self._lock:
            self._d[key] = value
            if ex:
                self._exp[key] = time.time() + ex
            else:
                self._exp.pop(key, None)
            self._flush()

    def setnx(self, key: str, value: str) -> bool:
        with self._lock:
            if self._alive(key):
                return False
            self.set(key, value)
            return True

    def delete(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._d.pop(k, None)
                self._exp.pop(k, None)
                self._sets.pop(k, None)
                self._lists.pop(k, None)
            self._flush()

    def incr(self, key: str, ex: int | None = None) -> int:
        with self._lock:
            n = int(self.get(key) or 0) + 1
            was_new = not self._alive(key)
            self._d[key] = str(n)
            if ex and was_new:
                self._exp[key] = time.time() + ex
            self._flush()
            return n

    def sadd(self, key: str, *vals: str) -> None:
        with self._lock:
            self._sets.setdefault(key, set()).update(vals)
            self._flush()

    def srem(self, key: str, *vals: str) -> None:
        with self._lock:
            self._sets.get(key, set()).difference_update(vals)
            self._flush()

    def smembers(self, key: str) -> list[str]:
        with self._lock:
            return sorted(self._sets.get(key, set()))

    def lpush(self, key: str, value: str, keep: int = 500) -> None:
        with self._lock:
            lst = self._lists.setdefault(key, [])
            lst.insert(0, value)
            del lst[keep:]
            self._flush()

    def lrange(self, key: str, n: int = 100) -> list[str]:
        with self._lock:
            return list(self._lists.get(key, []))[:n]


class UpstashStore:
    """Upstash Redis через REST (/pipeline). Один HTTP-запит на операцію."""
    persistent = True

    def __init__(self, url: str, token: str):
        import requests
        self._url = url.rstrip("/") + "/pipeline"
        self._s = requests.Session()
        self._s.headers.update({"Authorization": f"Bearer {token}"})

    def _run(self, *cmds: list):
        try:
            r = self._s.post(self._url, json=[list(map(str, c)) for c in cmds], timeout=8)
            r.raise_for_status()
            out = r.json()
        except Exception as exc:  # noqa: BLE001
            raise StoreError(f"{type(exc).__name__}: {exc}") from exc
        for o in out:
            if isinstance(o, dict) and o.get("error"):
                raise StoreError(str(o["error"]))
        return [o.get("result") if isinstance(o, dict) else o for o in out]

    def get(self, key: str) -> str | None:
        return self._run(["GET", key])[0]

    def mget(self, keys: list[str]) -> list[str | None]:
        if not keys:
            return []
        out: list[str | None] = []
        for i in range(0, len(keys), 200):
            out += self._run(["MGET", *keys[i:i + 200]])[0]
        return out

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._run(["SET", key, value, *(["EX", str(int(ex))] if ex else [])])

    def setnx(self, key: str, value: str) -> bool:
        return bool(self._run(["SET", key, value, "NX"])[0])

    def delete(self, *keys: str) -> None:
        if keys:
            self._run(["DEL", *keys])

    def incr(self, key: str, ex: int | None = None) -> int:
        res = self._run(["INCR", key], *([["EXPIRE", key, str(int(ex)), "NX"]] if ex else []))
        return int(res[0])

    def sadd(self, key: str, *vals: str) -> None:
        if vals:
            self._run(["SADD", key, *vals])

    def srem(self, key: str, *vals: str) -> None:
        if vals:
            self._run(["SREM", key, *vals])

    def smembers(self, key: str) -> list[str]:
        return sorted(self._run(["SMEMBERS", key])[0] or [])

    def lpush(self, key: str, value: str, keep: int = 500) -> None:
        self._run(["LPUSH", key, value], ["LTRIM", key, "0", str(keep - 1)])

    def lrange(self, key: str, n: int = 100) -> list[str]:
        return self._run(["LRANGE", key, "0", str(n - 1)])[0] or []


def make_store(url: str | None, token: str | None, path: str | Path | None = None):
    """Upstash, якщо задано URL і токен; інакше пам'ять (дані зникнуть при перезапуску)."""
    if url and token:
        return UpstashStore(url, token)
    return MemStore(path)


_CACHE: dict[tuple, object] = {}


def get_store(url: str | None, token: str | None):
    """Один екземпляр сховища на процес (HTTP-сесія й пам'ять не дублюються між перезапусками скрипта)."""
    k = (url or "", token or "")
    if k not in _CACHE:
        _CACHE[k] = make_store(url, token)
    return _CACHE[k]
