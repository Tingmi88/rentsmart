import os
from datetime import date
from pathlib import Path

import pytest

from rentsmart.contracts import ConfigError, Kind
from rentsmart.core.engine import build_brief
from rentsmart.core.facts import OwnerFacts
from rentsmart.core.market import build_rent_change
from rentsmart.providers.base import RentIndexRecord
from rentsmart.providers.fake import FakeProvider
from rentsmart.providers.zori import ZoriFile
from rentsmart.settings import ZORI_ENV, rent_index
from tests.conftest import ADDRESS, TODAY
from tests.conftest import ZORI_SAMPLE as SAMPLE


def test_zori_reads_one_zip_oldest_first() -> None:
    record = ZoriFile(SAMPLE).rent_index("78729")
    assert record is not None and record.zip_code == "78729"
    assert len(record.history) == 15
    assert record.history[0] == (date(2025, 7, 31), 2000.0)
    assert record.history[-1] == (date(2026, 9, 30), 1944.0)
    assert "Zillow" in record.source and record.limitations


def test_zori_skips_blank_months_and_keeps_leading_zeros() -> None:
    zori = ZoriFile(SAMPLE)
    short = zori.rent_index("32601")
    assert short is not None and len(short.history) == 6
    assert zori.rent_index("02108") is not None
    assert zori.rent_index("99999") is None


def test_zori_rejects_other_files(tmp_path: Path) -> None:
    other = tmp_path / "other.csv"
    other.write_text("a,b\n1,2\n")
    with pytest.raises(ConfigError, match="ZORI"):
        ZoriFile(other).rent_index("78729")
    with pytest.raises(ConfigError, match="Could not read"):
        ZoriFile(tmp_path / "missing.csv").rent_index("78729")


def test_rent_change_over_twelve_months() -> None:
    record = ZoriFile(SAMPLE).rent_index("78729")
    env = build_rent_change(record)
    assert env is not None
    assert env.value == -0.024 and env.kind == Kind.COMPUTED
    assert env.as_of == date(2026, 9, 30)
    assert "Zillow" in env.source
    assert env.evidence == ["2026-09: $1,944", "2025-09: $1,992"]
    assert record is not None and set(record.limitations) <= set(env.limitations)
    assert any("not a price for this property" in lim for lim in env.limitations)


def test_rent_change_needs_the_same_month_a_year_earlier() -> None:
    assert build_rent_change(None) is None
    assert build_rent_change(ZoriFile(SAMPLE).rent_index("32601")) is None
    gap = RentIndexRecord(
        zip_code="1",
        source="test index",
        history=[(date(2025, 8, 31), 100.0), (date(2026, 9, 30), 110.0)],
    )
    assert build_rent_change(gap) is None


def test_brief_carries_rent_change_and_flags_it_stale(fake_provider: FakeProvider) -> None:
    zori = ZoriFile(SAMPLE)
    plain = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY)
    assert plain.zip_rent_change is None

    fresh = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY, rent_index=zori)
    assert fresh.zip_rent_change is None  # 32601 has only 6 months

    fake_provider.properties = [
        p.model_copy(update={"zip_code": "02108"}) for p in fake_provider.properties
    ]
    brief = build_brief(ADDRESS, OwnerFacts(), fake_provider, today=TODAY, rent_index=zori)
    assert brief.zip_rent_change is not None and brief.zip_rent_change.value == 0.04
    assert not brief.zip_rent_change.stale

    late = build_brief(
        ADDRESS, OwnerFacts(), fake_provider, today=date(2027, 3, 1), rent_index=zori
    )
    assert late.zip_rent_change is not None and late.zip_rent_change.stale and late.stale


def test_settings_rent_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(ZORI_ENV, raising=False)
    assert rent_index() is None
    monkeypatch.setenv(ZORI_ENV, str(SAMPLE))
    assert isinstance(rent_index(), ZoriFile)
    monkeypatch.setenv(ZORI_ENV, str(tmp_path / "nope.csv"))
    with pytest.raises(ConfigError, match=ZORI_ENV):
        rent_index()


def test_zori_rereads_a_replaced_file(tmp_path: Path) -> None:
    path = tmp_path / "zori.csv"
    path.write_text(SAMPLE.read_text())
    zori = ZoriFile(path)
    assert zori.rent_index("78729") is not None
    path.write_text(SAMPLE.read_text().replace("78729", "78730"))
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
    assert zori.rent_index("78729") is None


def test_settings_reject_a_non_zori_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    other = tmp_path / "other.csv"
    other.write_text("a,b\n1,2\n")
    monkeypatch.setenv(ZORI_ENV, str(other))
    with pytest.raises(ConfigError, match="ZORI"):
        rent_index()
