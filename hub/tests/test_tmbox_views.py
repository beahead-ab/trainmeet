"""The box's side, the 20×4 display and the five languages, ported from the old Server's
test_terminal16_sides.py, test_terminal16_20x4.py and test_tmbox_language.py.

Provbanan: Norrby – Åsen – Mellanå – Sjövik, left to right. At Åsen, Norrby lies to the left
and Mellanå to the right, as Vagnsta had one neighbour on each side in the old tests.
"""

from __future__ import annotations

import pytest

from contracts.terminal import Frame
from drift import terminal_text
from drift.terminal import Box
from hub.tests.test_tmbox_terminal import Lab

BLANK = " " * 20


def fit(left: str = "", right: str = "", width: int = 20) -> str:
    return left + " " * (width - len(left) - len(right)) + right


def idle(name: str, width: int = 20) -> str:
    return (" " * ((width - len(name)) // 2) + name).ljust(width)


@pytest.fixture
def lab() -> Lab:
    return Lab()


# --- Sides (Casper, 2026-10-01) ---------------------------------------------------------


@pytest.fixture
def sided() -> Lab:
    """Åsen has a box for each side and one for both; Mellanå has a box too."""
    lab = Lab()
    lab.add("mla")
    for name, side in (("asn-left", "left"), ("asn-right", "right")):
        lab.boxes[name] = Box(client_id=f"box-{name}", name=name)
        lab.view().assign(lab.boxes[name], "asn", side)
    return lab


def trains(lab: Lab, name: str) -> set[str]:
    view = lab.view()
    return {view.legs[key].train.number for key in view._candidates(lab.boxes[name])}


def keys(lab: Lab, name: str) -> set[str]:
    return set(lab.view()._candidates(lab.boxes[name]))


def test_each_box_sees_only_the_trains_on_its_side(sided: Lab) -> None:
    both, left, right = keys(sided, "asn"), keys(sided, "asn-left"), keys(sided, "asn-right")
    assert left | right == both, "both: the whole place, as before"
    assert not left & right
    view = sided.view()
    assert {view.legs[key].section.id for key in left} == {"s-nby-asn"}
    assert {view.legs[key].section.id for key in right} == {"s-asn-mla"}
    assert "t101-nby" in left and "t101-asn" in right


def test_searching_a_train_on_the_other_side_says_so(lab: Lab) -> None:
    """Norrby's only section goes to the right; a box there for the left has no trains."""
    lab.view().assign(lab.boxes["nby"], "nby", "left")
    assert lab.lookup("101")["frame"]["lines"][0].strip() == "ANNAN SIDA"
    lab.accept("nby", "#")
    assert lab.lookup("999")["frame"]["lines"][0].strip() == "INGET TÅG"
    assert lab.kinds() == []


def test_a_through_train_is_split_between_the_two_boxes(sided: Lab) -> None:
    """The box for Norrby's side moves 101 here; the box for Mellanå's side asks Mellanå."""
    frame = sided.lookup("101", "asn-left")["frame"]
    assert frame["lines"][0].strip() == "FLYTTA 101 HIT?"
    assert frame["keys"]["#"]["label"] == "Flytta hit"
    sided.accept("asn-left", "*")
    frame = sided.lookup("101", "asn-right")["frame"]
    assert frame["lines"][0].endswith("101?Mlå"), frame["lines"]


def test_a_request_reaches_only_the_box_on_its_side(sided: Lab) -> None:
    sided.lookup("101")  # Norrby asks Åsen.
    left, right, both = (sided.frame(name) for name in ("asn-left", "asn-right", "asn"))
    assert left["requests"]["count"] == 1
    assert left["lines"][0] == "Nby?101      1/1"
    assert left["lines"][1].startswith("#Ja *Nej")
    assert both["requests"]["count"] == 1
    assert right["requests"]["count"] == 0
    assert right["lines"][0] == idle("Åsen", 16), "nothing pushed to the other side's box"
    assert right["lines"][1].startswith("Nr# A:Kö")
    assert right["attention"]["kind"] is None
    sided.accept("asn-left", "#")  # Ge klart.
    sided.accept("nby", "#")  # Avgång.
    left, right, both = (sided.frame(name) for name in ("asn-left", "asn-right", "asn"))
    assert (left["active"]["count"], both["active"]["count"], right["active"]["count"]) == (1, 1, 0)
    assert right["lines"][0] == idle("Åsen", 16)
    assert "101" in left["lines"][0], "still shows the train it cleared"
    sided.accept("asn-left", "#")  # Ankomst.
    assert "MOTTAGET" in sided.lines("nby")[0]


def test_the_receipt_goes_to_the_senders_side_only(sided: Lab) -> None:
    sided.lookup("101", "asn-right")  # Asks Mellanå at once.
    assert sided.frame("mla")["requests"]["count"] == 1
    sided.accept("mla", "#")
    assert sided.frame("asn-left")["active"]["count"] == 0
    sided.wait(3)
    sided.accept("asn-right", "#")  # Avgång; 101 jumps to Åsen.
    sided.accept("mla", "#")  # Ankomst.
    assert "MOTTAGET" in sided.lines("asn-right")[0]
    assert "MOTTAGET" in sided.lines("asn")[0]
    assert "MOTTAGET" not in sided.lines("asn-left")[0]


def test_changing_side_starts_the_box_afresh(sided: Lab) -> None:
    box = sided.boxes["asn-left"]
    before = sided.frame("asn-left")
    sided.view().assign(box, "asn", "right")
    assert keys(sided, "asn-left") == keys(sided, "asn-right")
    fresh = sided.frame("asn-left")
    assert fresh["view_token"] != before["view_token"]
    # 101# typed on the old side would move it here: it must do nothing.
    stale = sided.view().press(
        box,
        {
            "command_id": "old-side",
            "view_token": before["view_token"],
            "key": "#",
            "train_number": "101",
            "entry_context": before["entry"]["context"],
        },
    )
    assert stale["status"] == "rejected", "a key pressed for the old side does nothing"
    assert sided.kinds() == []


def test_a_box_given_a_place_with_requests_waiting_opens_them(lab: Lab) -> None:
    lab.lookup("101")
    late = Box(client_id="box-late", name="Box sen")
    lab.boxes["late"] = late
    lab.view().assign(late, "asn")
    assert late.screen == "requests"
    assert lab.lines("late")[0] == "Nby?101      1/1"


def test_a_side_or_language_the_box_does_not_have_is_refused(lab: Lab) -> None:
    box = lab.boxes["nby"]
    with pytest.raises(ValueError):
        lab.view().assign(box, "nby", "middle")
    with pytest.raises(ValueError):
        lab.view().assign(box, "nby", "both", "xx")
    assert (box.side, box.language) == ("both", "sv")


# --- The 20×4 display (trainmeet-tmbox #39) ---------------------------------------------


@pytest.fixture
def tall() -> Lab:
    """Every box a 20×4."""
    lab = Lab()
    for box in lab.boxes.values():
        box.rows, box.cols = 4, 20
    return lab


def press(lab: Lab, name: str, key: str) -> list[str]:
    result = lab.send(name, key)
    assert result["status"] == "accepted", result
    check_tall(lab)
    return list(result["frame"]["lines"])


def type_number(lab: Lab, name: str, number: str) -> list[str]:
    context = lab.frame(name)["entry"]["context"]
    result = lab.send(name, "#", train_number=number, entry_context=context)
    assert result["status"] == "accepted", result
    check_tall(lab)
    return list(result["frame"]["lines"])


def check_tall(lab: Lab) -> None:
    """Whatever a box shows, it is four whole rows of twenty, and it can be drawn."""
    for name in lab.boxes:
        frame = lab.frame(name)
        assert (frame["rows"], frame["cols"]) == (4, 20)
        assert [len(line) for line in frame["lines"]] == [20] * 4, frame["lines"]
        assert [len(cells) for cells in frame["lcd"]["cells"]] == [20] * 4
        Frame.model_validate(frame)


def test_an_idle_box_names_its_place_and_lists_the_two_nearest_trains(tall: Lab) -> None:
    assert tall.lines("nby") == [
        idle("Norrby"),
        fit("101 AVG Ån", "06:00"),
        fit("102 ANK Ån", "06:34"),
        fit("Nr# A:Kö", "06:00"),
    ]
    check_tall(tall)


def test_the_entry_picture_keeps_the_digits_where_they_were(tall: Lab) -> None:
    entry = tall.frame("nby")["entry"]
    assert entry["lines"] == [fit("TÅG: _____"), BLANK, BLANK, fit("#Sök B:Del", "06:00")]
    assert (entry["row"], entry["column"], entry["max_length"]) == (0, 5, 5)
    assert len(entry["lcd"]["cells"]) == 4


def test_a_train_from_request_to_arrival(tall: Lab) -> None:
    type_number(tall, "nby", "101")
    assert tall.lines("nby") == [
        fit("", "101?Ån"),
        fit("Till Åsen", "06:00"),
        fit("Väntar svar", "Sp 1"),
        fit("*Åter B:Öv", "06:00"),
    ]
    assert tall.lines("asn") == [
        fit("Nby?101", "1/1"),
        fit("Från Norrby", "06:08"),
        fit("Vill skicka", "Sp 1"),
        fit("#Ja *Nej", "06:00"),
    ]
    press(tall, "asn", "#")
    assert tall.lines("nby") == [
        fit("", "101>Ån"),
        fit("Till Åsen", "06:00"),
        fit("Klar att avgå", "Sp 1"),
        fit("#Avg *Åter", "06:00"),
    ]
    assert tall.lines("asn") == [
        fit("Nby>101"),
        fit("Från Norrby", "06:08"),
        fit("Klarerad", "Sp 1"),
        fit("C/D A:Kö", "06:00"),
    ]
    press(tall, "nby", "#")
    assert tall.lines("nby") == [
        fit("", "101▶Ån"),
        fit("Till Åsen", "06:00"),
        fit("Avgått", "Sp 1"),
        fit("C/D A:Kö", "06:00"),
    ]
    assert tall.lines("asn") == [
        fit("Nby▶101"),
        fit("Från Norrby", "06:08"),
        fit("På väg hit", "Sp 1"),
        fit("#In B:Sp", "06:00"),
    ]
    press(tall, "asn", "#")
    # The receipt names the other place in full on row two and leaves row three empty.
    assert tall.lines("nby") == [fit("101 MOTTAGET"), fit("Åsen"), BLANK, fit("Ån", "06:00")]
    assert tall.lines("asn") == [fit("101 ANK SP1"), fit("Norrby"), BLANK, fit("Nby", "06:00")]
    tall.wait(5)
    # Back at the start screen; 101 is done at Norrby.
    assert tall.lines("nby") == [
        idle("Norrby"),
        fit("102 ANK Ån", "06:34"),
        fit("4501 AVG Ån", "06:35"),
        fit("Nr# A:Kö", "06:00"),
    ]


def test_a_refusal_and_a_withdrawal_name_the_other_place(tall: Lab) -> None:
    type_number(tall, "nby", "101")
    press(tall, "asn", "*")
    assert tall.lines("asn") == [
        fit("NEKA 101?"),
        fit("Från Norrby", "06:08"),
        fit("Vill skicka", "Sp 1"),
        fit("#Ja *Nej", "06:00"),
    ]
    press(tall, "asn", "#")
    assert tall.lines("nby") == [fit("101 NEKAT"), fit("Åsen"), BLANK, fit("Ån", "06:00")]
    assert tall.lines("asn") == [fit("101 NEKAT"), fit("Norrby"), BLANK, fit("Nby", "06:00")]
    tall.wait(3.5)
    assert tall.lines("nby")[0] == idle("Norrby")
    type_number(tall, "nby", "101")
    press(tall, "nby", "*")
    assert tall.lines("nby") == [
        fit("ÅTER 101?"),
        fit("Till Åsen", "06:00"),
        fit("Väntar svar", "Sp 1"),
        fit("#Ja *Nej", "06:00"),
    ]
    press(tall, "nby", "#")
    assert tall.lines("nby") == [fit("101 ÅTERTAGET"), fit("Åsen"), BLANK, fit("Ån", "06:00")]
    assert tall.lines("asn") == [
        fit("101 ÅTERTAGET"),
        fit("Norrby"),
        BLANK,
        fit("Nby", "06:00"),
    ]


def test_a_notice_without_another_place_has_empty_rows_two_and_three(tall: Lab) -> None:
    type_number(tall, "nby", "123")
    assert tall.lines("nby") == [fit("INGET TÅG"), BLANK, BLANK, fit("", "06:00")]


def test_browsing_the_timetable_names_the_state_of_each_train(tall: Lab) -> None:
    press(tall, "nby", "#")
    assert tall.lines("nby") == [
        fit("101 AVG", "06:00"),
        fit("Till Åsen", "06:00"),
        fit("Ej begärd", "Sp 1"),
        fit("#Välj A:Kö", "06:00"),
    ]
    press(tall, "nby", "B")  # Arrivals first.
    assert tall.lines("nby") == [
        fit("102 ANK", "06:34"),
        fit("Från Åsen", "06:34"),
        fit("Ej skickad", "Sp 2"),
        fit("#Välj A:Kö", "06:00"),
    ]


def test_a_train_nobody_sent_is_moved_here_and_a_track_can_be_chosen(tall: Lab) -> None:
    type_number(tall, "nby", "102")
    assert tall.lines("nby") == [
        fit("FLYTTA 102 HIT?"),
        fit("Från Åsen", "06:34"),
        fit("Ej skickad", "Sp 2"),
        fit("#Ja B:Sp", "06:00"),
    ]
    press(tall, "nby", "B")
    # The track on row three is the planned one; the chosen one is on row one.
    assert tall.lines("nby")[0] == fit("102 SPÅR 2")
    assert tall.lines("nby")[2] == fit("Ej skickad", "Sp 2")
    press(tall, "nby", "D")
    chosen = tall.lines("nby")[0].split()[-1]
    press(tall, "nby", "#")
    assert tall.lines("nby") == [fit(f"102 ANK SP{chosen}"), fit("Åsen"), BLANK, fit("Ån", "06:00")]


def test_a_box_that_ends_here_says_so_on_four_rows(tall: Lab) -> None:
    type_number(tall, "nby", "102")
    press(tall, "nby", "#")
    press(tall, "nby", "#")
    lines = press(tall, "nby", "B")
    assert lines[0] == fit("102 SLUTAR HÄR")
    assert lines[3] == fit("#Undan", "06:00")
    lines = press(tall, "nby", "#")
    assert lines == [fit("UNDANSTÄLLT"), BLANK, BLANK, fit("102", "06:00")]


def rename(lab: Lab, place: str, name: str) -> None:
    for index, found in enumerate(lab.drift.package.places):
        if found.id == place:
            lab.drift.package.places[index] = found.model_copy(update={"name": name})


def test_rows_two_and_three_give_way_when_more_than_eight_own_characters(tall: Lab) -> None:
    rename(tall, "asn", "ÅåÄäÖöÆæØ")  # Nine own characters in one name.
    lines = type_number(tall, "nby", "101")
    assert lines == [fit("", "101?Ån"), BLANK, BLANK, fit("*Åter B:Öv", "06:00")]


def test_rows_two_and_three_give_way_for_a_character_the_box_cannot_draw(tall: Lab) -> None:
    rename(tall, "asn", "Kraków")
    lines = type_number(tall, "nby", "101")
    assert lines == [fit("", "101?Ån"), BLANK, BLANK, fit("*Åter B:Öv", "06:00")]


def test_eight_own_characters_still_fit(tall: Lab) -> None:
    rename(tall, "asn", "ÅåÄäÖöÆæ")
    lines = type_number(tall, "nby", "101")
    assert lines[1] == fit("Till ÅåÄäÖöÆæ", "06:00")


def test_a_name_too_long_for_the_row_is_cut_but_never_the_time(tall: Lab) -> None:
    rename(tall, "asn", "Åsen Norra Hållplatsen")
    lines = type_number(tall, "nby", "101")
    assert lines[1] == fit("Åsen Norra Hål", "06:00")  # "Till " gives way, then the name.
    assert lines[2] == fit("Väntar svar", "Sp 1")


def test_a_title_the_box_cannot_draw_gives_the_code_on_both_sizes(tall: Lab) -> None:
    rename(tall, "nby", "Kraków")
    assert tall.lines("nby")[0] == idle("Nby")
    for box in tall.boxes.values():
        box.rows, box.cols = 2, 16
    assert tall.lines("nby")[0] == idle("Nby", 16)
    assert tall.lines("asn") == ["      Åsen      ", "Nr# A:Kö   06:00"]


def test_a_20x4_waiting_for_a_place_says_so_on_four_rows(lab: Lab) -> None:
    box = Box(client_id="box-new", name="Box 7", rows=4, cols=20)
    lab.boxes["new"] = box
    frame = lab.view().frame(box)
    assert (frame["rows"], frame["cols"]) == (4, 20)
    assert frame["lines"] == [idle("VÄNTAR PÅ"), idle("TILLDELNING"), BLANK, BLANK]
    Frame.model_validate(frame)


# --- The five languages (Q7) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "to", "waiting", "track", "asks"),
    [
        ("sv", "Till Åsen", "Väntar svar", "Sp 1", "Vill skicka"),
        ("en", "To Åsen", "Awaiting OK", "Trk 1", "Asks to send"),
        ("da", "Til Åsen", "Venter svar", "Sp 1", "Vil sende"),
        ("nb", "Til Åsen", "Venter svar", "Sp 1", "Vil sende"),
        ("de", "Nach Åsen", "Wartet Antw.", "Gl 1", "Will senden"),
    ],
)
def test_the_proposals_last_page_in_every_language(
    tall: Lab, language: str, to: str, waiting: str, track: str, asks: str
) -> None:
    for box in tall.boxes.values():
        box.language = language
    type_number(tall, "nby", "101")
    sender, receiver = tall.lines("nby"), tall.lines("asn")
    assert sender[1] == fit(to, "06:00")
    assert sender[2] == fit(waiting, track)
    assert receiver[2] == fit(asks, track)


def test_place_names_codes_and_numbers_are_never_translated(lab: Lab) -> None:
    for box in lab.boxes.values():
        box.language = "en"
    assert lab.lines("nby") == ["     Norrby     ", "No# A:Q    06:00"]
    frame = lab.lookup("101")["frame"]
    assert frame["lines"][0].endswith("101?Ån")
    assert frame["keys"]["*"]["label"] == "Withdraw request…"
    assert frame["status"] == "Train 101 · Departure to Åsen · scheduled 06:00"
    asen = lab.frame("asn")
    assert asen["lines"][1].startswith("#Yes *No")
    assert asen["keys"]["#"]["label"] == "Approve request"
    assert asen["keys"]["#"]["short"] == "APPROVE"
    assert asen["keys"]["A"]["label"] == "Request queue (1 waiting)"
    assert asen["language"] == "en"


@pytest.mark.parametrize("language", terminal_text.LANGUAGES)
def test_a_whole_run_can_be_drawn_in_every_language(lab: Lab, language: str) -> None:
    """Every picture of a run, from the request to putting a train away, fits the box."""
    for box in lab.boxes.values():
        box.language = language
    lab.departure()
    lab.accept("asn", "B")
    lab.accept("asn", "D")
    lab.accept("asn", "#")
    lab.lookup("102")
    lab.accept("nby", "#")
    lab.accept("nby", "#")
    lab.accept("nby", "B")
    lab.accept("nby", "#")
    lab.lookup("999", "sjv")
    for name in lab.boxes:
        Frame.model_validate(lab.frame(name))


def test_the_waiting_box_speaks_its_language(lab: Lab) -> None:
    box = Box(client_id="box-new", name="Box 7", language="de")
    lab.boxes["new"] = box
    frame = lab.view().frame(box)
    assert frame["lines"] == [idle("WARTE AUF", 16), idle("ZUWEISUNG", 16)]
    assert frame["status"].startswith("Box 7 wartet")
