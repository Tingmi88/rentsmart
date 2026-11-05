"""Replay recorded RentCast responses through the real adapter, with no network.

Used by the golden-set evaluation so results are repeatable and cost no API calls.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx

from rentsmart.providers.rentcast import (
    BASE_URL,
    MARKETS_PATH,
    PROPERTIES_PATH,
    RENT_AVM_PATH,
    RentCastProvider,
)

FIXTURE_FILES = {
    PROPERTIES_PATH: "properties.json",
    RENT_AVM_PATH: "rent_long_term.json",
    MARKETS_PATH: "markets.json",
}
_API_PREFIX = httpx.URL(BASE_URL).path


def replay_provider(
    fixture_dir: Path, recorded_on: Callable[[], date] = date.today
) -> RentCastProvider:
    def handle(request: httpx.Request) -> httpx.Response:
        name = FIXTURE_FILES.get(request.url.path.removeprefix(_API_PREFIX))
        file = fixture_dir / name if name else None
        if file is None or not file.exists():
            return httpx.Response(404)
        data = json.loads(file.read_text())
        return httpx.Response(404) if data is None else httpx.Response(200, json=data)

    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handle))
    return RentCastProvider(api_key="replay", client=client, today=recorded_on)
