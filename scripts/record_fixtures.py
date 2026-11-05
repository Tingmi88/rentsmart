"""Record live RentCast responses as test fixtures. Costs about 3 API requests per run.

Run by hand only, never in CI:

    uv run python scripts/record_fixtures.py "123 Main St, Gainesville, FL 32601" gainesville-main

Writes tests/fixtures/rentcast/<slug>/{properties,rent_long_term,markets}.json.
The API key is never written. Owner and other personal fields are stripped (§11).
"""

import json
import sys
from pathlib import Path
from typing import Any

from rentsmart.contracts import RentsmartError
from rentsmart.core.engine import build_brief
from rentsmart.core.facts import OwnerFacts
from rentsmart.providers.rentcast import RentCastProvider
from rentsmart.providers.replay import FIXTURE_FILES
from rentsmart.settings import usage_log

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "rentcast"
PERSONAL_KEYS = {"owner", "ownerOccupied"}


def _strip_personal(data: Any) -> Any:
    if isinstance(data, list):
        return [_strip_personal(item) for item in data]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(data, dict):
        return {k: _strip_personal(v) for k, v in data.items() if k not in PERSONAL_KEYS}  # pyright: ignore[reportUnknownVariableType]
    return data


def main(address: str, slug: str) -> None:
    out_dir = FIXTURES / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    def save(path: str, data: Any) -> None:
        target = out_dir / FIXTURE_FILES[path]
        target.write_text(json.dumps(_strip_personal(data), indent=2) + "\n")
        print(f"wrote {target}")

    try:
        build_brief(
            address, OwnerFacts(), RentCastProvider.from_env(on_response=save, usage=usage_log())
        )
    except RentsmartError as err:
        print(f"stopped early ({type(err).__name__}): {err.message}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
