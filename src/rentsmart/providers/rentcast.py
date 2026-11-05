"""RentCast adapter: maps RentCast API responses onto provider-neutral records."""

import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, cast

import httpx

from rentsmart.contracts import ConfigError, ProviderError, QuotaExceeded, SimilarAddress
from rentsmart.core.address import Address, compare
from rentsmart.providers.base import (
    CompRecord,
    MarketRecord,
    PropertyRecord,
    RentEstimateRecord,
    SubjectQuery,
    TaxRecord,
)
from rentsmart.providers.cache import CacheHit, CacheMiss, ResponseCache, UsageLog

BASE_URL = "https://api.rentcast.io/v1"
PROPERTIES_PATH = "/properties"
RENT_AVM_PATH = "/avm/rent/long-term"
MARKETS_PATH = "/markets"
API_KEY_ENV = "RENTCAST_API_KEY"
COMP_COUNT = 10
MAX_SUGGESTIONS = 5
HISTORY_MONTHS = 6

# Called with (path, parsed JSON or None for 404) after each successful request.
ResponseHook = Callable[[str, Any], None]


class RentCastProvider:
    name = "RentCast"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        on_response: ResponseHook | None = None,
        cache: ResponseCache | None = None,
        today: Callable[[], date] = date.today,
        *,
        offline: bool = False,
        usage: UsageLog | None = None,
        check_similar: bool = False,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=BASE_URL,
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            timeout=20.0,
        )
        self._on_response = on_response
        self._cache = cache
        self._today = today
        self._offline = offline  # cache only: a miss raises CacheMiss instead of fetching
        self._usage = usage
        # Before looking up an unsaved address, stop if similar saved addresses exist.
        self._check_similar = check_similar
        self._retrieved_on: dict[str, date] = {}
        # When each response served from the cache was fetched (live responses aren't listed).
        self.saved_at: dict[str, datetime] = {}

    @classmethod
    def from_env(
        cls,
        on_response: ResponseHook | None = None,
        cache: ResponseCache | None = None,
        today: Callable[[], date] = date.today,
        *,
        offline: bool = False,
        usage: UsageLog | None = None,
        check_similar: bool = False,
    ) -> "RentCastProvider":
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not api_key:
            raise ConfigError(
                f"{API_KEY_ENV} is not set. Export it, or add it to .env (see .env.example)."
            )
        return cls(
            api_key,
            on_response=on_response,
            cache=cache,
            today=today,
            offline=offline,
            usage=usage,
            check_similar=check_similar,
        )

    def resolve_address(self, address: str) -> list[PropertyRecord]:
        query = {"address": address}
        data = self._saved_lookup(address, query)
        if data is None:
            data = self._get(PROPERTIES_PATH, query)
        if not data:
            return []
        retrieved_on = self._retrieved_on.get(PROPERTIES_PATH)
        with _parsing(PROPERTIES_PATH):
            return [
                _parse_property(_obj(p)).model_copy(update={"retrieved_on": retrieved_on})
                for p in _list(data)
            ]

    def rent_estimate(self, subject: SubjectQuery) -> RentEstimateRecord:
        params: dict[str, str | int | float | None] = {
            "address": subject.address,
            "propertyType": subject.property_type,
            "bedrooms": subject.beds,
            "bathrooms": subject.baths,
            "squareFootage": subject.sqft,
            "compCount": COMP_COUNT,
        }
        data = self._get(RENT_AVM_PATH, params)
        if not data:
            return RentEstimateRecord()
        with _parsing(RENT_AVM_PATH):
            return RentEstimateRecord(
                rent=data.get("rent"),
                low=data.get("rentRangeLow"),
                high=data.get("rentRangeHigh"),
                comps=[_parse_comp(_obj(c)) for c in _list(data.get("comparables"))],
                as_of=self._retrieved_on.get(RENT_AVM_PATH),
            )

    def market_stats(self, zip_code: str) -> MarketRecord:
        params = {"zipCode": zip_code, "dataType": "Rental", "historyRange": HISTORY_MONTHS}
        data = self._get(MARKETS_PATH, params)
        with _parsing(MARKETS_PATH):
            rental = _obj(_obj(data).get("rentalData"))
            history = _obj(rental.get("history"))
            return MarketRecord(
                zip_code=zip_code,
                median_days_on_market=rental.get("medianDaysOnMarket"),
                history=[
                    (date.fromisoformat(f"{month}-01"), float(row["medianDaysOnMarket"]))
                    for month, row in sorted((m, _obj(r)) for m, r in history.items())
                    if row.get("medianDaysOnMarket") is not None
                ],
                as_of=_date(rental.get("lastUpdatedDate")),
            )

    def _saved_lookup(self, address: str, query: dict[str, Any]) -> Any:
        """The freshest usable saved lookup of this address, typed this way or another, or None.

        Raises SimilarAddress when only near matches were looked up and check_similar is on.
        """
        cache = self._cache
        if cache is None:
            return None
        same: CacheHit | None = cache.get(PROPERTIES_PATH, query)  # this exact text
        seen_same = same is not None
        similar: dict[str, date] = {}
        for entry in cache.entries(PROPERTIES_PATH):
            records = _list(entry.data)
            if len(records) != 1 or (saved := _address(_obj(records[0]))) is None:
                continue
            match = compare(address, saved)
            if match == "same":
                seen_same = True  # the address itself was looked up: never ask
                fresh = cache.read and cache.is_fresh(entry.fetched_at)
                if fresh and (same is None or entry.fetched_at > same.fetched_at):
                    same = entry
            elif match == "similar":
                label = str(_obj(records[0]).get("formattedAddress"))
                day = entry.fetched_at.astimezone().date()
                similar[label] = max(day, similar.get(label, day))
        if same is not None:
            self._retrieved_on[PROPERTIES_PATH] = same.fetched_at.astimezone().date()
            self.saved_at[PROPERTIES_PATH] = same.fetched_at
            return same.data
        if similar and self._check_similar and not seen_same:
            newest = sorted(similar.items(), key=lambda kv: kv[1], reverse=True)
            raise SimilarAddress(address, newest[:MAX_SUGGESTIONS])
        return None

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        query = {k: v for k, v in params.items() if v is not None}
        if self._cache is not None and (hit := self._cache.get(path, query)) is not None:
            self._retrieved_on[path] = hit.fetched_at.astimezone().date()
            self.saved_at[path] = hit.fetched_at
            return hit.data
        if self._offline:
            raise CacheMiss(path)
        try:
            resp = self._client.get(path, params=query)
        except httpx.HTTPError as err:
            raise ProviderError(f"Could not reach RentCast: {err}") from err
        if self._usage is not None:
            self._usage.record()  # any response counts: the vendor may bill errors too
        if resp.status_code == 429:
            raise QuotaExceeded(self.name)
        if resp.status_code in (401, 403):
            detail = _error_message(resp) or f"Check {API_KEY_ENV}."
            raise ProviderError(f"RentCast refused the request (HTTP {resp.status_code}): {detail}")
        if resp.status_code == 404:
            data = None
        elif resp.is_error:
            raise ProviderError(f"RentCast returned HTTP {resp.status_code} for {path}.")
        else:
            try:
                data = resp.json()
            except ValueError as err:
                raise ProviderError(
                    f"RentCast returned a response that isn't JSON for {path}."
                ) from err
        self._retrieved_on[path] = self._today()
        if self._cache is not None:
            self._cache.put(path, query, data)
        if self._on_response:
            self._on_response(path, data)
        return data


