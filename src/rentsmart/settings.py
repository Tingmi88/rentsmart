"""Settings read from the environment, shared by the CLI and the local UI."""

import os
from datetime import timedelta
from pathlib import Path

from rentsmart.contracts import ConfigError
from rentsmart.core.freshness import DEFAULT_STALE_AFTER_DAYS
from rentsmart.providers.cache import (
    CACHE_DAYS_ENV,
    DEFAULT_MAX_AGE_DAYS,
    ResponseCache,
    UsageLog,
    default_cache_dir,
)
from rentsmart.providers.zori import ZoriFile

STALE_ENV = "RENTSMART_STALE_AFTER_DAYS"
ZORI_ENV = "RENTSMART_ZORI_CSV"


def _whole_days(env: str, default: int) -> int:
    raw = os.environ.get(env, "").strip()
    if not raw:
        return default
    if not raw.isdigit():
        raise ConfigError(f"{env} must be a whole number of days, got {raw!r}.")
    return int(raw)


def stale_after_days() -> int:
    return _whole_days(STALE_ENV, DEFAULT_STALE_AFTER_DAYS)


def response_cache(refresh: bool = False, *, any_age: bool = False) -> ResponseCache | None:
    """The local response cache, or None when RENTSMART_CACHE_DAYS is 0.

    `any_age` serves saved responses however old (the local UI shows their date instead).
    """
    days = _whole_days(CACHE_DAYS_ENV, DEFAULT_MAX_AGE_DAYS)
    if days == 0:
        return None
    max_age = timedelta.max if any_age else timedelta(days=days)
    return ResponseCache(default_cache_dir(), max_age, read=not refresh)


def usage_log() -> UsageLog:
    return UsageLog(default_cache_dir())


def rent_index() -> ZoriFile | None:
    """The user's downloaded ZORI file, or None when RENTSMART_ZORI_CSV isn't set."""
    raw = os.environ.get(ZORI_ENV, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_file():
        raise ConfigError(f"{ZORI_ENV} points to {path}, which isn't a file.")
    zori = ZoriFile(path)
    zori.check()
    return zori
