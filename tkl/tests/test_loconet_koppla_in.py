"""Koppla in (#85, STUDIO-04, STUDIO-17, STUDIO-19, STUDIO-24): the four states per object,
learning by touching against the pretend LocoNet, and Lyssna in Swedish.

The made-up Provby has no addresses of its own: its switches 1 and 2 have their numbers as the
default, and the pretend layout is wired with made-up addresses for the rest, which Koppla in
learns. Nothing here names a station (RS13).
"""

from __future__ import annotations

import pytest

from contracts.station_model import (
    Address,
    FeedbackType,
    Position,
    StationModel,
    SwitchControl,
    SwitchFeedback,
)
from contracts.tkl import AddressState, ObjectKind
from tkl.loconet.learning import LearnError, Learning
from tkl.loconet.listen import Listening, describe, meaning
from tkl.loconet.messages import (
    FrameReader,
    Output,
    decode,
    discover,
    from_hex,
    interrogation,
    sensor_report,
    switch_report,
    switch_request,
)
from tkl.loconet.objects import changed, confirmed, find, objects, states
from tkl.loconet.simulator import PretendLoconet
from tkl.tests.provstation import provby, switch

GREY, YELLOW, GREEN, WITHOUT = (
    AddressState.GREY,
    AddressState.YELLOW,
    AddressState.GREEN,
    AddressState.WITHOUT,
)
SWITCH, SIGNAL, CIRCUIT = ObjectKind.SWITCH, ObjectKind.SIGNAL, ObjectKind.TRACK_CIRCUIT


def state(model: StationModel, kind: ObjectKind, name: str) -> AddressState:
    return states(model)[(kind, name)]


def test_four_states_per_object() -> None:
    """STUDIO-17: grey not connected, yellow an address given, green confirmed on the layout,
    and Utan adress chosen for manual switches and virtual signals. STUDIO-19: a switch's
    number is its address as the default, and can be changed."""
    model = provby()
    assert state(model, SWITCH, "1") == YELLOW and find(model, SWITCH, "1").default  # type: ignore[union-attr]
    assert state(model, SIGNAL, "In") == GREY
    assert state(model, CIRCUIT, "Spår 1") == GREY
    model = changed(model, SIGNAL, "In", address=Address(number=201))
    assert state(model, SIGNAL, "In") == YELLOW
    model = changed(model, SIGNAL, "In", address=confirmed(Address(number=201)))
    assert state(model, SIGNAL, "In") == GREEN
    model = changed(model, SIGNAL, "D", address="without")
    assert state(model, SIGNAL, "D") == WITHOUT
    model = changed(model, CIRCUIT, "Spår 2", address="without")
    assert state(model, CIRCUIT, "Spår 2") == WITHOUT
    model = changed(model, SWITCH, "2", control=SwitchControl.MANUAL)
    assert state(model, SWITCH, "2") == WITHOUT
    model = changed(model, SWITCH, "1", address=Address(number=17))
    wired = find(model, SWITCH, "1")
    assert wired is not None and wired.address is not None and wired.address.number == 17
    assert not wired.default and wired.state == YELLOW, "the number changed: still yellow"
    named = provby(switches=[switch("Vx4", "b", "c", "d", node="1"), switch("2", "i", "g", "h")])
    assert state(named, SWITCH, "Vx4") == GREY, "Vx4 is no LocoNet address"
    assert [o.name for o in objects(provby()) if o.kind == SWITCH] == ["1", "2"]


class Bench:
    """Koppla in at the pretend layout: what TKL sends goes to the layout, what comes back is
    observed, as the service does."""

    def __init__(self, model: StationModel, reversed_: tuple[str, ...] = ()) -> None:
        self.model = model
        self.seconds = 0.0
        self.layout = PretendLoconet.from_model(
            model, reversed_=reversed_, clock=lambda: self.seconds
        )
        self.learning = Learning()
        self.reader = FrameReader()
        for frame in interrogation():
            self.send(frame)

    def send(self, data: bytes) -> None:
        self.layout.write(data)
        self.hear()

    def hear(self) -> None:
        for frame in self.reader.push(self.layout.read(0)):
            self.learning.observe(self.model, decode(frame))

    def wait(self, seconds: float) -> None:
        self.seconds += seconds
        self.hear()

    def learn(self, kind: ObjectKind, name: str) -> None:
        for frame in self.learning.learn(self.model, kind, name):
            self.send(frame)

    def answer(self, answer: str, other: str | None = None) -> str:
        q = self.learning.question
        assert q is not None
        done = self.learning.answer(self.model, q.id, answer, other)  # type: ignore[arg-type]
        if done.model is not None:
            self.model = done.model
        for frame in done.frames:
            self.send(frame)
        return done.message


