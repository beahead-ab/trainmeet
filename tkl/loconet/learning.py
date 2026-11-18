"""Koppla in: learning by touching the layout (STUDIO-04, STUDIO-17, STUDIO-19, STUDIO-24).

- A track circuit: the owner puts a wagon on it. A sensor that changes while Koppla in listens
  asks: "Givaren 73 slog till. Är det Spår 3?". The proposal is the track circuit that already
  has the address, else the one the owner chose to learn, else none, and the owner may name
  another. Yes gives the track circuit the address, confirmed: green. A sensor that lets go when
  the wagon comes is reversed, and the question says so (the polarity, through a question).
- A switch: Lägg om sends a switch request to its address, the switch's number by default, to
  the other position each time. The owner says whether it moved that way, the other way (the
  polarity is reversed) or not at all. The first two confirm the address: green. A report from
  the card after the order is shown, and gives the switch feedback from the card when it had
  none.
- A signal: Skicka kör orders kör. The owner says whether it shows kör; if it shows stopp, kör
  is sent again with the polarity reversed and asked again. Stopp is sent when it is answered.

Only a change counts for a sensor, so the interrogation's first answers and a report that says
the same again ask nothing (cda-tkl's Mät objekt: the report must change). A green track
circuit asks nothing either. Pure Python: it says which frames to send and gives the changed
model to save; the service sends and saves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

from contracts.station_model import Address, FeedbackType, Position, StationModel, SwitchFeedback
from contracts.tkl import AddressState, ObjectKind, TklChoice, TklLearning, TklQuestion
from tkl.loconet.messages import Message, SensorReport, SwitchReport, switch_request
from tkl.loconet.objects import (
    KIND_WORD,
    changed,
    confirmed,
    find,
    objects,
    output_for,
    position_for,
    signal_output,
)

Answer = Literal["yes", "no", "reversed"]
POSITION_WORD: Final = {Position.PLUS: "rakt (+)", Position.MINUS: "avvikande (\N{MINUS SIGN})"}


class LearnError(Exception):
    """What cannot be learnt now, and why, in Swedish."""


@dataclass
class _Asked:
    id: int
    kind: ObjectKind
    object: str | None
    address: int
    text: str
    answers: list[tuple[Answer, str]]
    choices: list[str] = field(default_factory=list)
    active: bool = True
    """A sensor's question: it slog till (True) or släppte (False)."""
    position: Position | None = None
    """A switch's question: the position it was asked to take."""
    flipped: bool = False
    """A signal's question: kör was sent with the polarity reversed."""
    seen: str | None = None
    from_card: bool = False


@dataclass(frozen=True)
class Learnt:
    """What an answer did: the model to save, if it changed; the frames to send; what to say."""

    model: StationModel | None
    frames: list[bytes]
    message: str


