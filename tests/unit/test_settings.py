from datetime import timedelta

import pytest

from rentsmart.contracts import ConfigError
from rentsmart.core.freshness import DEFAULT_STALE_AFTER_DAYS
from rentsmart.settings import response_cache, stale_after_days


def test_defaults() -> None:
    assert stale_after_days() == DEFAULT_STALE_AFTER_DAYS
    cache = response_cache()
    assert cache is not None and cache.max_age == timedelta(days=7) and cache.read


def test_refresh_skips_reads() -> None:
    cache = response_cache(refresh=True)
    assert cache is not None and not cache.read


def test_zero_days_disables_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENTSMART_CACHE_DAYS", "0")
    assert response_cache() is None


@pytest.mark.parametrize("env", ["RENTSMART_CACHE_DAYS", "RENTSMART_STALE_AFTER_DAYS"])
def test_bad_values_are_config_errors(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv(env, "seven")
    with pytest.raises(ConfigError, match=env):
        response_cache() if env == "RENTSMART_CACHE_DAYS" else stale_after_days()
