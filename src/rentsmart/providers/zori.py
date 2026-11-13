"""Zillow Observed Rent Index (ZORI), read from a CSV the user downloaded.

rentsmart never fetches from Zillow. The user downloads the zip-level file from
https://www.zillow.com/research/data/ and points RENTSMART_ZORI_CSV at it. Zillow
requires attribution, so the source name travels with every value built from it.
"""

import csv
import re
from collections.abc import Sequence
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


class ZoriFile:
    name = SOURCE

    def __init__(self, path: Path) -> None:
        self.path = path

    def check(self) -> None:
        """Fail early, before any paid call, if the file can't be read or isn't ZORI."""
        try:
            with self.path.open(newline="", encoding="utf-8") as f:
                _months(self.path, next(csv.reader(f), list[str]()))
        except OSError as err:
            raise ConfigError(f"Could not read the ZORI file {self.path}: {err.strerror}") from None

    def rent_index(self, zip_code: str) -> RentIndexRecord | None:
        try:
            modified = self.path.stat().st_mtime_ns
        except OSError as err:
            raise ConfigError(f"Could not read the ZORI file {self.path}: {err.strerror}") from None
        # The local UI rebuilds the brief on every what-if; don't reread 10 MB each time.
        return _lookup(self.path, modified, zip_code)


@lru_cache(maxsize=64)
def _lookup(path: Path, modified: int, zip_code: str) -> RentIndexRecord | None:
    """One zip's series. `modified` is in the key so a re-downloaded file is read again."""
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            months = _months(path, reader.fieldnames or [])
            for row in reader:
                if row["RegionType"] != "zip" or row["RegionName"].zfill(5) != zip_code:
                    continue
                history = [(date.fromisoformat(m), float(row[m])) for m in months if row[m].strip()]
                return RentIndexRecord(
                    zip_code=zip_code, source=SOURCE, history=history, limitations=LIMITATIONS
                )
    except OSError as err:
        raise ConfigError(f"Could not read the ZORI file {path}: {err.strerror}") from None
    except ValueError as err:
        raise ConfigError(f"{path} has a value that isn't a number: {err}") from None
    return None


def _months(path: Path, columns: Sequence[str]) -> list[str]:
    months = [c for c in columns if _MONTH.match(c)]
    if not {"RegionName", "RegionType"} <= set(columns) or not months:
        raise ConfigError(f"{path} doesn't look like a zip-level ZORI CSV from Zillow Research.")
    return months
