import pytest

from rentsmart.core.address import Address, compare, join, split_formatted

AUSTIN = Address(street="4120 Sample Dr", unit="", city="Austin", state="TX", zip="78729")
TOMANET = Address(street="12814 Tomanet Trl", unit="# A", city="Austin", state="TX", zip="78727")


@pytest.mark.parametrize(
    "typed",
    [
        "4120 Sample Dr, Austin, TX 78729",
        "4120 sample drive austin tx 78729",
        "4120 Sample Dr. Austin, Tx, 78729",
    ],
)
def test_same_address_written_differently(typed: str) -> None:
    assert compare(typed, AUSTIN) == "same"


@pytest.mark.parametrize(
    "typed",
    [
        "4120 sample dr Austin TX 78279",  # zip digits swapped
        "4120 sample Dr",  # no city, state, zip
        "4120 smple dr, Austin, TX 78729",  # misspelled street
        "4120 Sample Dr, Round Rock, TX 78729",  # different city
    ],
)
def test_similar_address(typed: str) -> None:
    assert compare(typed, AUSTIN) == "similar"


@pytest.mark.parametrize(
    "typed",
    [
        "4122 Sample Dr, Austin, TX 78729",  # different house number
        "4120 Main St, Austin, TX 78729",  # different street
        "4120 Sample Dr # 2, Austin, TX 78729",  # unit the saved address doesn't have
        "",
        "Sample Dr, Austin, TX 78729",  # no house number
    ],
)
def test_not_similar(typed: str) -> None:
    assert compare(typed, AUSTIN) is None


def test_units() -> None:
    assert compare("12814 Tomanet Trl # A, Austin, TX 78727", TOMANET) == "same"
    assert compare("12814 Tomanet Trail, Unit A, Austin TX 78727", TOMANET) == "same"
    assert compare("12814 Tomanet Trl, Apt B, Austin, TX 78727", TOMANET) is None
    # No unit typed: maybe this unit, maybe another one. Ask.
    assert compare("12814 Tomanet Trl, Austin, TX 78727", TOMANET) == "similar"


def test_join_and_split_formatted_round_trip() -> None:
    assert join("4120 Sample Dr", "Austin", "TX", "78729") == "4120 Sample Dr, Austin, TX 78729"
    assert split_formatted("12814 Tomanet Trl, # A, Austin, TX 78727") == (
        "12814 Tomanet Trl # A",
        "Austin",
        "TX",
        "78727",
    )
    assert split_formatted("4120 Sample Dr") is None
