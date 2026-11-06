"""The TMBox 16×2 view, ported from the old Server's terminal16 pilot tests.

Two boxes on Provbanan: Norrby (Nby) sends, Åsen (Ån) receives. Åsen lies to the right of
Norrby, so Norrby writes 101>Ån and Åsen writes Nby>101, as KNB and DY did in the old tests.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any
from uuid import uuid4

import pytest

from contracts.meet import MeetPackage
from contracts.terminal import Frame
from drift.engine import Drift
from drift.terminal import Box, Boxes

START = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def idle(name: str, width: int = 16) -> str:
    """A box with nothing going on names its place on the first row, centred."""
    return (" " * ((width - len(name)) // 2) + name).ljust(width)


class Lab:
    """Drift and two boxes, with a wall clock the test moves."""

    def __init__(self) -> None:
        raw = files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
        self.package = MeetPackage.model_validate_json(raw)
        self.now = START
        self.drift = Drift(self.package, [], now=self.now)
        self.drift.start(self.now)
        self.boxes: dict[str, Box] = {
            "nby": Box(client_id="box-nby", name="Box Norrby"),
            "asn": Box(client_id="box-asn", name="Box Åsen"),
            "sjv": Box(client_id="box-sjv", name="Box Sjövik"),
        }
        view = self.view()
        for place, box in self.boxes.items():
            view.assign(box, place)

    def add(self, place: str) -> None:
        """One more box, given a place: Mellanå has none to begin with."""
        self.boxes[place] = Box(client_id=f"box-{place}", name=f"Box {place}")
        self.view().assign(self.boxes[place], place)

    def departure(self) -> None:
        """101 asked for at Norrby, cleared at Åsen and sent on its way."""
        self.lookup("101")
        self.lookup("101", "asn")
        self.accept("asn", "#")
        self.accept("nby", "#")

    def view(self) -> Boxes:
        boxes = {box.client_id: box for box in self.boxes.values()}
        view = Boxes(self.drift, boxes, epoch="e1", now=self.now)
        view.catch_up()
        return view

    def frame(self, place: str) -> dict[str, Any]:
        return self.view().frame(self.boxes[place])

    def lines(self, place: str) -> list[str]:
        return list(self.frame(place)["lines"])

    def send(self, place: str, key: str, **extra: Any) -> dict[str, Any]:
        view = self.view()
        box = self.boxes[place]
        body = {"command_id": uuid4().hex, "view_token": view.frame(box)["view_token"], "key": key}
        return view.press(box, {**body, **extra})

    def accept(self, place: str, key: str) -> dict[str, Any]:
        result = self.send(place, key)
        assert result["status"] == "accepted", result
        for box in self.boxes:
            frame = self.frame(box)
            assert [len(row) for row in frame["lines"]] == [16, 16]
        return result

    def lookup(self, number: str, place: str = "nby") -> dict[str, Any]:
        context = self.frame(place)["entry"]["context"]
        result = self.send(place, "#", train_number=number, entry_context=context)
        assert result["status"] == "accepted", result
        return result

    def wait(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def kinds(self) -> list[str]:
        return [event.kind.value for event in self.drift.history[1:]]


@pytest.fixture
def lab() -> Lab:
    return Lab()


def test_initial_frame_names_the_place_and_follows_the_contract(lab: Lab) -> None:
    frame = lab.frame("nby")
    Frame.model_validate(frame)
    assert frame["lines"][0] == idle("Norrby")
    assert frame["lines"][1] == "Nr# A:Kö   06:00"
    assert frame["station_code"] == "Nby"
    assert frame["keys"]["A"]["label"] == "Förfrågningskö (0 väntar)"


def test_full_clearance_chain(lab: Lab) -> None:
    lab.lookup("101")
    assert "101?Ån" in lab.lines("nby")[0]
    assert "#" not in lab.frame("nby")["keys"]
    # Åsen was idle: the request opens there by itself, #Ja *Nej.
    asen = lab.frame("asn")
    assert asen["lines"][0] == "Nby?101      1/1"
    assert asen["lines"][1].startswith("#Ja *Nej")
    assert asen["keys"]["#"]["label"] == "Ge klart"
    assert asen["attention"]["kind"] == "incoming_request"
    lab.accept("asn", "#")
    assert "101>Ån" in lab.lines("nby")[0]
    assert lab.frame("nby")["keys"]["#"]["label"] == "Rapportera avgång"
    lab.wait(3)  # Two sounds within two seconds are one; the more important one wins.
    lab.accept("nby", "#")
    assert "101▶Ån" in lab.lines("nby")[0]
    assert "Nby▶101" in lab.lines("asn")[0]
    assert lab.frame("asn")["attention"]["kind"] == "incoming_train"
    assert lab.frame("asn")["keys"]["#"]["label"] == "Rapportera ankomst"
    lab.accept("asn", "#")
    assert lab.kinds() == [
        "clearance.requested",
        "clearance.answered",
        "train.departed",
        "train.arrived",
    ]
    # The receiver is told the track, the sender that the train was received.
    assert lab.lines("asn") == ["101 ANK SP1     ", "Nby        06:00"]
    assert lab.lines("nby") == ["101 MOTTAGET    ", "Ån         06:00"]
    assert lab.frame("nby")["status"].startswith("Tåg 101 mottaget i Åsen")
    lab.wait(5)
    # Both go back to their start screens by themselves: the section is free again.
    assert lab.lines("nby")[0] == idle("Norrby")
    assert lab.lines("asn")[0] == idle("Åsen")
    assert all(not case.active for case in lab.drift.cases.values())


def test_the_receiver_can_also_type_the_number(lab: Lab) -> None:
    """The old test's way: the receiver types 39# and answers with #."""
    lab.lookup("101")
    lab.accept("asn", "B")  # Away from the queue without answering.
    assert lab.lines("asn")[0].startswith("Nby?101")
    lab.lookup("101", "asn")
    assert lab.frame("asn")["keys"]["#"]["label"] == "Ge klart"
    lab.accept("asn", "#")
    assert "101>Ån" in lab.lines("nby")[0]