@contextmanager
def _parsing(path: str) -> Generator[None]:
    """Turn a response we can't map (vendor changed shape, bad values) into a named failure."""
    try:
        yield
    except (AttributeError, KeyError, TypeError, ValueError) as err:
        raise ProviderError(
            f"RentCast returned an unexpected response for {path} ({type(err).__name__}: {err})."
        ) from err


def _error_message(resp: httpx.Response) -> str | None:
    try:
        message = _obj(resp.json()).get("message")
    except ValueError:
        return None
    return str(message) if message else None


def _obj(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []


def _date(value: str | None) -> date | None:
    return datetime.fromisoformat(value).date() if value else None


def _address(p: dict[str, Any]) -> Address | None:
    street = p.get("addressLine1")
    if not street:
        return None
    return Address(
        street=str(street),
        unit=str(p.get("addressLine2") or ""),
        city=str(p.get("city") or ""),
        state=str(p.get("state") or ""),
        zip=str(p.get("zipCode") or ""),
    )


def _parse_property(p: dict[str, Any]) -> PropertyRecord:
    # Owner fields are never read: no personal data (§11).
    tax = None
    taxes = _obj(p.get("propertyTaxes"))
    if taxes:
        year = max(taxes, key=int)
        assessment = _obj(_obj(p.get("taxAssessments")).get(year))
        tax = TaxRecord(
            year=int(year),
            amount=float(taxes[year]["total"]),
            assessed_value=assessment.get("value"),
        )
    return PropertyRecord(
        formatted_address=p["formattedAddress"],
        zip_code=str(p["zipCode"]),
        property_type=p.get("propertyType"),
        beds=p.get("bedrooms"),
        baths=p.get("bathrooms"),
        sqft=p.get("squareFootage"),
        year_built=p.get("yearBuilt"),
        tax=tax,
    )


def _parse_comp(c: dict[str, Any]) -> CompRecord:
    return CompRecord(
        address=c["formattedAddress"],
        distance_miles=c.get("distance"),
        beds=c.get("bedrooms"),
        baths=c.get("bathrooms"),
        sqft=c.get("squareFootage"),
        price=float(c["price"]),
        listed_date=_date(c.get("listedDate")),
        last_seen_date=_date(c.get("lastSeenDate")),
        status=str(c.get("status") or "unknown").lower(),
    )