def test_a_wagon_on_a_track_asks_and_yes_makes_it_green() -> None:
    """STUDIO-04: "Givaren 3 slog till. Är det Spår 1?" Yes gives the track circuit the
    address, confirmed: green. The interrogation's first answers ask nothing."""
    bench = Bench(provby())
    assert bench.learning.question is None, "the interrogation only gives the baseline"
    bench.learn(CIRCUIT, "Spår 1")
    learning = bench.learning.shown_learning()
    assert learning is not None and learning.text == "Ställ en vagn på Spår 1."
    bench.layout.occupy("Spår 1")
    bench.hear()
    q = bench.learning.shown_question()
    assert q is not None and q.text == "Givaren 3 slog till. Är det Spår 1?"
    assert [a.label for a in q.answers] == ["Ja", "Nej"]
    assert "Spår 2" in q.choices and "Spår 1" not in q.choices
    said = bench.answer("yes")
    assert said == "Spår 1 är grön: givare 3."
    assert state(bench.model, CIRCUIT, "Spår 1") == GREEN
    assert bench.learning.question is None and bench.learning.target is None
    bench.layout.occupy("Spår 1", False)
    bench.hear()
    bench.layout.occupy("Spår 1")
    bench.hear()
    assert bench.learning.question is None, "a green track circuit asks nothing"
    assert bench.learning.message == "Givaren 3 slog till: Spår 1, redan bekräftad."


def test_the_owner_may_name_another_track_and_the_sensor_moves_to_it() -> None:
    model = changed(provby(), CIRCUIT, "Spår 2", address=Address(number=4))
    bench = Bench(model)
    bench.layout.occupy("Spår 1")
    bench.hear()
    q = bench.learning.shown_question()
    assert q is not None and q.text == "Givaren 3 slog till. Vilken spårledning är det?"
    bench.layout.occupy("Spår 2")
    bench.hear()
    q = bench.learning.shown_question()
    assert q is not None and q.text == "Givaren 4 slog till. Är det Spår 2?"
    said = bench.answer("yes", "Vx2")
    assert said == "Vx2 är grön: givare 4. Givaren togs från Spår 2."
    assert state(bench.model, CIRCUIT, "Vx2") == GREEN
    assert state(bench.model, CIRCUIT, "Spår 2") == GREY
    with pytest.raises(LearnError, match="gäller inte längre"):
        bench.learning.answer(bench.model, 99, "yes")


def test_a_sensor_that_lets_go_when_the_wagon_comes_is_reversed() -> None:
    """STUDIO-24: the polarity per object, through a question."""
    bench = Bench(provby(), reversed_=("Spår 1",))
    bench.learn(CIRCUIT, "Spår 1")
    bench.layout.occupy("Spår 1")
    bench.hear()
    q = bench.learning.shown_question()
    assert q is not None and q.text.startswith(
        "Givaren 3 släppte. Ställde du just en vagn på Spår 1?"
    )
    assert [a.value for a in q.answers] == ["reversed", "no"]
    assert bench.answer("reversed") == "Spår 1 är grön: givare 3, omvänd."
    wired = find(bench.model, CIRCUIT, "Spår 1")
    assert wired is not None and wired.reversed and wired.state == GREEN


def test_lagg_om_throws_the_switch_and_the_answer_confirms_address_and_polarity() -> None:
    """STUDIO-04 and STUDIO-24: Lägg om sends the request; the card's report is shown; yes
    makes the switch green with feedback from the card, and the other way reverses it."""
    bench = Bench(provby())
    bench.learn(SWITCH, "1")
    q = bench.learning.shown_question()
    assert (
        q is not None
        and q.text == "Växel 1 ska lägga sig avvikande (\N{MINUS SIGN}). Gjorde den det?"
    )
    assert [a.value for a in q.answers] == ["yes", "reversed", "no"]
    assert bench.layout.received()[-1] == switch_request(1, Output.THROWN)
    bench.wait(1.0)
    q = bench.learning.shown_question()
    assert q is not None and q.seen == "Kortet rapporterade avvikande (\N{MINUS SIGN})."
    assert bench.answer("yes") == "Växel 1 är grön: adress 1."
    wired = find(bench.model, SWITCH, "1")
    assert wired is not None and wired.state == GREEN and not wired.default
    assert wired.feedback == SwitchFeedback(type=FeedbackType.CARD)
    bench.learn(SWITCH, "1")
    assert bench.layout.received()[-1] == switch_request(1, Output.CLOSED), "back again"
    reversed_ = Bench(provby(), reversed_=("2",))
    reversed_.learn(SWITCH, "2")
    reversed_.wait(1.0)
    assert reversed_.layout.position("2") == Position.PLUS, "it went the other way"
    said = reversed_.answer("reversed")
    assert said == "Växel 2 är grön: adress 2, omvänd polaritet."
    assert find(reversed_.model, SWITCH, "2").reversed  # type: ignore[union-attr]
    nothing = Bench(provby())
    nothing.learn(SWITCH, "1")
    assert (
        nothing.answer("no") == "Växel 1 är kvar som gul. Kontrollera adressen 1 och försök igen."
    )
    assert state(nothing.model, SWITCH, "1") == YELLOW


