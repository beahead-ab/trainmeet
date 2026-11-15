"""EVN and the check digit: TrainCatalog's tests (catalog/test_modulkort_fields.py, EvnTests),
ported with the module (CAT-27, CAT-57–CAT-60)."""

from __future__ import annotations

import pytest

from catalog import evn


def test_check_digits_from_stefans_examples() -> None:
    assert evn.check_digit("31763933013") == 1
    assert evn.check_digit("21760429045") == 2


def test_twelve_digits_are_read_and_a_wrong_check_digit_is_reported() -> None:
    good = evn.describe("31 76 393 3 013-1")
    assert good is not None
    assert (good.text, good.country_letters, good.valid) == ("31 76 393 3 013-1", "N", True)
    bad = evn.describe("31 76 393 3 013-7")
    assert bad is not None
    assert not bad.valid
    assert (bad.check, bad.given) == (1, 7)
    eleven = evn.describe("31 76 393 3 013")  # eleven digits: the check digit is computed
    assert eleven is not None
    assert eleven.text == "31 76 393 3 013-1"
    assert eleven.given is None


def test_seven_digits_need_both_codes() -> None:
    found = evn.describe("393 3 013", "31", "76")
    assert found is not None and found.text == "31 76 393 3 013-1"
    assert evn.describe("393 3 013", "31", "") is None
    assert evn.describe("393 3 013") is None
    swedish = evn.describe("042 9 045", "21", "74")
    assert swedish is not None and swedish.country_letters == "S"


def test_national_number_with_its_own_check_digit_is_not_uic() -> None:
    # Eight digits are only UIC when the check digit matches; otherwise a national number.
    assert evn.describe("6018 035-3", "21", "74") is None
    matching = evn.describe("393 3 013-1", "31", "76")
    assert matching is not None and matching.valid
    # In the UIC grouping with both codes given, a mismatch is a wrong check digit: reported.
    wrong = evn.describe("393 3 013-7", "31", "76")
    assert wrong is not None
    assert (wrong.valid, wrong.check, wrong.given) == (False, 1, 7)


def test_the_number_is_never_rewritten() -> None:
    painted = "21 74 245 2 253-9"
    found = evn.describe(painted)
    assert found is not None and found.text == "21 74 245 2 253-0"
    assert painted == "21 74 245 2 253-9"


@pytest.mark.parametrize("number", ["", "Rc6 1340", "1340", "12-34", "1234567890123"])
def test_other_numbers_are_not_evn(number: str) -> None:
    assert evn.describe(number) is None


def test_check_digit_wants_eleven_digits() -> None:
    with pytest.raises(ValueError, match="eleven digits"):
        evn.check_digit("123")
