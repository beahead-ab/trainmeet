"""The TMBox view, 16×2 or 20×4: Drift draws the screen and the box sends key presses.

Ported from the old Server's terminal16 (Terminal16Lab, Server 4.24) with its tests as the
key: the start screen with the station's name, 101# that asks at once, the request queue
under A, #Ja *Nej, the arrows ? < > ◀ ▶, the notices (NEKAT, ÅTERTAGET, ANK SP1, INGA FRÅGOR)
that go away by themselves, and the receipt MOTTAGET at the sender. The TMBox logic is
not redesigned (decided 1 November).

Also ported: another arrival track (B:Sp, UPPT SPÅR), FLYTTA HIT for a train nobody sent,
a through train asked for while on its way in, putting away a train that ended here, the
box's side (ANNAN SIDA), the 20×4 display and the five languages (drift/terminal_text.py).
Not yet: the automation, which comes after step 2.

The boxes of a run share one Drift: what one box does, the others see. What a box was told
is worked out from Drift's events, so a box that was away catches up on its next picture.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final
from uuid import uuid4

from contracts import drift as events
from contracts import station
from contracts.common import Side
from contracts.meet import ClearanceMode, Place, Section
from contracts.reasons import TEXT_SV, Reason
from drift import lcd, terminal_text
from drift.engine import Case, Drift, Leg, Refused, model_time, parse_time

PROFILE: Final = "server-16x2-pilot"
NOTICE_SECONDS: Final = 3
RECEIPT_SECONDS: Final = 5
ATTENTION_WINDOW_SECONDS: Final = 2
ATTENTION_KINDS: Final = (
    "incoming_request",
    "request_denied",
    "request_approved",
    "incoming_train",
)
PROCESSED_LIMIT: Final = 64

NAVIGATION_ACTIONS: Final = frozenset(
    {
        "back",
        "home",
        "requests",
        "next_request",
        "previous_request",
        "active",
        "next_active",
        "previous_active",
        "browse",
        "next",
        "previous",
        "filter",
        "select",
        "cancel_view",
        "reject_view",
        "tracks",
        "next_track",
        "previous_track",
    }
)

# The word a phone keypad prints under a key, by the button's label (old SHORT_LABELS).
SHORT_LABELS: Final = {
    "Stäng meddelande": "STÄNG",
    "Tillbaka": "TILLBAKA",
    "OK": "OK",
    "Visa väntande förfrågningar": "VISA KÖ",
    "Visa kommande tåg": "KOMMANDE",
    "Föregående aktiva tåg": "FÖREG",
    "Föregående tåg": "FÖREG",
    "Föregående förfrågan": "FÖREG",
    "Nästa aktiva tåg": "NÄSTA",
    "Nästa tåg": "NÄSTA",
    "Nästa förfrågan": "NÄSTA",
    "Översikt utan trafikändring": "ÖVERSIKT",
    "Ge klart": "GE KLART",
    "Neka begäran…": "NEKA",
    "Visa ankomster": "FILTER",
    "Visa avgångar": "FILTER",
    "Visa alla tåg": "FILTER",
    "Välj tåg": "VÄLJ",
    "Behåll begäran eller klartecken": "BEHÅLL",
    "Bekräfta återtagning": "ÅTERTA",
    "Tillbaka utan att neka": "TILLBAKA",
    "Bekräfta neka": "NEKA",
    "Reservera": "RESERVERA",
    "Begär klartecken": "BEGÄR",
    "Återta begäran…": "ÅTERTA",
    "Rapportera avgång": "AVGÅTT",
    "Återta klartecken…": "ÅTERTA",
    "Rapportera ankomst": "INNE",
    "Föregående spår": "FÖREG",
    "Nästa spår": "NÄSTA",
    "Ankommit på valt spår": "INNE",
    "Annat ankomstspår": "SPÅR",
    "Placera på spår": "PLACERA",
    "Placera på spår…": "PLACERA",
    "Flytta hit": "FLYTTA",
    "Ställ undan": "UNDAN",
}

# The old Server's words for the refusals a box shows; the rest use the common texts.
REFUSED_TEXT: Final = {
    Reason.CHANNEL_OCCUPIED: "Sträckan är upptagen",
    Reason.DEPARTURE_NOT_RESERVED: "Klartecken saknas",
    Reason.TRAIN_NOT_DEPARTED: "Tåget har inte avgått",
}


class LineState(StrEnum):
    FREE = "free"
    REQUESTED = "requested"
    RESERVED = "reserved"
    OCCUPIED = "occupied"


@dataclass
class Box:
    """One box: where it stands and what it shows. Kept between key presses."""

    client_id: str
    name: str
    place: str | None = None
    side: str = "both"
    language: str = "sv"
    rows: int = 2
    cols: int = 16
    screen: str = "overview"
    selected: str | None = None
    return_screen: str = "detail"
    browse_filter: str = "all"
    track: int = 0
    notice: str = ""
    notice_hint: str = ""
    notice_until: float | None = None
    receipts: list[list[str]] = field(default_factory=list)
    receipt_until: float | None = None
    revision: int = 0
    attention_seq: int = 0
    attention_kind: str | None = None
    attention_at: float | None = None
    seen: int = 0
    processed: list[list[Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> Box:
        data = json.loads(text)
        known = {name: data[name] for name in cls.__dataclass_fields__ if name in data}
        return cls(**known)


Buttons = dict[str, tuple[str, str]]
Translate = Callable[..., str]


class Boxes:
    """The boxes of one run over one Drift. `now` is the wall clock, not the model clock."""

    def __init__(self, drift: Drift, boxes: dict[str, Box], *, epoch: str, now: datetime) -> None:
        self.drift = drift
        self.boxes = boxes
        self.epoch = epoch
        self.now = now
        self.t = now.timestamp()
        # Presses the box said no to, for Logg (B15): client, place, key and why.
        self.refusals: list[tuple[str, str | None, str, str]] = []
        package = drift.package
        self.places: dict[str, Place] = {p.id: p for p in package.places}
        order = package.display.graph_order or [p.id for p in package.places]
        self._order = {place: index for index, place in enumerate(order)}

    # --- Drift's state seen from a box --------------------------------------------------

    @property
    def legs(self) -> dict[str, Leg]:
        return self.drift.legs

    def _case(self, key: str) -> Case | None:
        return self.drift.active_case(key)

    def _state(self, key: str) -> LineState:
        case = self._case(key)
        if case is None:
            return LineState.FREE
        if case.status == station.ClearanceStatus.WAITING:
            return LineState.REQUESTED
        return LineState.OCCUPIED if case.departed else LineState.RESERVED

    def _completed(self, key: str) -> bool:
        return key in self.drift.arrived

    def _active_keys(self) -> list[str]:
        """Legs with a case under way, in the order they were asked for."""
        return [c.leg.departure.id for c in self.drift.cases.values() if c.active]

    def _code(self, place: str) -> str:
        return self.places[place].code

    def _side(self, place: str, section: Section, other: str) -> str:
        """Which side of `place` the section to `other` leaves from, as the box shows it."""
        side = section.side_at_a if place == section.place_a else section.side_at_b
        if side is None:
            side = (
                Side.LEFT if self._order.get(other, 0) < self._order.get(place, 0) else Side.RIGHT
            )
        return side.value

    def _own(self, box: Box, leg: Leg) -> bool:
        return leg.departure.place == box.place

    def _on_side(self, box: Box, leg: Leg) -> bool:
        """A box set to one side handles only the trains on sections to that side
        (Casper, 2026-10-01). Both, the default, is the whole place."""
        if box.side == "both" or box.place is None:
            return True
        own = leg.departure.place == box.place
        other = leg.arrival.place if own else leg.departure.place
        return self._side(box.place, leg.section, other) == box.side

    def _label(self, place: str, leg: Leg) -> tuple[str, str]:
        own = leg.departure.place == place
        other = leg.arrival.place if own else leg.departure.place
        side = self._side(place, leg.section, other)
        state = self._state(leg.departure.id)
        marker = "-"
        if state != LineState.FREE:
            points_left = (side == "left") == own
            if state == LineState.REQUESTED:
                marker = "?"
            elif state == LineState.OCCUPIED:
                marker = "◀" if points_left else "▶"
            else:
                marker = "<" if points_left else ">"
        number = leg.train.number
        code = self._code(other)
        token = f"{code}{marker}{number}" if side == "left" else f"{number}{marker}{code}"
        return token, side

    def _schedule(self, box: Box, leg: Leg) -> dict[str, Any]:
        outgoing = self._own(box, leg)
        call = leg.departure if outgoing else leg.arrival
        value = (call.departure if outgoing else call.arrival) or ""
        minute = parse_time(value) // 60 if value else 10**9
        return {
            "kind": "departure" if outgoing else "arrival",
            "label": "AVG" if outgoing else "ANK",
            "time": value or "--:--",
            "order": call.day_offset * 1440 + minute,
            "other": leg.arrival.place if outgoing else leg.departure.place,
        }

    def _candidates(self, box: Box, *, filtered: bool = False) -> list[str]:
        result = []
        for key, leg in self.legs.items():
            if self._completed(key):
                continue
            own = self._own(box, leg)
            incoming = leg.arrival.place == box.place
            if own and self._state(key) == LineState.OCCUPIED:
                continue  # A departed train is no longer a departure to come at its sender.
            if (own or incoming) and self._on_side(box, leg):
                kind = self._schedule(box, leg)["kind"]
                if filtered and box.browse_filter not in {"all", kind}:
                    continue
                result.append(key)
        return sorted(
            result,
            key=lambda key: (
                self._schedule(box, self.legs[key])["order"],
                self.legs[key].train.number,
                key,
            ),
        )

    def _lookup(self, box: Box, number: str) -> list[str]:
        """The legs a typed number means here, one wherever it can be told (old _lookup)."""
        matches = [k for k in self._candidates(box) if self.legs[k].train.number == number]
        if len(matches) > 1:
            active = [k for k in matches if self._state(k) != LineState.FREE]
            if len(active) == 1:
                return active
            if active:
                arriving = {
                    self.legs[k].arrival.id
                    for k in active
                    if self.legs[k].arrival.place == box.place
                }
                return [k for k in active if self.legs[k].departure.id not in arriving]
            # Nothing under way. A through train the system has not seen come is moved here
            # first (FLYTTA 93 HIT?), and the next 93# asks for the departure (Benny #170).
            own = [k for k in matches if self._own(box, self.legs[k])]
            if len(own) == 1:
                previous = self.legs[own[0]].previous
                coming = [k for k in matches if k == previous]
                if coming:
                    return coming
            matches = own or matches
        return matches

    def _requests(self, box: Box) -> list[str]:
        return [
            key
            for key in self._active_keys()
            if self.legs[key].arrival.place == box.place
            and self._on_side(box, self.legs[key])
            and self._state(key) == LineState.REQUESTED
        ]

    def _active_trains(self, box: Box) -> list[str]:
        """Ongoing traffic here; unanswered requests to this place live under A."""
        choices = []
        for key in self._active_keys():
            leg = self.legs[key]
            own = self._own(box, leg)
            if not own and leg.arrival.place != box.place:
                continue
            if not self._on_side(box, leg):
                continue
            state = self._state(key)
            if state == LineState.FREE or (not own and state == LineState.REQUESTED):
                continue
            priority = (
                0
                if own and state == LineState.RESERVED
                else 1
                if not own and state == LineState.OCCUPIED
                else 2
                if state == LineState.REQUESTED
                else 3
                if state == LineState.RESERVED
                else 4
            )
            choices.append((priority, self._schedule(box, leg)["order"], key))
        for key in self._to_put_away(box):
            choices.append((5, self._schedule(box, self.legs[key])["order"], key))
        return [key for _, _, key in sorted(choices)]

    def _to_put_away(self, box: Box) -> list[str]:
        """Trains that ended their run here and still stand on a track (Casper, 2026-10-10)."""
        return [
            key
            for key, leg in self.legs.items()
            if leg.arrival.place == box.place
            and self.drift.ended_here(key)
            and self._on_side(box, leg)
        ]

    def _can_take_in(self, key: str) -> bool:
        """An arrival can be reported unless it waits for an answer (old Server 2.1.0)."""
        return self._state(key) in {LineState.FREE, LineState.RESERVED, LineState.OCCUPIED}

    def _movable(self, box: Box, leg: Leg) -> bool:
        """A train for this place the system does not see coming: never sent, or cleared but
        never reported departed. The box asks whether to move it here (issue #115)."""
        if leg.arrival.place != box.place or self._completed(leg.departure.id):
            return False
        return self._state(leg.departure.id) in {LineState.FREE, LineState.RESERVED}

    def _track_choices(self, box: Box) -> list[str]:
        leg = self.legs.get(box.selected or "")
        if leg is None or leg.arrival.place != box.place:
            return []
        return self.drift.track_choices(leg)

    def _mode(self, leg: Leg) -> ClearanceMode:
        return leg.section.clearance_mode or self.drift.package.meet.clearance_mode

    # --- What each box was told ---------------------------------------------------------

    def _signal(self, box: Box, kind: str) -> None:
        current = box.attention_kind
        if (
            current in ATTENTION_KINDS
            and box.attention_at is not None
            and self.t - box.attention_at < ATTENTION_WINDOW_SECONDS
            and ATTENTION_KINDS.index(kind) > ATTENTION_KINDS.index(current)
        ):
            return
        box.attention_seq += 1
        box.attention_kind, box.attention_at = kind, self.t

    def _open_requests(self, box: Box, direction: int = 0) -> None:
        choices = self._requests(box)
        current = choices.index(box.selected) if box.selected in choices else None
        index = (current + direction) % len(choices) if current is not None else 0
        box.selected = choices[index] if choices else None
        box.screen, box.notice = "requests", ""

    def catch_up(self) -> None:
        """Tell every box what happened since it last looked (old _notify_*)."""
        for event in self.drift.history:
            for box in self.boxes.values():
                if box.place is None or event.seq <= box.seen:
                    continue
                self._told(box, event)
        last = len(self.drift.history)
        for box in self.boxes.values():
            box.seen = max(box.seen, last)

    def _told(self, box: Box, event: events.DriftEvent) -> None:
        clearance = event.data.get("clearance_id")
        case = self.drift.cases.get(str(clearance)) if clearance is not None else None
        if case is None:
            return
        leg = case.leg
        key = leg.departure.id
        number = leg.train.number
        sender = leg.departure.place == box.place
        receiver = leg.arrival.place == box.place
        if not (sender or receiver) or not self._on_side(box, leg):
            return  # The box for the other side is not told (Casper, 2026-10-01).
        match event.kind:
            case events.EventKind.CLEARANCE_REQUESTED if receiver:
                if self._state(key) != LineState.REQUESTED:
                    return
                self._signal(box, "incoming_request")
                if box.notice in ("", "INGA FRÅGOR") and (
                    box.screen == "overview" or (box.screen == "requests" and box.selected is None)
                ):
                    self._open_requests(box)
                    box.revision += 1
            case events.EventKind.CLEARANCE_ANSWERED if sender:
                if event.actor.kind == events.ActorKind.SYSTEM:
                    return  # Direct clearance: nobody answered.
                approved = bool(event.data.get("approved"))
                self._signal(box, "request_approved" if approved else "request_denied")
                if not approved and box.selected == key:
                    box.notice, box.notice_hint = f"{number} NEKAT", self._code(leg.arrival.place)
                    box.notice_until = self.t + NOTICE_SECONDS
                    box.revision += 1
            case events.EventKind.CLEARANCE_CANCELLED if receiver:
                if box.selected not in (None, key) and box.screen != "overview":
                    return  # A box busy with another train is left alone.
                box.notice = f"{number} ÅTERTAGET"
                box.notice_hint = self._code(leg.departure.place)
                box.notice_until = self.t + NOTICE_SECONDS
                box.revision += 1
            case events.EventKind.TRAIN_DEPARTED if receiver:
                self._signal(box, "incoming_train")
            case events.EventKind.TRAIN_ARRIVED if sender:
                if box.selected == key:
                    box.selected, box.screen, box.notice = None, "overview", ""
                box.receipts.append([number, leg.arrival.place])
                box.revision += 1
            case _:
                return

    def _dismiss_receipt(self, box: Box) -> None:
        if box.receipt_until is not None:
            box.receipts.pop(0)
            box.receipt_until = None
            box.revision += 1

    def _advance(self, box: Box) -> None:
        """Notices clear themselves; receipts follow one at a time (old _advance_receipts)."""
        if (
            box.screen == "requests"
            and box.selected is None
            and not box.notice
            and not self._requests(box)
        ):
            box.notice, box.notice_hint = "INGA FRÅGOR", ""
            box.revision += 1
        if not box.notice and box.notice_until is not None:
            box.notice_until, box.notice_hint = None, ""
        if box.notice and box.notice_until is None:
            box.notice_until = self.t + NOTICE_SECONDS
        if box.notice_until is not None and self.t >= box.notice_until:
            box.notice, box.notice_until, box.notice_hint = "", None, ""
            box.selected, box.screen = None, "overview"
            box.revision += 1
        if box.receipt_until is not None and self.t >= box.receipt_until:
            self._dismiss_receipt(box)
        if (
            box.receipts
            and box.receipt_until is None
            and box.screen == "overview"
            and not box.notice
        ):
            box.receipt_until = self.t + RECEIPT_SECONDS
            box.revision += 1

    # --- The keys ------------------------------------------------------------------------

    def _buttons(self, box: Box) -> Buttons:
        buttons = self._view_buttons(box)
        buttons["A"] = ("requests", f"Förfrågningskö ({len(self._requests(box))} väntar)")
        return buttons

    def _view_buttons(self, box: Box) -> Buttons:
        if box.receipt_until is not None:
            return {"#": ("home", "Stäng meddelande"), "*": ("home", "Tillbaka")}
        if box.notice:
            return {"#": ("back", "OK"), "*": ("back", "Tillbaka")}
        if box.screen == "overview":
            active = self._active_trains(box)
            primary = (
                ("requests", "Visa väntande förfrågningar")
                if self._requests(box)
                else ("browse", "Visa kommande tåg")
            )
            return {
                "#": primary,
                "C": ("previous_active", "Föregående aktiva tåg")
                if active
                else ("previous", "Föregående tåg"),
                "D": ("next_active", "Nästa aktiva tåg") if active else ("next", "Nästa tåg"),
                "B": ("active", "Visa aktiva tåg"),
            }
        buttons: Buttons = {"*": ("back", "Tillbaka")}
        if box.screen == "requests":
            buttons["B"] = ("home", "Översikt utan trafikändring")
            if self._requests(box):
                buttons["C"] = ("previous_request", "Föregående förfrågan")
                buttons["D"] = ("next_request", "Nästa förfrågan")
            if box.selected in self._requests(box):
                buttons["#"] = ("accept", "Ge klart")
                buttons["*"] = ("reject_view", "Neka begäran…")
            return buttons
        if box.screen == "browse":
            next_filter = {"all": "ankomster", "arrival": "avgångar", "departure": "alla tåg"}[
                box.browse_filter
            ]
            buttons["B"] = ("filter", "Visa " + next_filter)
            buttons["C"] = ("previous", "Föregående tåg")
            buttons["D"] = ("next", "Nästa tåg")
            if box.selected in self._candidates(box, filtered=True):
                buttons["#"] = ("select", "Välj tåg")
            return buttons
        active_view = box.screen == "active"
        if active_view:
            buttons["B"] = ("home", "Översikt utan trafikändring")
            buttons["C"] = ("previous_active", "Föregående aktiva tåg")
            buttons["D"] = ("next_active", "Nästa aktiva tåg")
            if box.selected not in self._active_trains(box):
                return buttons  # Never silently select or confirm another train.
        if box.selected in self._to_put_away(box):
            buttons["#"] = ("stable", "Ställ undan")  # # puts it away and frees the track.
            return buttons
        leg = self.legs.get(box.selected or "")
        if leg is None or self._completed(leg.departure.id):
            return buttons
        key = leg.departure.id
        state = self._state(key)
        own = self._own(box, leg)
        if box.screen == "cancel":
            buttons["*"] = ("back", "Behåll begäran eller klartecken")
            if own and state in {LineState.REQUESTED, LineState.RESERVED}:
                buttons["#"] = ("cancel", "Bekräfta återtagning")
            return buttons
        if box.screen == "reject":
            buttons["*"] = ("back", "Tillbaka utan att neka")
            if not own and state == LineState.REQUESTED:
                buttons["#"] = ("reject", "Bekräfta neka")
            return buttons
        if box.screen == "move" and self._movable(box, leg):
            # Reached only by typing or picking the train, so the # after a #Ja on a request
            # can never move a train by mistake.
            buttons["#"] = ("arrive", "Flytta hit")
            buttons["B"] = ("tracks", "Annat ankomstspår")
            return buttons
        if box.screen == "tracks":
            if not own and self._can_take_in(key) and self._track_choices(box):
                buttons["#"] = ("arrive_track", "Ankommit på valt spår")
                buttons["C"] = ("previous_track", "Föregående spår")
                buttons["D"] = ("next_track", "Nästa spår")
            return buttons
        if not active_view:
            buttons["C"] = ("previous", "Föregående tåg")
            buttons["D"] = ("next", "Nästa tåg")
        if own and state == LineState.FREE:
            if self.drift.request_block(leg) is None:
                direct = self._mode(leg) == ClearanceMode.DIRECT
                buttons["#"] = ("request", "Reservera" if direct else "Begär klartecken")
        elif state == LineState.REQUESTED:
            buttons["B"] = ("home", "Översikt utan trafikändring")
            if own:
                buttons["*"] = ("cancel_view", "Återta begäran…")
            else:
                buttons["#"] = ("accept", "Ge klart")
                buttons["*"] = ("reject_view", "Neka begäran…")
        elif state == LineState.RESERVED and own:
            buttons["#"] = ("depart", "Rapportera avgång")
            buttons["*"] = ("cancel_view", "Återta klartecken…")
            buttons["B"] = ("home", "Översikt utan trafikändring")
        elif state == LineState.OCCUPIED and not own:
            buttons["#"] = ("arrive", "Rapportera ankomst")
            buttons["B"] = ("tracks", "Annat ankomstspår")
        elif not own and state == LineState.FREE:
            # Never sent in the system: 93# shows it, # places it (old Server 2.1.0).
            buttons["#"] = ("arrive", "Placera på spår")
            buttons["B"] = ("tracks", "Annat ankomstspår")
        elif not own and state == LineState.RESERVED:
            # Cleared here but never reported departed: placed through the track picker only,
            # so the # after #Ja never takes a train in.
            buttons["B"] = ("tracks", "Placera på spår…")
        return buttons

    # --- The picture -----------------------------------------------------------------------

    def _overview(self, box: Box) -> str:
        assert box.place is not None
        width = box.cols
        left: list[str] = []
        right: list[str] = []
        for key in self._active_keys():
            leg = self.legs[key]
            if box.place in {leg.departure.place, leg.arrival.place} and self._on_side(box, leg):
                token, side = self._label(box.place, leg)
                (left if side == "left" else right).append(token)
        a = left[0] if left else ""
        b = right[0] if right else ""
        if a and b and len(a) + len(b) >= width:
            # Whole identities: B opens the counted list of active trains.
            return lcd.row(a, "", width)
        return lcd.row(a, b, width)

    def _idle_titles(self, box: Box) -> list[str]:
        """An idle box names its place (trainmeet-tmbox #43); the code if the name is too long
        or has a character the box cannot draw; and nothing, as before."""
        assert box.place is not None
        place = self.places[box.place]
        width = box.cols
        name = lcd.cells(place.name)
        titles = [lcd.centered(name, width)] if len(name) <= width else []
        return [*titles, lcd.centered(place.code, width), " " * width]

    def _token(self, box: Box) -> str:
        text = f"{self.epoch}:{box.client_id}:{box.place}:{box.revision}:{len(self.drift.history)}"
        return sha256(text.encode()).hexdigest()[:24]

    def _clock(self) -> str:
        return model_time(self.drift.clock.at(self.now))

    # --- Rows two and three of a 20×4 (trainmeet-tmbox #39) ------------------------------

    def _place_named(self, code: str) -> Place | None:
        """The place a notice names by its code, if it is a place (UNDANSTÄLLT carries a
        train number)."""
        return next((place for place in self.places.values() if place.code == code), None)

    @staticmethod
    def _name_row(place: Place, width: int) -> str:
        """A place's name on a row of its own, cut only if it is too long."""
        return lcd.cells(place.name)[:width].ljust(width)

    @staticmethod
    def _spread(left: str, right: str, width: int) -> str:
        """`left` and `right` on one row; `left` gives way (is cut) before `right`."""
        left, right = lcd.cells(left), lcd.cells(right)
        left = left[: max(0, width - len(right) - (1 if right else 0))]
        return lcd.row(left, right, width)

    def _state_word(self, box: Box, leg: Leg) -> str:
        """Where the train stands, in words, for the third row of a 20×4."""
        own = self._own(box, leg)
        key = leg.departure.id
        if self._completed(key):
            return ""  # Over: it has arrived, nothing waits for anyone.
        state = self._state(key)
        if state == LineState.REQUESTED:
            return "Väntar svar" if own else "Vill skicka"
        if state == LineState.RESERVED:
            return "Klar att avgå" if own else "Klarerad"
        if state == LineState.OCCUPIED:
            return "Avgått" if own else "På väg hit"
        return "Ej begärd" if own else "Ej skickad"

    def _leg_rows(self, box: Box, leg: Leg, t: Translate) -> list[str] | None:
        """Who the train goes to or comes from and when, then where it stands and the track
        the timetable has it on here. Never changes what rows one and four say."""
        if box.rows != 4:
            return None
        width = box.cols
        schedule = self._schedule(box, leg)
        outgoing = schedule["kind"] == "departure"
        name = lcd.cells(self.places[schedule["other"]].name)
        # Without room for Till/Från the row keeps the name; only a name longer than the row
        # is cut.
        with_word = t("Till" if outgoing else "Från") + " " + name
        room = width - len(schedule["time"]) - 1
        second = lcd.row(
            with_word if len(with_word) <= room else name[:room], schedule["time"], width
        )
        track = (leg.departure if outgoing else leg.arrival).track
        right = ""
        if track is not None:
            word = t("Sp {track}", track=track)
            right = word if len(word) + 2 <= width else track
        word = self._state_word(box, leg)
        return [second, self._spread(t(word) if word else "", right, width)]

    def _upcoming_rows(self, box: Box, t: Translate) -> list[str] | None:
        """The two nearest trains still to come: number, AVG or ANK, the other place's code
        and the time."""
        if box.rows != 4:
            return None
        width = box.cols
        rows: list[str] = []
        for key in self._candidates(box):
            if self._state(key) != LineState.FREE:
                continue  # Already on the first row.
            leg = self.legs[key]
            schedule = self._schedule(box, leg)
            code = self._code(schedule["other"])
            line = f"{leg.train.number} {t(schedule['label'])} {code}"
            rows.append(self._spread(line, schedule["time"], width))
            if len(rows) == 2:
                break
        return rows + [" " * width] * (2 - len(rows))

    # --- The picture ---------------------------------------------------------------------

    def frame(self, box: Box) -> dict[str, Any]:
        """The picture for one box, as the Frame contract (contracts.terminal.Frame) says.
        Rows one and four of a 20×4 say what a 16×2 says; two and three are extra."""
        clock = self._clock()
        if box.place is None:
            return self._waiting_frame(box, clock)
        self._advance(box)
        buttons = self._buttons(box)
        language = box.language

        def t(key: str, **values: object) -> str:
            return terminal_text.text(language, key, **values)

        width, height = box.cols, box.rows

        def row_(left: str = "", right: str = "") -> str:
            return lcd.row(left, right, width)

        room = width - 5  # What a hint may take beside the clock.
        middle: list[str] | None = None
        hint = "Nr# A:Kö"
        first = self._overview(box)
        if box.screen == "overview":
            middle = self._upcoming_rows(box, t)
        selected = self.legs.get(box.selected or "")
        requests = self._requests(box)
        active = self._active_trains(box)
        active_position = active.index(box.selected) + 1 if box.selected in active else 0
        position = requests.index(box.selected) + 1 if box.selected in requests else 0

        def compact(count: int) -> str:
            return str(count) if count < 100 else "99+"

        if box.screen == "overview" and active:
            hint = t("B:Akt{count} C/D", count=compact(len(active)))
            if len(lcd.cells(hint)) > room:
                hint = t("B:Akt{count}", count=compact(len(active)))
        if box.screen == "overview" and requests:
            hint = t("A:K{count} B:Akt", count=compact(len(requests))) if active else "A:Kö #Visa"
            if len(lcd.cells(hint)) > room:
                hint = t("A{count} B:Akt", count=compact(len(requests)))
        if box.notice:
            first = row_(terminal_text.notice(language, box.notice))
            hint = box.notice_hint
            named = self._place_named(box.notice_hint)
            middle = [self._name_row(named, width)] if named is not None else None
        elif box.screen == "requests":
            if position and selected is not None:
                middle = self._leg_rows(box, selected, t)
                label, side = self._label(box.place, selected)
                counter = f"{position}/{len(requests)}"
                if len(label) + len(counter) < width:
                    first = row_(label, counter) if side == "left" else row_(counter, label)
                    hint = "#Ja *Nej"
                else:
                    # Whole identities; the count goes in the hint.
                    first = row_(label) if side == "left" else row_("", label)
                    hint = t("#Ja {count}", count=counter)
            else:
                first = row_(t("INGA FRÅGOR" if not requests else "FRÅGAN ÄNDRAD"))
                hint = "A:Kö *=Bak"
        elif box.screen == "browse":
            choices = self._candidates(box, filtered=True)
            if selected is not None and box.selected in choices:
                schedule = self._schedule(box, selected)
                middle = self._leg_rows(box, selected, t)
                first = row_(f"{selected.train.number} {t(schedule['label'])}", schedule["time"])
                hint = "#Välj A:Kö"
            else:
                empty = {"all": "INGA TÅG", "arrival": "INGA ANKOMSTER"}.get(
                    box.browse_filter, "INGA AVGÅNGAR"
                )
                first = row_(t("VÄLJ NÄSTA TÅG" if choices else empty))
                hint = "C/D A:Kö" if choices else "B:Fil A:Kö"
        elif box.screen in {"cancel", "reject"} and selected is not None:
            question = "ÅTER {number}?" if box.screen == "cancel" else "NEKA {number}?"
            if "#" in buttons:
                first, hint = row_(t(question, number=selected.train.number)), "#Ja *Nej"
                middle = self._leg_rows(box, selected, t)
            else:
                first, hint = row_(t("LÄGET ÄNDRAT")), "*=Bak"
        elif box.screen == "move" and selected is not None and self._movable(box, selected):
            question = t("FLYTTA {number} HIT?", number=selected.train.number)
            if len(lcd.cells(question)) > width:
                question = t("FLYTTA {number}?", number=selected.train.number)
            first, hint = row_(question), "#Ja B:Sp"
            middle = self._leg_rows(box, selected, t)
        elif box.screen == "tracks" and selected is not None and self._track_choices(box):
            tracks = self._track_choices(box)
            label = tracks[box.track % len(tracks)]
            first = row_(t("{number} SPÅR {track}", number=selected.train.number, track=label))
            hint = "#In C/D:Sp"
            middle = self._leg_rows(box, selected, t)
        elif box.screen == "active" and not active_position:
            first = row_(t("LÄGET ÄNDRAT" if active else "INGA AKTIVA TÅG"))
            hint = "C/D B:Öv"
        elif (
            box.screen in {"detail", "active"}
            and selected is not None
            and buttons.get("#", ("",))[0] == "stable"
        ):
            first = row_(t("{number} SLUTAR HÄR", number=selected.train.number))
            hint = "#Undan"
            middle = self._leg_rows(box, selected, t)
        elif box.screen in {"detail", "active", "move"} and selected is not None:
            label, side = self._label(box.place, selected)
            first = row_(label) if side == "left" else row_("", label)
            middle = self._leg_rows(box, selected, t)
            action = buttons.get("#", ("", ""))[0]
            hint = {
                "request": "#Beg A:Kö",
                "accept": "#Ja *Nej",
                "depart": "#Avg *Åter",
                "arrive": "#In B:Sp",
            }.get(
                action,
                "*Åter B:Öv"
                if buttons.get("B", ("",))[0] == "home"
                else "C/D A:Kö"
                if "C" in buttons
                else "A:Kö *=Bak",
            )
            if action == "request" and buttons["#"][1] == "Reservera":
                hint = "#Sändklar"
            if box.screen == "active":
                counter = f"{compact(active_position)}/{compact(len(active))}"
                hint = {"depart": "#Avg C/D", "arrive": "#In B:Sp"}.get(action, "C/D B:Öv")
                if len(label) + len(counter) < width:
                    first = row_(label, counter) if side == "left" else row_(counter, label)
                else:
                    # Long identities stay whole; the count moves beside the action.
                    prefix = t({"depart": "#Avg", "arrive": "#In"}.get(action, "C/D"))
                    hint = prefix + " " + counter
                    if len(lcd.cells(hint)) > room:
                        hint = prefix + " " + compact(len(active))

        status = self._status(box, selected, requests, active, active_position, t)
        hint = t(hint)
        titles = [first]
        if box.screen == "overview" and not box.notice and not first.strip():
            titles = self._idle_titles(box)
        if box.receipt_until is not None and box.receipts:
            number, destination = box.receipts[0]
            place = self.places[destination]
            middle = [self._name_row(place, width)]
            first, hint = row_(number + " " + t("MOTTAGET")), place.code
            if len(lcd.cells(hint)) > room:
                first, hint = row_(number, place.code), t("MOTTAGET")
            titles = [first]
            status = t(
                "Tåg {number} mottaget i {station}. Meddelandet försvinner automatiskt.",
                number=number,
                station=place.name,
            )
        blank = " " * width
        lines = [titles[0], row_(hint, clock)]
        for top in titles:
            if height == 4:
                lines = [top, *([*(middle or []), blank, blank][:2]), row_(hint, clock)]
                if not lcd.fits(lines):
                    # Only eight places for own characters: rows two and three give way,
                    # one and four are always shown.
                    lines[1] = lines[2] = blank
            else:
                lines = [top, row_(hint, clock)]
            if lcd.fits([lines[0], lines[-1]]):
                break
        return self._picture(box, lines, buttons, clock, status, requests, active, active_position)

    def _status(
        self,
        box: Box,
        selected: Leg | None,
        requests: list[str],
        active: list[str],
        active_position: int,
        t: Translate,
    ) -> str:
        status = t("Skriv tågnummer direkt, eller bläddra med C/D")
        if selected is not None and box.screen != "overview":
            schedule = self._schedule(box, selected)
            direction = "Avgång till" if schedule["kind"] == "departure" else "Ankomst från"
            status = t(
                "Tåg {number} · {direction} {station} · planerat {time}",
                number=selected.train.number,
                direction=t(direction),
                station=self.places[schedule["other"]].name,
                time=schedule["time"],
            )
            if box.screen == "browse":
                choices = self._candidates(box, filtered=True)
                position = choices.index(box.selected) + 1 if box.selected in choices else 0
                label = {"all": "alla tåg", "arrival": "ankomster", "departure": "avgångar"}[
                    box.browse_filter
                ]
                status = f"{position}/{len(choices)} · {t(label)} · " + status
        if selected is not None and selected.departure.id in self._to_put_away(box):
            status = t(
                "Tåg {number} slutar här. # ställer undan det, så blir spåret fritt.",
                number=selected.train.number,
            )
        if box.screen == "requests":
            status = (
                t(
                    "Förfrågan {position}/{count}",
                    position=requests.index(box.selected) + 1,
                    count=len(requests),
                )
                + " · "
                + status
                if box.selected in requests
                else t("Ingen vald förfrågan. A öppnar kön; B visar översikten.")
            )
        if box.screen == "active":
            status = (
                t("Aktivt tåg {position}/{count}", position=active_position, count=len(active))
                + " · "
                + status
                if active_position
                else t("Ingen vald aktiv rörelse. C/D väljer; B visar översikten.")
            )
        return status

    def _picture(
        self,
        box: Box,
        lines: list[str],
        buttons: Buttons,
        clock: str,
        status: str,
        requests: list[str],
        active: list[str],
        active_position: int,
    ) -> dict[str, Any]:
        assert box.place is not None
        place = self.places[box.place]
        language = box.language

        def t(key: str, **values: object) -> str:
            return terminal_text.text(language, key, **values)

        def label(key: str, action: str, text: str) -> str:
            if key == "A":
                return t("Förfrågningskö ({count} väntar)", count=len(requests))
            if action == "active":
                return t("Aktiva tåg ({count})", count=len(active))
            return t(text)

        def short(key: str, action: str, text: str) -> str:
            if key == "A":
                return t("KÖ") + (f" {len(requests)}" if requests else "")
            if action == "active":
                return t("AKTIVA") + (f" {len(active)}" if active else "")
            word = SHORT_LABELS.get(text)
            return t(word) if word else ""

        return {
            "profile": PROFILE,
            "device_id": box.client_id,
            "station": place.name,
            "station_code": place.code,
            "rows": box.rows,
            "cols": box.cols,
            "lines": lines,
            "lcd": lcd.encode(lines),
            "attention": {
                "epoch": self.epoch,
                "seq": box.attention_seq,
                "kind": box.attention_kind,
            },
            "view_token": self._token(box),
            "revision": len(self.drift.history),
            "view_revision": box.revision,
            "input_guard_ms": 500,
            "language": language,
            "keys": {
                key: {
                    "label": label(key, action, text),
                    "short": short(key, action, text),
                    "acts": action not in NAVIGATION_ACTIONS,
                }
                for key, (action, text) in buttons.items()
            },
            "entry": {
                **self._entry(box, clock),
                "labels": {
                    "#": t("Sök tåg (begär direkt)"),
                    "*": t("Avbryt inmatning"),
                    "B": t("Sudda siffra"),
                    "A": t("Förfrågningskö (avbryt inmatning)"),
                },
                "short": {"#": t("SÖK"), "*": t("AVBRYT"), "B": t("SUDDA"), "A": t("KÖ")},
            },
            "requests": {
                "count": len(requests),
                "position": requests.index(box.selected) + 1 if box.selected in requests else 0,
                "label": "A · " + t("Förfrågningskö ({count} väntar)", count=len(requests)),
            },
            "active": {
                "count": len(active),
                "position": active_position if box.screen == "active" else 0,
            },
            "status": status,
        }

    def _entry(self, box: Box, clock: str) -> dict[str, Any]:
        """The picture while a train number is typed; the digits go at row 0, column 5."""
        language = box.language
        width, blank = box.cols, " " * box.cols
        first = lcd.row(terminal_text.text(language, "TÅG: _____"), "", width)
        last = lcd.row(terminal_text.text(language, "#Sök B:Del"), clock, width)
        lines = [first, blank, blank, last] if box.rows == 4 else [first, last]
        return {
            "context": f"{self.epoch}:{box.client_id}:{box.place or '-'}",
            "max_length": 5,
            "lines": lines,
            "lcd": lcd.encode(lines),
            "row": 0,
            "column": 5,
            "commit": "#",
            "cancel": "*",
            "erase": "B",
            "shortcut": "A",
        }

    def _waiting_frame(self, box: Box, clock: str) -> dict[str, Any]:
        """A box nobody has assigned yet: it says so and waits (Väntar in Klienter)."""
        language = box.language
        width = box.cols
        lines = [
            lcd.centered(terminal_text.text(language, "VÄNTAR PÅ"), width),
            lcd.centered(terminal_text.text(language, "TILLDELNING"), width),
        ]
        lines += [" " * width] * (box.rows - 2)
        entry = self._entry(box, clock)
        return {
            "profile": PROFILE,
            "device_id": box.client_id,
            "station": box.name,
            "station_code": "-",
            "rows": box.rows,
            "cols": width,
            "lines": lines,
            "lcd": lcd.encode(lines),
            "attention": {"epoch": self.epoch, "seq": box.attention_seq, "kind": None},
            "view_token": self._token(box),
            "revision": len(self.drift.history),
            "view_revision": box.revision,
            "input_guard_ms": 500,
            "language": language,
            "keys": {},
            "entry": {key: entry[key] for key in ("context", "max_length", "lines", "lcd")},
            "status": terminal_text.text(
                language,
                "{name} väntar på att trafikledningen tilldelar en driftplats.",
                name=box.name,
            ),
            "waiting": True,
        }

    # --- A key press ---------------------------------------------------------------------

    def press(self, box: Box, body: dict[str, Any]) -> dict[str, Any]:
        """Carry out one key press and answer as the Ack contract: status, message, frame."""
        if box.place is not None:
            self._advance(box)
        command_id = body.get("command_id")
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 80:
            return self._answer(box, command_id, False, "Ogiltigt kommando-ID")
        signature = json.dumps(body, sort_keys=True, ensure_ascii=False)
        for cached_id, cached_signature, accepted, message in box.processed:
            if cached_id == command_id:
                if cached_signature != signature:
                    return self._answer(box, command_id, False, "Kommando-ID har redan använts")
                return self._answer(box, command_id, accepted, message, duplicate=True)
        if box.place is None:
            result = (False, "Boxen väntar på tilldelning")
        elif body.get("view_token") != self._token(box):
            result = (False, "Läget ändrades. Läs displayen och försök igen.")
        else:
            result = self._dispatch(box, body)
        box.processed = [*box.processed, [command_id, signature, *result]][-PROCESSED_LIMIT:]
        if not result[0]:
            key = body.get("key")
            self.refusals.append(
                (box.client_id, box.place, key if isinstance(key, str) else "?", result[1])
            )
        self.catch_up()
        return self._answer(box, command_id, *result)

    def _answer(
        self,
        box: Box,
        command_id: object,
        accepted: bool,
        message: str = "",
        *,
        duplicate: bool = False,
    ) -> dict[str, Any]:
        status = "duplicate" if duplicate else "accepted" if accepted else "rejected"
        return {
            "status": status,
            "message": message,
            "command_id": command_id if isinstance(command_id, str) else "-",
            "frame": self.frame(box),
        }

    def _dispatch(self, box: Box, body: dict[str, Any]) -> tuple[bool, str]:
        key = body.get("key")
        if not isinstance(key, str) or len(key) != 1:
            return False, "Ogiltig tangent"
        if any(name in body for name in ("action", "connection_id", "station_id", "place")):
            return False, "Servern bestämmer funktion och mottagare"
        if key == "#" and "train_number" in body:
            return self._enter(box, body)
        if "train_number" in body:
            return False, "Servern bestämmer funktion och mottagare"
        button = self._buttons(box).get(key)
        if button is None:
            return False, "Tangenten är inte tillgänglig i det här läget"
        self._dismiss_receipt(box)
        action = button[0]
        box.notice, box.notice_hint, box.notice_until = "", "", None
        if action == "back":
            box.screen = (
                box.return_screen if box.screen in {"cancel", "reject", "tracks"} else "overview"
            )
        elif action == "home":
            box.screen = "overview"
        elif action in {"requests", "next_request", "previous_request"}:
            step = {"requests": 0, "next_request": 1, "previous_request": -1}[action]
            self._open_requests(box, step)
        elif action in {"active", "next_active", "previous_active"}:
            self._open_active(box, {"active": 0, "next_active": 1, "previous_active": -1}[action])
        elif action in {"browse", "next", "previous"}:
            self._browse(box, {"browse": 0, "next": 1, "previous": -1}[action])
        elif action == "filter":
            box.browse_filter = {"all": "arrival", "arrival": "departure", "departure": "all"}[
                box.browse_filter
            ]
            box.selected = None
            self._browse(box)
        elif action == "select":
            leg = self.legs[box.selected or ""]
            box.screen = "move" if self._movable(box, leg) else "detail"
        elif action == "tracks":
            box.return_screen = box.screen
            box.track, box.screen = 0, "tracks"
        elif action in {"next_track", "previous_track"}:
            step = 1 if action == "next_track" else -1
            box.track = (box.track + step) % max(1, len(self._track_choices(box)))
        elif action in {"cancel_view", "reject_view"}:
            box.return_screen = box.screen
            box.screen = "cancel" if action == "cancel_view" else "reject"
        else:
            message = self._traffic(box, action)
            if message:
                return False, message
        box.revision += 1
        return True, ""

    def _enter(self, box: Box, body: dict[str, Any]) -> tuple[bool, str]:
        number = body["train_number"]
        context = f"{self.epoch}:{box.client_id}:{box.place}"
        if body.get("entry_context") != context or not (
            isinstance(number, str) and number.isascii() and number.isdigit() and len(number) <= 5
        ):
            return False, "Ogiltig eller gammal inmatning"
        self._dismiss_receipt(box)
        matches = self._lookup(box, number)
        if len(matches) != 1:
            here = [
                leg
                for key, leg in self.legs.items()
                if leg.train.number == number
                and not self._completed(key)
                and box.place in {leg.departure.place, leg.arrival.place}
            ]
            # The train is here, but on the sections the place's other box handles.
            other_side = bool(here) and not any(self._on_side(box, leg) for leg in here)
            box.notice = (
                ("ANNAN SIDA" if other_side else "INGET TÅG") if not matches else "FLERA TÅG ADMIN"
            )
            box.notice_hint, box.notice_until = "", None
        else:
            box.selected, box.screen, box.notice = matches[0], "detail", ""
            box.browse_filter = "all"
            if self._movable(box, self.legs[matches[0]]):
                box.screen = "move"
            # 101# is enough: a departure that can be asked for is asked for at once,
            # and * takes it back until the receiver has answered (Casper, 2026-10-02).
            if self._buttons(box).get("#", ("",))[0] == "request":
                message = self._traffic(box, "request")
                if message:
                    box.revision += 1
                    return False, message
        box.revision += 1
        return True, ""

    def _browse(self, box: Box, direction: int = 0) -> None:
        choices = self._candidates(box, filtered=True)
        current = choices.index(box.selected) if box.selected in choices else None
        if choices:
            if current is not None:
                index = (current + direction) % len(choices)
            else:
                index = len(choices) - 1 if direction < 0 else 0
            box.selected = choices[index]
        else:
            box.selected = None
        box.screen = "browse"

    def _open_active(self, box: Box, direction: int = 0) -> None:
        choices = self._active_trains(box)
        current = (
            choices.index(box.selected)
            if box.screen == "active" and box.selected in choices
            else None
        )
        if choices:
            if current is not None:
                index = (current + direction) % len(choices)
            else:
                index = len(choices) - 1 if direction < 0 else 0
            box.selected = choices[index]
        else:
            box.selected = None
        box.screen, box.notice = "active", ""

    def _command(
        self, box: Box, action: station.Action, payload: dict[str, object], case: Case | None
    ) -> Reason | None:
        assert box.place is not None
        revision = (
            station.Revision(scope=station.RevisionScope.CASE, key=case.id, value=case.revision)
            if case is not None
            else None
        )
        command = station.Command(
            message_id=f"{box.client_id}-{uuid4().hex}",
            client_id=box.client_id,
            place=box.place,
            context=self.drift.context,
            action=action,
            payload=payload,
            expected_revision=revision,
        )
        try:
            self.drift.command(command, self.now)
        except Refused as error:
            return error.reason
        return None

    def _traffic(self, box: Box, action: str) -> str:
        leg = self.legs.get(box.selected or "")
        if leg is None:
            return "Läget har ändrats. Välj tåget igen."
        key = leg.departure.id
        case = self._case(key)
        number = leg.train.number
        reason: Reason | None
        match action:
            case "request":
                reason = self._command(
                    box,
                    station.Action.CLEARANCE_REQUEST,
                    {"call": key, "section": leg.section.id, "clearance_id": f"clr-{uuid4().hex}"},
                    None,
                )
            case "accept" | "reject" if case is not None:
                reason = self._command(
                    box,
                    station.Action.CLEARANCE_RESPONSE,
                    {"clearance_id": case.id, "approved": action == "accept"},
                    case,
                )
            case "cancel" if case is not None:
                reason = self._command(
                    box, station.Action.CLEARANCE_CANCEL, {"clearance_id": case.id}, case
                )
            case "depart":
                reason = self._command(box, station.Action.TRAIN_DEPARTED, {"call": key}, None)
            case "arrive" | "arrive_track":
                choices = self._track_choices(box)
                track = (
                    choices[box.track % len(choices)]
                    if action == "arrive_track" and choices
                    else self.drift.planned_track(leg)
                )
                occupied = (
                    track is not None
                    and self.drift.occupant(leg.arrival.place, track, key) is not None
                )
                payload: dict[str, object] = {"call": leg.arrival.id}
                if track is not None:
                    payload["track"] = track
                reason = self._command(box, station.Action.TRAIN_ARRIVED, payload, None)
            case "stable":
                reason = self._command(
                    box, station.Action.TRAIN_SET_ASIDE, {"call": leg.arrival.id}, None
                )
            case _:
                return "Läget har ändrats. Välj tåget igen."
        if reason is not None:
            return REFUSED_TEXT.get(reason, TEXT_SV[reason].rstrip("."))
        if action == "stable":
            # Put away: the track is free, and the box says so with the train's number.
            box.notice, box.notice_hint = "UNDANSTÄLLT", number
            box.notice_until = self.t + NOTICE_SECONDS
            box.screen, box.selected = "overview", None
            return ""
        if action == "accept" and box.screen == "requests":
            box.screen = "detail"  # Stay with the accepted train; # never moves to the next.
        if action in {"arrive", "arrive_track"}:
            track = self.drift.tracks.get(key) or "?"
            # Another train on the track does not stop the arrival; the box says so (4.12.2).
            box.notice = f"{number} UPPT SPÅR" if occupied else f"{number} ANK SP{track}"
            box.notice_hint = self._code(leg.departure.place)
            box.notice_until = self.t + NOTICE_SECONDS
        if action == "cancel":
            box.notice = f"{number} ÅTERTAGET"
            box.notice_hint = self._code(leg.arrival.place)
            box.notice_until = self.t + NOTICE_SECONDS
        if action == "reject":
            box.notice = f"{number} NEKAT"
            box.notice_hint = self._code(leg.departure.place)
            box.notice_until = self.t + NOTICE_SECONDS
        return ""

    def assign(self, box: Box, place: str, side: str = "both", language: str | None = None) -> None:
        """The dispatcher gives the box a place and a side: it starts on the start screen, told
        nothing old, with the requests waiting there open (old runtime). A key pressed for the
        old place or side does nothing, since the picture it was pressed on is gone."""
        if place not in self.places:
            raise Refused(Reason.WRONG_PLACE)
        if side not in {"both", "left", "right"}:
            raise ValueError("Sidan är both, left eller right.")
        if language is not None:
            if language not in terminal_text.LANGUAGES:
                raise ValueError("Språket finns inte på boxen.")
            box.language = language
        box.place, box.side = place, side
        box.screen, box.selected, box.return_screen = "overview", None, "detail"
        box.notice, box.notice_hint, box.notice_until = "", "", None
        box.receipts, box.receipt_until = [], None
        box.seen = len(self.drift.history)
        box.revision += 1
        if self._requests(box):
            self._open_requests(box)