def test_showing_a_request_is_not_answering_it(lab: Lab) -> None:
    lab.lookup("101")
    lab.frame("asn")
    assert lab.kinds() == ["clearance.requested"]


def test_rejection_notifies_sender_without_departure(lab: Lab) -> None:
    lab.lookup("101")
    lab.accept("asn", "*")
    assert lab.lines("asn")[0].startswith("NEKA 101?")
    lab.accept("asn", "#")
    assert lab.lines("asn")[0].startswith("101 NEKAT")
    assert "NEKAT" in lab.lines("nby")[0]
    assert lab.lines("nby")[1].startswith("Ån")
    assert lab.frame("nby")["attention"]["kind"] == "request_denied"
    lab.wait(3)
    assert lab.lines("nby")[0] == idle("Norrby")


def test_star_keeps_the_incoming_request(lab: Lab) -> None:
    lab.lookup("101")
    lab.accept("asn", "*")
    lab.accept("asn", "*")
    assert lab.kinds() == ["clearance.requested"]


def test_cancel_pending_requires_explicit_confirmation(lab: Lab) -> None:
    lab.lookup("101")
    lab.accept("nby", "*")
    assert lab.lines("nby") == ["ÅTER 101?       ", "#Ja *Nej   06:00"]
    lab.accept("nby", "#")
    assert lab.lines("nby")[0].startswith("101 ÅTERTAGET")
    assert lab.lines("nby")[1].startswith("Ån")
    # The receiver is told, with the sender's code, and is not left on its request.
    assert lab.lines("asn")[0].startswith("101 ÅTERTAGET")
    assert lab.lines("asn")[1].startswith("Nby")
    assert lab.kinds() == ["clearance.requested", "clearance.cancelled"]


def test_no_cancel_after_departure(lab: Lab) -> None:
    lab.lookup("101")
    lab.accept("asn", "#")
    lab.accept("nby", "#")
    assert "*" not in lab.frame("nby")["keys"] or lab.frame("nby")["keys"]["*"]["acts"] is False


def test_unknown_train_says_so_and_goes_home(lab: Lab) -> None:
    lab.lookup("999")
    assert lab.lines("nby")[0].startswith("INGET TÅG")
    lab.wait(3)
    assert lab.lines("nby")[0] == idle("Norrby")


def test_an_empty_queue_says_so_and_goes_home_by_itself(lab: Lab) -> None:
    lab.accept("asn", "A")
    assert lab.lines("asn")[0].startswith("INGA FRÅGOR")
    lab.wait(3)
    assert lab.lines("asn")[0] == idle("Åsen")


