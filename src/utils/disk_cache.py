"""Minimal JSON disk cache with TTL — used for market snapshots and news history."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Optional


class DiskCache:
    """A very small, dependency-free persistent cache.

    Entries are JSON files in a directory. Each entry stores ``{"_ts": epoch,
    "data": <serializable>}``. Reads older than *max_age_hours* are treated as
    misses. Writes are atomic via temp-file + os.replace.
    """

    def __init__(self, directory: str | Path, default_ttl_hours: float = 6.0):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl_hours = default_ttl_hours
        self._lock = Lock()

    def _path(self, key: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
        return self.dir / f"{safe}.json"

    def get(self, key: str, max_age_hours: Optional[float] = None) -> Optional[Any]:
        ttl = self.default_ttl_hours if max_age_hours is None else max_age_hours
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            stored = float(payload.get("_ts", 0.0))
            if stored and (time.time() - stored) > ttl * 3600:
                return None
            return payload.get("data")
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        path = self._path(key)
        payload = {"_ts": time.time(), "data": value}
        try:
            data_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            with self._lock:
                tmp = path.with_suffix(".tmp")
                with open(tmp, "wb") as fh:
                    fh.write(data_bytes)
                os.replace(tmp, path)
        except OSError:
            # Never crash the app because of a cache write.
            pass