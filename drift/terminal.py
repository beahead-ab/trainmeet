"""The TMBox 16×2 view: Drift draws the screen and the box sends key presses.

Ported from the old Server's terminal16 (Terminal16Lab, Server 4.24) with its tests as the
key: the start screen with the station's name, 101# that asks at once, the request queue
under A, #Ja *Nej, the arrows ? < > ◀ ▶, the notices (NEKAT, ÅTERTAGET, ANK SP1, INGA FRÅGOR)
that go away by themselves, and the receipt MOTTAGET at the sender. The TMBox logic is
not redesigned (decided 1 November).

Not yet ported, each with its own step: another arrival track (B:Sp), FLYTTA HIT for a train
nobody sent, putting a train away, the automation, the box's side, 20×4 and other languages.

The boxes of a run share one Drift: what one box does, the others see. What a box was told
is worked out from Drift's events, so a box that was away catches up on its next picture.
"""

from __future__ import annotations

import json
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
from drift import lcd
from drift.engine import Case, Drift, Leg, Refused, model_time, parse_time

PROFILE: Final = "server-16x2-pilot"
WIDTH: Final = 16
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
    screen: str = "overview"
    selected: str | None = None
    return_screen: str = "detail"
    browse_filter: str = "all"
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


class Boxes:
    """The boxes of one run over one Drift. `now` is the wall clock, not the model clock."""

    def __init__(self, drift: Drift, boxes: dict[str, Box], *, epoch: str, now: datetime) -> None:
        self.drift = drift
        self.boxes = boxes
        self.epoch = epoch
        self.now = now
        self.t = now.timestamp()
        package = drift.package
        self.places: dict[str, Place] = {p.id: p for p in package.places}
        order = package.display.graph_order or [p.id for p in package.places]
        self._order = {place: index for index, place in enumerate(order)}

    # --- Drift's state seen from a box --------------------------------------------------

    @property
    def legs(self) -> dict[str, Leg]:
        return self.drift.legs

    def _case(self, key: str) -> Case | None:
        return next(
            (c for c in self.drift.cases.values() if c.active and c.leg.departure.id == key),
            None,
        )

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
            if own or incoming:
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
            own = [k for k in matches if self._own(box, self.legs[k])]
            matches = own or matches
        return matches

    def _requests(self, box: Box) -> list[str]:
        return [
            key
            for key in self._active_keys()
            if self.legs[key].arrival.place == box.place and self._state(key) == LineState.REQUESTED
        ]

    def _active_trains(self, box: Box) -> list[str]:
        """Ongoing traffic here; unanswered requests to this place live under A."""
        choices = []
        for key in self._active_keys():
            leg = self.legs[key]
            own = self._own(box, leg)
            if not own and leg.arrival.place != box.place:
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
        return [key for _, _, key in sorted(choices)]

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
        return buttons

    # --- The picture -----------------------------------------------------------------------

    def _overview(self, box: Box) -> str:
        assert box.place is not None
        left: list[str] = []
        right: list[str] = []
        for key in self._active_keys():
            leg = self.legs[key]
            if box.place in {leg.departure.place, leg.arrival.place}:
                token, side = self._label(box.place, leg)
                (left if side == "left" else right).append(token)
        a = left[0] if left else ""
        b = right[0] if right else ""
        if a and b and len(a) + len(b) >= WIDTH:
            return lcd.row(a, "", WIDTH)
        return lcd.row(a, b, WIDTH)

    def _idle_titles(self, box: Box) -> list[str]:
        assert box.place is not None
        place = self.places[box.place]
        name = lcd.cells(place.name)
        titles = [lcd.centered(name, WIDTH)] if len(name) <= WIDTH else []
        return [*titles, lcd.centered(place.code, WIDTH), " " * WIDTH]

    def _token(self, box: Box) -> str:
        text = f"{self.epoch}:{box.client_id}:{box.place}:{box.revision}:{len(self.drift.history)}"
        return sha256(text.encode()).hexdigest()[:24]

    def _clock(self) -> str:
        return model_time(self.drift.clock.at(self.now))

    def frame(self, box: Box) -> dict[str, Any]:
        """The picture for one box, as the Frame contract (contracts.terminal.Frame) says."""
        clock = self._clock()
        if box.place is None:
            return self._waiting_frame(box, clock)
        self._advance(box)
        buttons = self._buttons(box)
        room = WIDTH - 5
        hint = "Nr# A:Kö"
        first = self._overview(box)
        selected = self.legs.get(box.selected or "")
        requests = self._requests(box)
        active = self._active_trains(box)
        active_position = active.index(box.selected) + 1 if box.selected in active else 0
        position = requests.index(box.selected) + 1 if box.selected in requests else 0

        def compact(count: int) -> str:
            return str(count) if count < 100 else "99+"

        if box.screen == "overview" and active:
            hint = f"B:Akt{compact(len(active))} C/D"
            if len(hint) > room:
                hint = f"B:Akt{compact(len(active))}"
        if box.screen == "overview" and requests:
            hint = f"A:K{compact(len(requests))} B:Akt" if active else "A:Kö #Visa"
        if box.notice:
            first, hint = lcd.row(box.notice, "", WIDTH), box.notice_hint
        elif box.screen == "requests":
            if position and selected is not None:
                label, side = self._label(box.place, selected)
                counter = f"{position}/{len(requests)}"
                if len(label) + len(counter) < WIDTH:
                    first = (
                        lcd.row(label, counter, WIDTH)
                        if side == "left"
                        else lcd.row(counter, label, WIDTH)
                    )
                    hint = "#Ja *Nej"
                else:
                    first = lcd.row(label, "", WIDTH) if side == "left" else lcd.row("", label)
                    hint = f"#Ja {counter}"
            else:
                first = lcd.row("INGA FRÅGOR" if not requests else "FRÅGAN ÄNDRAD", "", WIDTH)
                hint = "A:Kö *=Bak"
        elif box.screen == "browse":
            choices = self._candidates(box, filtered=True)
            if selected is not None and box.selected in choices:
                schedule = self._schedule(box, selected)
                first = lcd.row(
                    f"{selected.train.number} {schedule['label']}", schedule["time"], WIDTH
                )
                hint = "#Välj A:Kö"
            else:
                empty = {"all": "INGA TÅG", "arrival": "INGA ANKOMSTER"}.get(
                    box.browse_filter, "INGA AVGÅNGAR"
                )
                first = lcd.row("VÄLJ NÄSTA TÅG" if choices else empty, "", WIDTH)
                hint = "C/D A:Kö" if choices else "B:Fil A:Kö"
        elif box.screen in {"cancel", "reject"} and selected is not None:
            word = "ÅTER" if box.screen == "cancel" else "NEKA"
            if "#" in buttons:
                first, hint = lcd.row(f"{word} {selected.train.number}?", "", WIDTH), "#Ja *Nej"
            else:
                first, hint = lcd.row("LÄGET ÄNDRAT", "", WIDTH), "*=Bak"
        elif box.screen == "active" and not active_position:
            first = lcd.row("LÄGET ÄNDRAT" if active else "INGA AKTIVA TÅG", "", WIDTH)
            hint = "C/D B:Öv"
        elif box.screen in {"detail", "active"} and selected is not None:
            label, side = self._label(box.place, selected)
            first = lcd.row(label, "", WIDTH) if side == "left" else lcd.row("", label, WIDTH)
            action = buttons.get("#", ("", ""))[0]
            hint = {
                "request": "#Beg A:Kö",
                "accept": "#Ja *Nej",
                "depart": "#Avg *Åter",
                "arrive": "#In A:Kö",
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
                hint = {"depart": "#Avg C/D", "arrive": "#In C/D"}.get(action, "C/D B:Öv")
                if len(label) + len(counter) < WIDTH:
                    first = (
                        lcd.row(label, counter, WIDTH)
                        if side == "left"
                        else lcd.row(counter, label, WIDTH)
                    )

        status = self._status(box, selected, requests, active, active_position)
        titles = [first]
        if box.screen == "overview" and not box.notice and not first.strip():
            titles = self._idle_titles(box)
        if box.receipt_until is not None and box.receipts:
            number, destination = box.receipts[0]
            code = self._code(destination)
            first, hint = lcd.row(f"{number} MOTTAGET", "", WIDTH), code
            if len(hint) > room:
                first, hint = lcd.row(number, code, WIDTH), "MOTTAGET"
            titles = [first]
            name = self.places[destination].name
            status = f"Tåg {number} mottaget i {name}. Meddelandet försvinner automatiskt."
        lines = [titles[0], lcd.row(hint, clock, WIDTH)]
        for top in titles:
            lines = [top, lcd.row(hint, clock, WIDTH)]
            if lcd.fits(lines):
                break
        return self._picture(box, lines, buttons, clock, status, requests, active, active_position)

    def _status(
        self,
        box: Box,
        selected: Leg | None,
        requests: list[str],
        active: list[str],
        active_position: int,
    ) -> str:
        status = "Skriv tågnummer direkt, eller bläddra med C/D"
        if selected is not None and box.screen != "overview":
            schedule = self._schedule(box, selected)
            other = self.places[schedule["other"]].name
            direction = "Avgång till" if schedule["kind"] == "departure" else "Ankomst från"
            status = (
                f"Tåg {selected.train.number} · {direction} {other} · planerat {schedule['time']}"
            )
        if box.screen == "requests":
            status = (
                f"Förfrågan {requests.index(box.selected) + 1}/{len(requests)} · " + status
                if box.selected in requests
                else "Ingen vald förfrågan. A öppnar kön; B visar översikten."
            )
        if box.screen == "active":
            status = (
                f"Aktivt tåg {active_position}/{len(active)} · " + status
                if active_position
                else "Ingen vald aktiv rörelse. C/D väljer; B visar översikten."
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
        entry_lines = [lcd.row("TÅG: _____", "", WIDTH), lcd.row("#Sök B:Del", clock, WIDTH)]

        def label(key: str, action: str, text: str) -> str:
            if key == "A":
                return f"Förfrågningskö ({len(requests)} väntar)"
            if action == "active":
                return f"Aktiva tåg ({len(active)})"
            return text

        def short(key: str, action: str, text: str) -> str:
            if key == "A":
                return "KÖ" + (f" {len(requests)}" if requests else "")
            if action == "active":
                return "AKTIVA" + (f" {len(active)}" if active else "")
            return SHORT_LABELS.get(text, "")

        return {
            "profile": PROFILE,
            "device_id": box.client_id,
            "station": place.name,
            "station_code": place.code,
            "rows": 2,
            "cols": WIDTH,
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
            "language": "sv",
            "keys": {
                key: {
                    "label": label(key, action, text),
                    "short": short(key, action, text),
                    "acts": action not in NAVIGATION_ACTIONS,
                }
                for key, (action, text) in buttons.items()
            },
            "entry": {
                "context": f"{self.epoch}:{box.client_id}:{box.place}",
                "max_length": 5,
                "lines": entry_lines,
                "lcd": lcd.encode(entry_lines),
                "row": 0,
                "column": 5,
                "commit": "#",
                "cancel": "*",
                "erase": "B",
                "shortcut": "A",
                "labels": {
                    "#": "Sök tåg (begär direkt)",
                    "*": "Avbryt inmatning",
                    "B": "Sudda siffra",
                    "A": "Förfrågningskö (avbryt inmatning)",
                },
                "short": {"#": "SÖK", "*": "AVBRYT", "B": "SUDDA", "A": "KÖ"},
            },
            "requests": {
                "count": len(requests),
                "position": requests.index(box.selected) + 1 if box.selected in requests else 0,
                "label": f"A · Förfrågningskö ({len(requests)} väntar)",
            },
            "active": {
                "count": len(active),
                "position": active_position if box.screen == "active" else 0,
            },
            "status": status,
        }

    def _waiting_frame(self, box: Box, clock: str) -> dict[str, Any]:
        """A box nobody has assigned yet: it says so and waits (Väntar in Klienter)."""
        lines = [lcd.centered("VÄNTAR PÅ", WIDTH), lcd.row("TILLDELNING", clock, WIDTH)]
        entry_lines = [lcd.row("TÅG: _____", "", WIDTH), lcd.row("#Sök B:Del", clock, WIDTH)]
        return {
            "profile": PROFILE,
            "device_id": box.client_id,
            "station": box.name,
            "station_code": "-",
            "rows": 2,
            "cols": WIDTH,
            "lines": lines,
            "lcd": lcd.encode(lines),
            "attention": {"epoch": self.epoch, "seq": box.attention_seq, "kind": None},
            "view_token": self._token(box),
            "revision": len(self.drift.history),
            "view_revision": box.revision,
            "input_guard_ms": 500,
            "language": "sv",
            "keys": {},
            "entry": {
                "context": f"{self.epoch}:{box.client_id}:-",
                "max_length": 5,
                "lines": entry_lines,
                "lcd": lcd.encode(entry_lines),
            },
            "status": f"{box.name} väntar på att trafikledningen tilldelar en driftplats.",
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
            box.screen = box.return_screen if box.screen in {"cancel", "reject"} else "overview"
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
            box.screen = "detail"
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
            box.notice = "INGET TÅG" if not matches else "FLERA TÅG ADMIN"
            box.notice_hint, box.notice_until = "", None
        else:
            box.selected, box.screen, box.notice = matches[0], "detail", ""
            box.browse_filter = "all"
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
            case "arrive":
                reason = self._command(
                    box, station.Action.TRAIN_ARRIVED, {"call": leg.arrival.id}, None
                )
            case _:
                return "Läget har ändrats. Välj tåget igen."
        if reason is not None:
            return REFUSED_TEXT.get(reason, TEXT_SV[reason].rstrip("."))
        if action == "accept" and box.screen == "requests":
            box.screen = "detail"  # Stay with the accepted train; # never moves to the next.
        if action == "arrive":
            track = leg.arrival.track or "?"
            box.notice = f"{number} ANK SP{track}"
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

    def assign(self, box: Box, place: str, side: str = "both") -> None:
        """The dispatcher gives the box a place: it starts on the start screen, told nothing old."""
        if place not in self.places:
            raise Refused(Reason.WRONG_PLACE)
        box.place, box.side = place, side
        box.screen, box.selected, box.return_screen = "overview", None, "detail"
        box.notice, box.notice_hint, box.notice_until = "", "", None
        box.receipts, box.receipt_until = [], None
        box.seen = len(self.drift.history)
        box.revision += 1