def test_direct_section_reserves_without_the_receiver(lab: Lab) -> None:
    """Mellanå–Sjövik has direct clearance: 102# at Sjövik is cleared at once."""
    lab.lookup("102", "sjv")
    assert "Mlå<102" in lab.lines("sjv")[0]
    assert lab.frame("sjv")["keys"]["#"]["label"] == "Rapportera avgång"
    assert lab.kinds() == ["clearance.requested", "clearance.answered"]


def test_stale_view_rejected_after_another_box_changes_state(lab: Lab) -> None:
    lab.lookup("101")
    token = lab.frame("nby")["view_token"]
    lab.accept("asn", "#")
    view = lab.view()
    answer = view.press(lab.boxes["nby"], {"command_id": "old-1", "view_token": token, "key": "*"})
    assert answer["status"] == "rejected"
    assert "Läget ändrades" in answer["message"]


def test_duplicate_command_is_idempotent_and_id_cannot_be_repurposed(lab: Lab) -> None:
    view = lab.view()
    token = view.frame(lab.boxes["asn"])["view_token"]
    first = view.press(lab.boxes["asn"], {"command_id": "same", "view_token": token, "key": "A"})
    again = view.press(lab.boxes["asn"], {"command_id": "same", "view_token": token, "key": "A"})
    other = view.press(lab.boxes["asn"], {"command_id": "same", "view_token": token, "key": "B"})
    assert (first["status"], again["status"], other["status"]) == (
        "accepted",
        "duplicate",
        "rejected",
    )


def test_client_cannot_supply_action_or_place(lab: Lab) -> None:
    answer = lab.send("nby", "#", action="clearance.request")
    assert answer["status"] == "rejected"
    answer = lab.send("nby", "#", station_id="asn")
    assert answer["status"] == "rejected"


def test_input_rejects_six_digits_letters_and_foreign_context(lab: Lab) -> None:
    context = lab.frame("nby")["entry"]["context"]
    for number, entry in (("123456", context), ("10a", context), ("101", "e1:other:nby")):
        answer = lab.send("nby", "#", train_number=number, entry_context=entry)
        assert answer["status"] == "rejected"


def test_a_box_without_a_place_waits(lab: Lab) -> None:
    box = Box(client_id="box-new", name="Box 7")
    view = Boxes(lab.drift, {box.client_id: box}, epoch="e1", now=lab.now)
    frame = view.frame(box)
    assert frame["lines"][0] == idle("VÄNTAR PÅ")
    assert frame["waiting"] is True
    Frame.model_validate(frame)
    answer = view.press(box, {"command_id": "w-1", "view_token": frame["view_token"], "key": "A"})
    assert answer["status"] == "rejected"


def test_a_box_assigned_later_is_not_told_what_happened_before(lab: Lab) -> None:
    lab.lookup("101")
    late = Box(client_id="box-late", name="Box sen")
    lab.boxes["late"] = late
    view = lab.view()
    view.assign(late, "nby")
    assert late.receipts == []
    assert "101?Ån" in lab.lines("late")[0]


def test_every_frame_can_be_drawn_on_the_box(lab: Lab) -> None:
    lab.lookup("101")
    lab.accept("asn", "#")
    lab.accept("nby", "#")
    for place in lab.boxes:
        frame = lab.frame(place)
        assert len(frame["lcd"]["glyphs"]) <= 8
        assert json.dumps(frame, ensure_ascii=False)


# --- Tracks, FLYTTA HIT, through trains and putting away (old Server 2.1.0–4.12) ----------


def test_a_train_never_sent_can_be_placed_from_its_number(lab: Lab) -> None:
    """Casper, 2026-10-02: the receiver places a train nobody sent, on the timetable's track,
    so the game goes on. Since issue #115 the box asks first whether to move it here."""
    frame = lab.lookup("102")["frame"]  # Åsen never sent 102, which ends at Norrby.
    assert frame["lines"] == ["FLYTTA 102 HIT? ", "#Ja B:Sp   06:00"]
    assert frame["keys"]["#"]["label"] == "Flytta hit"
    assert frame["keys"]["#"]["short"] == "FLYTTA"
    assert lab.kinds() == []  # A lookup sends nothing.
    lab.accept("nby", "#")
    assert lab.kinds() == ["train.moved_here"]
    assert lab.drift.tracks["t102-asn"] == "2"
    assert "102 ANK SP2" in lab.lines("nby")[0]
    view = lab.view()
    assert "t102-asn" not in view._candidates(lab.boxes["asn"])


