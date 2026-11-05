"""Local cache of provider responses, to spend as few metered API calls as possible.

Stored on the user's machine only. Entries hold the request path, query, response body
and fetch time; never the API key.
"""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

CACHE_DIR_ENV = "RENTSMART_CACHE_DIR"
CACHE_DAYS_ENV = "RENTSMART_CACHE_DAYS"
DEFAULT_MAX_AGE_DAYS = 7


def default_cache_dir() -> Path:
    override = os.environ.get(CACHE_DIR_ENV, "").strip()
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME", "").strip()
    return (Path(base) if base else Path.home() / ".cache") / "rentsmart"


def _normalize(key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if key == "address":
        value = value.replace(",", " ").replace(".", " ")
    return " ".join(value.lower().split())


@dataclass(frozen=True)
class CacheHit:
    data: Any
    fetched_at: datetime


class ResponseCache:
    def __init__(
        self,
        root: Path,
        max_age: timedelta,
        *,
        read: bool = True,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.root = root
        self.max_age = max_age
        self.read = read  # False: always fetch fresh, but still store the result
        self._now = now

    def _file(self, path: str, params: dict[str, Any]) -> Path:
        # Case, spacing, commas and periods in an address don't change the answer, so they
        # don't change the key. Unit markers like "#" are kept.
        normalized = {k: _normalize(k, v) for k, v in params.items()}
        raw = json.dumps({"path": path, "params": normalized}, sort_keys=True)
        return self.root / f"{hashlib.sha256(raw.encode()).hexdigest()}.json"

    def get(self, path: str, params: dict[str, Any]) -> CacheHit | None:
        if not self.read:
            return None
        try:
            entry = json.loads(self._file(path, params).read_text())
            fetched_at = datetime.fromisoformat(entry["fetched_at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None  # missing or unreadable: treat as a miss
        if not self.is_fresh(fetched_at):
            return None
        return CacheHit(data=entry["data"], fetched_at=fetched_at)

    def is_fresh(self, fetched_at: datetime) -> bool:
        return self._now() - fetched_at <= self.max_age

    def entries(self, path: str) -> list[CacheHit]:
        """Every saved response for `path`, of any age (callers check `is_fresh`)."""
        hits: list[CacheHit] = []
        for file in sorted(self.root.glob("*.json")):
            try:
                entry = json.loads(file.read_text())
                if entry["path"] != path:
                    continue
                hits.append(CacheHit(entry["data"], datetime.fromisoformat(entry["fetched_at"])))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # usage.json, or a file that isn't a readable entry
        return hits

    def put(self, path: str, params: dict[str, Any], data: Any) -> None:
        entry = {
            "path": path,
            "params": params,
            "fetched_at": self._now().isoformat(),
            "data": data,
        }
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._file(path, params).write_text(json.dumps(entry))
        except OSError:
            pass  # a cache that can't be written must never break a brief


USAGE_FILE = "usage.json"


class CacheMiss(Exception):
    """A response isn't cached and the provider is offline. Nothing was fetched.

    Not a RentsmartError: it has no exit code and only the web UI catches it.
    """

    def __init__(self, path: str) -> None:
        super().__init__(f"{path} is not cached")
        self.path = path


class UsageLog:
    """Live API responses per month on this machine. A guide, not the vendor's count."""

    def __init__(self, root: Path, today: Callable[[], date] = date.today) -> None:
        self._file = root / USAGE_FILE
        self._today = today

    def _month(self) -> str:
        return f"{self._today():%Y-%m}"

    def _read(self) -> dict[str, int]:
        try:
            data = json.loads(self._file.read_text())
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        counts = cast(dict[str, object], data)
        return {k: v for k, v in counts.items() if isinstance(v, int)}

    def this_month(self) -> int:
        return self._read().get(self._month(), 0)

    def record(self) -> None:
        counts = self._read()
        month = self._month()
        counts[month] = counts.get(month, 0) + 1
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(counts))
        except OSError:
            pass  # counting must never break a brief