def test_skicka_kor_asks_and_tries_the_other_polarity() -> None:
    """STUDIO-04: Skicka kör orders kör and asks; stopp after the answer. A signal that shows
    stopp gets kör with the polarity reversed, and is asked again."""
    model = changed(provby(), SIGNAL, "In", address=Address(number=1001))
    bench = Bench(model, reversed_=("In",))
    bench.learn(SIGNAL, "In")
    q = bench.learning.shown_question()
    assert q is not None and q.text == "Signal In har fått kör. Visar den kör?"
    assert not bench.layout.proceed("In")
    assert bench.answer("reversed") == "Signal In fick kör med omvänd polaritet."
    assert bench.layout.proceed("In")
    q = bench.learning.shown_question()
    assert q is not None and q.text == "Med omvänd polaritet: visar signal In kör nu?"
    said = bench.answer("yes")
    assert said == "Signal In är grön: adress 1001, omvänd polaritet. Den visar stopp igen."
    assert not bench.layout.proceed("In"), "stopp after the answer"
    wired = find(bench.model, SIGNAL, "In")
    assert wired is not None and wired.reversed and wired.state == GREEN


def test_what_cannot_be_learnt_says_why() -> None:
    model = changed(provby(), SIGNAL, "D", address="without")
    learning = Learning()
    with pytest.raises(LearnError, match="Utan adress"):
        learning.learn(model, SIGNAL, "D")
    with pytest.raises(LearnError, match="har ingen adress"):
        learning.learn(model, SIGNAL, "In")
    with pytest.raises(LearnError, match="finns inte"):
        learning.learn(model, CIRCUIT, "Spår 9")


def test_lyssna_decodes_in_swedish_with_the_objects_and_their_polarity() -> None:
    """STUDIO-24, Lyssna behind Felsök. Ported: telegram-recorder.mjs's describeProtocol and
    communication-diagnostics.test.mjs, "inverted turnout expectation uses the physical address
    and polarity exactly once"."""
    model = changed(provby(), SWITCH, "1", address=Address(number=1, reversed=True))
    model = changed(model, CIRCUIT, "Spår 1", address=Address(number=73))
    found = objects(model)
    report = decode(switch_report(1, Output.CLOSED))
    assert describe(report) == "Växelrapport från adress 1: closed (C)."
    assert meaning(report, found) == ["växel 1: avvikande (\N{MINUS SIGN})"], "reversed"
    sensor = decode(sensor_report(73, True))
    assert describe(sensor) == "Givare 73: slog till (aktiv)."
    assert meaning(sensor, found) == ["Spår 1: belagd"]
    assert describe(decode(from_hex("B0 7A 07 32"))).startswith("Avfrågning, grupp 0/1/0")
    assert describe(decode(discover())) == "Discover: alla kort svarar med sin identitet."
    assert describe(decode(from_hex("B4 30 00 7B"))) == (
        "Långt kvitto: kommandostationen avvisade en växelorder."
    )
    listening = Listening()
    listening.hear("out", switch_request(1, Output.THROWN))
    listening.hear("in", sensor_report(73, True))
    listening.hear("in", b"\xb0\x7a\x30\x04")
    shown = listening.view(model, True)
    assert [m.direction for m in shown.messages] == ["in", "in", "out"], "newest first"
    assert shown.messages[0].text == "Fel kontrollsumma."
    assert shown.messages[1].objects == ["Spår 1: belagd"]
    assert shown.messages[2].text == "Order till adress 1: thrown (T), på."
    assert shown.messages[2].objects == ["växel 1: rakt (+)"]