@dataclass
class Learning:
    question: _Asked | None = None
    target: tuple[ObjectKind, str] | None = None
    thrown: dict[str, Position] = field(default_factory=dict)
    inputs: dict[int, bool] = field(default_factory=dict)
    message: str | None = None
    _last: int = 0

    # --- what the page shows ------------------------------------------------------------------

    def shown_question(self) -> TklQuestion | None:
        q = self.question
        if q is None:
            return None
        return TklQuestion(
            id=q.id,
            kind=q.kind,
            object=q.object,
            address=q.address,
            text=q.text,
            seen=q.seen,
            answers=[TklChoice(value=value, label=label) for value, label in q.answers],
            choices=q.choices,
        )

    def shown_learning(self) -> TklLearning | None:
        if self.target is None:
            return None
        kind, name = self.target
        return TklLearning(kind=kind, name=name, text=f"Ställ en vagn på {name}.")

    def forget(self) -> None:
        """A new connection: nothing asked, nothing known about the sensors."""
        self.question, self.target, self.message = None, None, None
        self.inputs.clear()

    def _ask(
        self,
        *,
        kind: ObjectKind,
        object: str | None,
        address: int,
        text: str,
        answers: list[tuple[Answer, str]],
        choices: list[str] | None = None,
        active: bool = True,
        position: Position | None = None,
        flipped: bool = False,
    ) -> None:
        self._last += 1
        self.question = _Asked(
            self._last,
            kind,
            object,
            address,
            text,
            answers,
            choices or [],
            active=active,
            position=position,
            flipped=flipped,
        )

    # --- listening ----------------------------------------------------------------------------

    def observe(self, model: StationModel, message: Message) -> bool:
        """A message from the layout while Koppla in listens; True when the page has news."""
        q = self.question
        if isinstance(message, SwitchReport):
            if q is None or q.kind == ObjectKind.TRACK_CIRCUIT or message.address != q.address:
                return False
            o = find(model, q.kind, q.object or "")
            reversed_ = o.reversed if o is not None else False
            if q.flipped:
                reversed_ = not reversed_
            if message.output is None:
                q.seen = "Kortet rapporterade: i rörelse."
            elif q.kind == ObjectKind.SWITCH:
                lies = POSITION_WORD[position_for(message.output, reversed_)]
                q.seen, q.from_card = f"Kortet rapporterade {lies}.", True
            else:
                proceed = message.output == signal_output(True, reversed_)
                q.seen = f"Kortet rapporterade {'kör' if proceed else 'stopp'}."
            return True
        if not isinstance(message, SensorReport):
            return False
        before = self.inputs.get(message.address)
        self.inputs[message.address] = message.active
        if q is not None and q.kind == ObjectKind.SWITCH:
            o = find(model, ObjectKind.SWITCH, q.object or "")
            if o is not None and o.feedback is not None:
                for sensor, lies in (
                    (o.feedback.straight, "rakt"),
                    (o.feedback.diverging, "avvikande"),
                ):
                    if sensor is not None and sensor.number == message.address and message.active:
                        q.seen = f"Givaren för {lies} slog till."
                        return True
        if before is None or before == message.active:
            return False
        if q is not None and q.kind != ObjectKind.TRACK_CIRCUIT:
            return False
        return self._sensor(model, message.address, message.active)

    def _sensor(self, model: StationModel, address: int, active: bool) -> bool:
        circuits = [o for o in objects(model) if o.kind == ObjectKind.TRACK_CIRCUIT]
        holder = next((o for o in circuits if o.address and o.address.number == address), None)
        if holder is not None and holder.state == AddressState.GREEN:
            if active != holder.reversed:
                self.message = f"Givaren {address} slog till: {holder.name}, redan bekräftad."
                return True
            return False
        proposed = holder.name if holder is not None else None
        if (
            proposed is None
            and self.target is not None
            and self.target[0] == ObjectKind.TRACK_CIRCUIT
        ):
            proposed = self.target[1]
        choices = [
            o.name
            for o in circuits
            if o.state in (AddressState.GREY, AddressState.YELLOW) and o.name != proposed
        ]
        if active:
            text = (
                f"Givaren {address} slog till. Är det {proposed}?"
                if proposed
                else f"Givaren {address} slog till. Vilken spårledning är det?"
            )
            answers: list[tuple[Answer, str]] = [("yes", "Ja"), ("no", "Nej")]
        else:
            where = f" på {proposed}" if proposed else ""
            text = (
                f"Givaren {address} släppte. Ställde du just en vagn{where}? Då är givaren "
                "omvänd: belagd när den släpper."
            )
            answers = [("reversed", "Ja, givaren är omvänd"), ("no", "Nej")]
        self._ask(
            kind=ObjectKind.TRACK_CIRCUIT,
            object=proposed,
            address=address,
            text=text,
            answers=answers,
            choices=choices,
            active=active,
        )
        return True

    # --- the owner's actions ------------------------------------------------------------------

    def learn(self, model: StationModel, kind: ObjectKind, name: str) -> list[bytes]:
        """Lär in: the frames to send now. LearnError when it cannot be done."""
        o = find(model, kind, name)
        if o is None:
            raise LearnError(f"{_cap(KIND_WORD[kind])} {name} finns inte i stationsmodellen.")
        if o.state == AddressState.WITHOUT:
            raise LearnError(f"{_cap(o.said)} är Utan adress och kopplas inte in.")
        self.message = None
        if kind == ObjectKind.TRACK_CIRCUIT:
            self.target = (kind, name)
            if self.question is not None and self.question.kind == kind:
                self.question = None
            return []
        if o.address is None:
            raise LearnError(f"{_cap(o.said)} har ingen adress. Ange adressen först.")
        if kind == ObjectKind.SWITCH:
            position = Position.PLUS if self.thrown.get(name) == Position.MINUS else Position.MINUS
            self.thrown[name] = position
            self._ask(
                kind=kind,
                object=name,
                address=o.address.number,
                text=f"Växel {name} ska lägga sig {POSITION_WORD[position]}. Gjorde den det?",
                answers=[
                    ("yes", "Ja"),
                    ("reversed", "Den lade sig åt andra hållet"),
                    ("no", "Nej, den rörde sig inte"),
                ],
                position=position,
            )
            return [switch_request(o.address.number, output_for(position, o.reversed))]
        self._ask(
            kind=kind,
            object=name,
            address=o.address.number,
            text=f"Signal {name} har fått kör. Visar den kör?",
            answers=[
                ("yes", "Ja, kör"),
                ("reversed", "Nej, den visar stopp"),
                ("no", "Nej, ingenting hände"),
            ],
        )
        return [switch_request(o.address.number, signal_output(True, o.reversed))]

    def answer(
        self, model: StationModel, question: int, answer: Answer, other: str | None = None
    ) -> Learnt:
        q = self.question
        if q is None or q.id != question:
            raise LearnError("Frågan gäller inte längre. Läs in sidan igen.")
        if q.kind == ObjectKind.TRACK_CIRCUIT:
            return self._circuit(model, q, answer, other)
        if q.kind == ObjectKind.SWITCH:
            return self._switch(model, q, answer)
        return self._signal(model, q, answer)

    def _circuit(self, model: StationModel, q: _Asked, answer: Answer, other: str | None) -> Learnt:
        name = other or q.object
        if answer == "no" and other is None:
            self.question = None
            return Learnt(None, [], f"Givaren {q.address} kopplades inte till något.")
        if name is None:
            raise LearnError("Välj spårledningen som givaren hör till.")
        o = find(model, ObjectKind.TRACK_CIRCUIT, name)
        if o is None:
            raise LearnError(f"Spårledningen {name} finns inte i stationsmodellen.")
        if o.state == AddressState.WITHOUT:
            raise LearnError(f"{name} är Utan adress och kopplas inte in.")
        address = confirmed(Address(number=q.address, reversed=not q.active))
        taken = [
            c.name
            for c in objects(model)
            if c.kind == ObjectKind.TRACK_CIRCUIT
            and c.name != name
            and c.address is not None
            and c.address.number == q.address
        ]
        for before in taken:
            model = changed(model, ObjectKind.TRACK_CIRCUIT, before, address=None)
        model = changed(model, ObjectKind.TRACK_CIRCUIT, name, address=address)
        self.question = None
        if self.target == (ObjectKind.TRACK_CIRCUIT, name):
            self.target = None
        said = f"{name} är grön: givare {q.address}{', omvänd' if not q.active else ''}."
        if taken:
            said += f" Givaren togs från {', '.join(taken)}."
        return Learnt(model, [], said)

    def _switch(self, model: StationModel, q: _Asked, answer: Answer) -> Learnt:
        name = q.object or ""
        o = find(model, ObjectKind.SWITCH, name)
        self.question = None
        if o is None or o.address is None:
            raise LearnError(f"Växel {name} finns inte längre i stationsmodellen.")
        if answer == "no":
            return Learnt(
                None,
                [],
                f"Växel {name} är kvar som gul. Kontrollera adressen {o.address.number} och "
                "försök igen.",
            )
        flip = answer == "reversed"
        address = confirmed(o.address.model_copy(update={"reversed": o.reversed != flip}))
        if flip and q.position is not None:
            other = Position.PLUS if q.position == Position.MINUS else Position.MINUS
            self.thrown[name] = other
        feedback = o.feedback
        if feedback is None and q.from_card:
            feedback = SwitchFeedback(type=FeedbackType.CARD)
        model = changed(model, ObjectKind.SWITCH, name, address=address, feedback=feedback)
        polarity = ", omvänd polaritet" if address.reversed else ""
        return Learnt(model, [], f"Växel {name} är grön: adress {address.number}{polarity}.")

    def _signal(self, model: StationModel, q: _Asked, answer: Answer) -> Learnt:
        name = q.object or ""
        o = find(model, ObjectKind.SIGNAL, name)
        if o is None or o.address is None:
            self.question = None
            raise LearnError(f"Signal {name} finns inte längre i stationsmodellen.")
        reversed_ = o.reversed != q.flipped
        stop = switch_request(o.address.number, signal_output(False, reversed_))
        if answer == "reversed" and not q.flipped:
            self._ask(
                kind=ObjectKind.SIGNAL,
                object=name,
                address=o.address.number,
                text=f"Med omvänd polaritet: visar signal {name} kör nu?",
                answers=[("yes", "Ja, kör"), ("no", "Nej")],
                flipped=True,
            )
            kör = switch_request(o.address.number, signal_output(True, not o.reversed))
            return Learnt(None, [kör], f"Signal {name} fick kör med omvänd polaritet.")
        self.question = None
        if answer != "yes":
            return Learnt(
                None,
                [stop],
                f"Signal {name} är kvar som gul. Kontrollera adressen {o.address.number}.",
            )
        address = confirmed(o.address.model_copy(update={"reversed": reversed_}))
        model = changed(model, ObjectKind.SIGNAL, name, address=address)
        polarity = ", omvänd polaritet" if reversed_ else ""
        return Learnt(
            model,
            [stop],
            f"Signal {name} är grön: adress {address.number}{polarity}. Den visar stopp igen.",
        )


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]