def test_another_track_for_a_train_moved_here(lab: Lab) -> None:
    lab.lookup("102")
    lab.accept("nby", "B")
    assert lab.lines("nby") == ["102 SPÅR 2      ", "#In C/D:Sp 06:00"]
    lab.accept("nby", "D")
    assert lab.lines("nby")[0].startswith("102 SPÅR")
    chosen = lab.lines("nby")[0].split()[-1]
    lab.accept("nby", "#")
    assert lab.drift.tracks["t102-asn"] == chosen != "2"


def test_a_through_train_never_seen_to_come_is_moved_here_first(lab: Lab) -> None:
    """Benny #170, Casper 2026-10-09: Norrby never sent 101. At Åsen 101# asks FLYTTA 101
    HIT? and asks Mellanå nothing; once it is here, the next 101# asks Mellanå at once."""
    lab.add("mla")
    frame = lab.lookup("101", "asn")["frame"]
    assert frame["lines"][0] == "FLYTTA 101 HIT? "
    assert frame["keys"]["#"]["label"] == "Flytta hit"
    assert lab.frame("mla")["requests"]["count"] == 0, "nothing asked of Mellanå"
    lab.accept("asn", "#")  # Moved here on its planned track.
    assert "t101-nby" in lab.drift.arrived  # Norrby's part is over.
    assert "t101-nby" not in lab.view()._candidates(lab.boxes["nby"])
    lab.accept("asn", "#")  # Dismiss the arrival notice.
    frame = lab.lookup("101", "asn")["frame"]  # Here now: the departure, asked at once.
    assert frame["lines"][0].endswith("101?Mlå"), frame["lines"]


def test_a_departure_picked_from_the_list_still_takes_the_train_along(lab: Lab) -> None:
    """The departure picked in the list can be asked for before the train is seen to come;
    sent on, it jumps here (Casper, 2026-10-02)."""
    lab.add("mla")
    lab.boxes["asn"].selected, lab.boxes["asn"].screen = "t101-asn", "detail"
    lab.accept("asn", "#")  # Asks Mellanå.
    lab.lookup("101", "mla")
    lab.accept("mla", "#")
    frame = lab.frame("asn")
    assert frame["keys"]["#"]["label"] == "Rapportera avgång"
    assert frame["lines"][0] == "         101>Mlå"
    lab.accept("asn", "#")
    assert "t101-nby" in lab.drift.arrived  # Norrby's part is over.
    assert lab.lookup("101", "mla")["frame"]["keys"]["#"]["label"] == "Rapportera ankomst"


def test_a_through_train_in_the_usual_order(lab: Lab) -> None:
    lab.add("mla")
    lab.lookup("101")  # Norrby asks Åsen.
    frame = lab.lookup("101", "asn")["frame"]  # The request, not the departure.
    assert frame["keys"]["#"]["label"] == "Ge klart"
    lab.accept("asn", "#")
    lab.accept("nby", "#")
    assert lab.lookup("101", "asn")["frame"]["keys"]["#"]["label"] == "Rapportera ankomst"
    lab.accept("asn", "#")
    lab.accept("asn", "#")  # Dismiss the arrival notice.
    frame = lab.lookup("101", "asn")["frame"]  # Arrived: the departure, asked at once.
    assert frame["lines"][0].endswith("101?Mlå"), frame["lines"]


def test_star_leaves_track_picker_without_arrival(lab: Lab) -> None:
    lab.departure()
    lab.accept("asn", "B")
    lab.accept("asn", "D")
    frame = lab.accept("asn", "*")["frame"]
    assert frame["keys"]["#"]["label"] == "Rapportera ankomst"
    assert "t101-nby" not in lab.drift.arrived
    assert lab.kinds()[-1] == "train.departed"


