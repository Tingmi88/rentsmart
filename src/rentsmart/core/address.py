"""Compare a typed US address with one already looked up, without calling any provider.

Used to catch typos (a swapped zip digit, a missing city, a misspelled street) before a
paid lookup. A different house number or unit is never treated as the same property.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

# One string, not 51 quoted literals.
STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "  # noqa: SIM905
    "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
# Street name similarity (0..1) above which a typed street counts as a misspelling.
STREET_SIMILARITY = 0.8

_WORDS = {
    "avenue": "ave",
    "boulevard": "blvd",
    "circle": "cir",
    "court": "ct",
    "drive": "dr",
    "highway": "hwy",
    "lane": "ln",
    "parkway": "pkwy",
    "place": "pl",
    "road": "rd",
    "street": "st",
    "terrace": "ter",
    "trail": "trl",
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northeast": "ne",
    "northwest": "nw",
    "southeast": "se",
    "southwest": "sw",
}
_UNIT_WORDS = {"#", "apt", "apartment", "unit", "ste", "suite"}
_ZIP = re.compile(r"^(\d{5})(-?\d{4})?$")

Match = Literal["same", "similar"]


@dataclass(frozen=True)
class Address:
    """A looked-up address, split the way the vendor returned it. Unit may be empty."""

    street: str
    unit: str
    city: str
    state: str
    zip: str


def join(street: str, city: str, state: str, zip_code: str) -> str:
    return f"{street}, {city}, {state} {zip_code}"


def split_formatted(text: str) -> tuple[str, str, str, str] | None:
    """Split "street[, unit], city, ST zip" into (street with unit, city, state, zip)."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 3:
        return None
    state_zip = parts[-1].split()
    if len(state_zip) != 2:
        return None
    return " ".join(parts[:-2]), parts[-2], state_zip[0], state_zip[1]


def _tokens(text: str) -> list[str]:
    raw = text.lower().replace(",", " ").replace(".", " ").split()
    out: list[str] = []
    unit_next = False
    for word in raw:
        if word in _UNIT_WORDS:
            unit_next = True
            continue
        word = _WORDS.get(word, word)
        if unit_next:
            word = "#" + word.removeprefix("#")
            unit_next = False
        out.append(word)
    return out


def compare(typed: str, saved: Address) -> Match | None:
    """Say whether `typed` names the `saved` address.

    "same": every part matches. "similar": probably the same property, with a part missing,
    mistyped, or misspelled. None: a different property (or not an address).
    """
    words = _tokens(typed)
    street = _tokens(saved.street)
    if not words or not street or not words[0][:1].isdigit() or words[0] != street[0]:
        return None
    name = street[1:]
    typed_name = words[1 : 1 + len(name)]
    ratio = SequenceMatcher(None, " ".join(typed_name), " ".join(name)).ratio()
    if ratio < STREET_SIMILARITY:
        return None

    zip_code, state, unit = "", "", ""
    city: list[str] = []
    for word in words[1 + len(name) :]:
        if m := _ZIP.match(word):
            zip_code = m.group(1)
        elif word.startswith("#"):
            unit = word
        elif word.upper() in STATES and not state:
            state = word.upper()
        else:
            city.append(word)
    saved_unit = "".join(_tokens(saved.unit))
    if unit and unit != saved_unit:
        return None

    same = (
        typed_name == name
        and unit == saved_unit
        and " ".join(city) == " ".join(_tokens(saved.city))
        and state == saved.state.upper()
        and zip_code == saved.zip[:5]
    )
    return "same" if same else "similar"
