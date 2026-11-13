"""Zillow Observed Rent Index (ZORI), read from a CSV the user downloaded.

rentsmart never fetches from Zillow. The user downloads the zip-level file from
https://www.zillow.com/research/data/ and points RENTSMART_ZORI_CSV at it. Zillow
requires attribution, so the source name travels with every value built from it.
"""

import csv
import math
import re
from array import array
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from rentsmart.contracts import ConfigError
from rentsmart.providers.base import RentIndexRecord

SOURCE = "Zillow Observed Rent Index (ZORI), Zillow"
LIMITATIONS = [
    "ZORI tracks asking rents for all home types, including apartments, smoothed over 3 months.",
    "Its dollar level isn't comparable with the comps or the rent estimate; "
    "only the change is used.",
]
_MONTH = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class _Index:
    months: list[date]
    # zip -> one value per month, NaN where the file has none. ~10 MB for the national file.
    by_zip: dict[str, array[float]]


class ZoriFile:
    name = SOURCE

    def __init__(self, path: Path) -> None:
        self.path = path

    def check(self) -> None:
        """Read and validate the whole file now, so a bad file fails before any paid call."""
        self._index()

    def rent_index(self, zip_code: str) -> RentIndexRecord | None:
        index = self._index()
        values = index.by_zip.get(zip_code)
        if values is None:
            return None
        history = [(m, v) for m, v in zip(index.months, values, strict=True) if not math.isnan(v)]
        return RentIndexRecord(
            zip_code=zip_code, source=SOURCE, history=history, limitations=LIMITATIONS
        )

    def _index(self) -> _Index:
        try:
            modified = self.path.stat().st_mtime_ns
        except OSError as err:
            raise _unreadable(self.path, err.strerror) from None
        return _load(self.path, modified)


def _unreadable(path: Path, reason: object) -> ConfigError:
    return ConfigError(f"Could not read the ZORI file {path}: {reason}")


@lru_cache(maxsize=2)
def _load(path: Path, modified: int) -> _Index:
    """Parse the file once per version (`modified` is in the key, so a re-download is reread)."""
    try:
        with path.open(newline="", encoding="utf-8") as f:
            return _parse(path, csv.reader(f))
    except OSError as err:
        raise _unreadable(path, err.strerror) from None
    except UnicodeDecodeError:
        raise _unreadable(path, "not a UTF-8 text file (download the CSV, not XLSX)") from None
    except csv.Error as err:
        raise _unreadable(path, f"not a valid CSV ({err})") from None


def _parse(path: Path, rows: Iterator[list[str]]) -> _Index:
    not_zori = ConfigError(f"{path} doesn't look like a zip-level ZORI CSV from Zillow Research.")
    header = next(rows, None)
    if header is None or not {"RegionName", "RegionType"} <= set(header):
        raise not_zori
    month_cols = [i for i, c in enumerate(header) if _MONTH.match(c)]
    try:
        months = [date.fromisoformat(header[i]) for i in month_cols]
    except ValueError:
        raise ConfigError(f"{path} has a month column that isn't a real date.") from None
    if not months:
        raise not_zori
    name, kind = header.index("RegionName"), header.index("RegionType")
    by_zip: dict[str, array[float]] = {}
    for line, row in enumerate(rows, start=2):
        if len(row) != len(header):
            raise ConfigError(f"{path} line {line} has {len(row)} columns, expected {len(header)}.")
        if row[kind] != "zip":
            continue
        try:
            values = array("d", (float(row[i]) if row[i].strip() else math.nan for i in month_cols))
        except ValueError:
            raise ConfigError(f"{path} line {line} has a rent that isn't a number.") from None
        by_zip[row[name].zfill(5)] = values
    return _Index(months, by_zip)
