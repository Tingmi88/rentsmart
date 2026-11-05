from datetime import UTC, datetime, timedelta
from pathlib import Path

from rentsmart.providers.cache import ResponseCache

T0 = datetime(2026, 10, 20, 12, tzinfo=UTC)


def _cache(root: Path, now: datetime, read: bool = True) -> ResponseCache:
    return ResponseCache(root, timedelta(days=7), read=read, now=lambda: now)


def test_round_trip_and_expiry(tmp_path: Path) -> None:
    _cache(tmp_path, T0).put("/p", {"address": "1 A St"}, [{"x": 1}])
    hit = _cache(tmp_path, T0 + timedelta(days=6)).get("/p", {"address": "1 A St"})
    assert hit is not None and hit.data == [{"x": 1}] and hit.fetched_at == T0
    assert _cache(tmp_path, T0 + timedelta(days=8)).get("/p", {"address": "1 A St"}) is None


def test_key_ignores_address_case_and_spacing(tmp_path: Path) -> None:
    cache = _cache(tmp_path, T0)
    cache.put("/p", {"address": "1 A St,  Town"}, "data")
    assert cache.get("/p", {"address": "1 a st, town"}) is not None
    assert cache.get("/p", {"address": "2 A St, Town"}) is None
    assert cache.get("/other", {"address": "1 A St, Town"}) is None


def test_not_found_is_cached_as_null(tmp_path: Path) -> None:
    cache = _cache(tmp_path, T0)
    cache.put("/p", {"address": "nowhere"}, None)
    hit = cache.get("/p", {"address": "nowhere"})
    assert hit is not None and hit.data is None


def test_refresh_skips_reads_but_still_writes(tmp_path: Path) -> None:
    _cache(tmp_path, T0).put("/p", {}, "old")
    fresh = _cache(tmp_path, T0, read=False)
    assert fresh.get("/p", {}) is None
    fresh.put("/p", {}, "new")
    hit = _cache(tmp_path, T0).get("/p", {})
    assert hit is not None and hit.data == "new"


def test_corrupt_entry_is_a_miss(tmp_path: Path) -> None:
    cache = _cache(tmp_path, T0)
    cache.put("/p", {}, "data")
    next(tmp_path.glob("*.json")).write_text("{not json")
    assert cache.get("/p", {}) is None


def test_unwritable_cache_never_raises(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    _cache(blocker / "cache", T0).put("/p", {}, "data")  # parent is a file


def test_api_key_never_stored(tmp_path: Path) -> None:
    _cache(tmp_path, T0).put("/p", {"address": "1 A St"}, {"rent": 1})
    assert "key" not in next(tmp_path.glob("*.json")).read_text().lower()


def test_key_ignores_commas_and_periods(tmp_path: Path) -> None:
    cache = _cache(tmp_path, T0)
    cache.put("/p", {"address": "4120 Sample Dr, Austin, TX 78729"}, {"rent": 1})
    hit = cache.get("/p", {"address": "4120 sample dr. Austin TX, 78729"})
    assert hit is not None and hit.data == {"rent": 1}


def test_key_keeps_unit_numbers_distinct(tmp_path: Path) -> None:
    cache = _cache(tmp_path, T0)
    cache.put("/p", {"address": "12814 Tomanet Trl, # A, Austin, TX 78727"}, {"rent": 1})
    assert cache.get("/p", {"address": "12814 Tomanet Trl, # B, Austin, TX 78727"}) is None
