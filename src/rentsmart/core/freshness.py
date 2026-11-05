"""Freshness: flag data older than a configured threshold (§5.4 rule 5)."""

from datetime import date
from typing import Any

from rentsmart.contracts import Envelope

DEFAULT_STALE_AFTER_DAYS = 90
# Tax bills are annual, so they get their own, longer threshold.
TAX_STALE_AFTER_DAYS = 550


def flag_stale[E: Envelope[Any]](envelope: E, today: date, max_age_days: int) -> E:
    if (today - envelope.as_of).days > max_age_days:
        return envelope.model_copy(update={"stale": True})
    return envelope