def test_after_clearance_hash_never_takes_the_train_in(lab: Lab) -> None:
    """The # after #Ja must not receive the train. One the sender never reported departed
    can still be placed, with B and then #."""
    lab.lookup("101")
    lab.lookup("101", "asn")
    lab.accept("asn", "#")
    frame = lab.frame("asn")
    assert "#" not in frame["keys"]
    assert frame["keys"]["B"]["label"] == "Placera på spår…"
    assert lab.send("asn", "#")["status"] == "rejected"
    assert "t101-nby" not in lab.drift.arrived
    lab.accept("asn", "B")
    lab.accept("asn", "#")
    assert lab.drift.tracks["t101-nby"] == "1"
    assert lab.drift.active_case("t101-nby") is None


def test_arrival_track_override_preserves_plan(lab: Lab) -> None:
    lab.departure()
    lab.accept("asn", "B")
    lab.accept("asn", "D")
    assert "SPÅR 2" in lab.lines("asn")[0]
    lab.accept("asn", "#")
    assert lab.drift.tracks["t101-nby"] == "2"
    assert lab.drift.planned_track(lab.drift.legs["t101-nby"]) == "1"
    assert lab.lines("asn")[0] == "101 ANK SP2     "


def test_an_occupied_track_does_not_stop_the_arrival(lab: Lab) -> None:
    """Casper, 2026-10-02: taken in all the same, and the box says so."""
    lab.lookup("4501", "asn")  # 4501 is moved to Åsen's track 1 first.
    lab.accept("asn", "#")
    lab.accept("asn", "#")  # Dismiss its notice.
    lab.departure()
    lab.accept("asn", "#")
    assert lab.lines("asn")[0] == "101 UPPT SPÅR   "
    assert lab.drift.tracks["t101-nby"] == "1"
    assert lab.drift.active_case("t101-nby") is None
    assert "101 MOTTAGET" in lab.lines("nby")[0], "the sender is still told"


def test_alternate_arrival_track_also_notifies_sender(lab: Lab) -> None:
    lab.departure()
    lab.accept("asn", "B")
    lab.accept("asn", "D")
    lab.accept("asn", "#")
    assert lab.drift.tracks["t101-nby"] == "2"
    assert "101 MOTTAGET" in lab.lines("nby")[0]


def test_the_box_says_the_train_ends_here_and_hash_puts_it_away(lab: Lab) -> None:
    """Casper, 2026-10-10: at a manned place the box says the train ends here, and the
    operator reports it put away. Then the track is free."""
    lab.lookup("102")
    lab.accept("nby", "#")  # 102 is here, on track 2, and goes no further.
    lab.accept("nby", "#")  # Dismiss the arrival notice.
    frame = lab.frame("nby")
    assert frame["keys"]["B"]["label"] == "Aktiva tåg (1)", "the train to put away is active"
    frame = lab.accept("nby", "B")["frame"]
    assert [frame["lines"][0].strip(), frame["lines"][1][:11].strip()] == [
        "102 SLUTAR HÄR",
        "#Undan",
    ]
    assert frame["keys"]["#"]["label"] == "Ställ undan"
    assert frame["keys"]["#"]["acts"] is True, "putting away is a traffic act"
    assert "Tåg 102 slutar här." in frame["status"]
    frame = lab.accept("nby", "#")["frame"]
    assert frame["lines"][0].strip() == "UNDANSTÄLLT"
    assert frame["lines"][1][:11].strip() == "102"
    assert lab.kinds()[-1] == "train.set_aside"
    assert lab.drift.occupant("nby", "2") is None, "the track is free"
    frame = lab.accept("nby", "#")["frame"]  # OK.
    assert frame["keys"]["B"]["label"] == "Aktiva tåg (0)", "nothing more to do with 102"


def test_a_train_that_goes_on_is_not_offered_to_put_away(lab: Lab) -> None:
    lab.lookup("101", "asn")
    lab.accept("asn", "#")  # 101 moved to Åsen; it goes on to Mellanå.
    lab.accept("asn", "#")
    assert "SLUTAR" not in " ".join(lab.accept("asn", "B")["frame"]["lines"])


def test_every_track_notice_fits_on_the_box(lab: Lab) -> None:
    box = lab.boxes["nby"]
    for notice in ("12345 ANK SP12A", "12345 UPPT SPÅR", "UNDANSTÄLLT", "FLERA TÅG ADMIN"):
        box.notice, box.notice_hint, box.notice_until = notice, "12345", None
        assert [len(line) for line in lab.frame("nby")["lines"]] == [16, 16]
