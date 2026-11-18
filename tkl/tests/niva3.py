"""Level 3 for the tests (#85): a made-up station with its addresses, and the interlocking wired
to the pretend LocoNet through the same bus and link as on the layout.

    rig = Rig(level_3(provby()))
    rig.connect()
    rig.it.set_route("In", "12"); rig.run(1.0)

Nothing here names a station (RS13).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from contracts.station_model import Address, FeedbackType, StationModel, SwitchFeedback
from contracts.tkl import ObjectKind, TklFieldMode, TklReport
from tkl.loconet.link import Link
from tkl.loconet.messages import decode, interrogation
from tkl.loconet.objects import RUNNING, Bus, SwitchReported, changed, confirmed, objects
from tkl.loconet.simulator import PretendLoconet
from tkl.stallverk import Interlocking, plant_of
from tkl.stallverk.interlocking import Order

NOON = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
FIRST_SIGNAL = 101
FIRST_SENSOR = 501


def level_3(
    model: StationModel,
    *,
    green: bool = True,
    feedback: FeedbackType = FeedbackType.CARD,
) -> StationModel:
    """The model at level 3: every switch at its number, the signals from 101 and the track
    circuits' sensors from 501, confirmed on the layout (green) or only given (yellow)."""
    signal, sensor = FIRST_SIGNAL, FIRST_SENSOR
    for o in objects(model):
        if o.kind == ObjectKind.SWITCH:
            number = int(o.name)
        elif o.kind == ObjectKind.SIGNAL:
            number, signal = signal, signal + 1
        else:
            number, sensor = sensor, sensor + 1
        address = Address(number=number)
        given = confirmed(address) if green else address
        if o.kind == ObjectKind.SWITCH:
            model = changed(
                model, o.kind, o.name, address=given, feedback=SwitchFeedback(type=feedback)
            )
        else:
            model = changed(model, o.kind, o.name, address=given)
    return model.model_copy(update={"level": 3})


class Rig:
    """The interlocking, the bus, the link and the pretend LocoNet, with one clock."""

    def __init__(
        self,
        model: StationModel,
        *,
        mode: TklFieldMode = TklFieldMode.LOCONET,
        movement: float = 0.5,
        layout: PretendLoconet | None = None,
    ) -> None:
        self.model = model
        self.mode = mode
        self.seconds = 0.0
        self.layout = layout or PretendLoconet.from_model(
            model, clock=lambda: self.seconds, movement=movement
        )
        self.layout.clock = lambda: self.seconds
        self.link = Link(self.layout, clock=lambda: self.seconds)
        self.bus = Bus(model, RUNNING[mode])
        self.it = Interlocking(plant_of(model), now=self.now)
        self.up: list[TklReport] = []
        self.sent: list[Order] = []

    def now(self) -> datetime:
        return NOON + timedelta(seconds=self.seconds)

    def connect(self) -> None:
        assert self.it.field_connect(self.mode).accepted
        self.send(self.it.take_orders())
        for frame in interrogation():
            self.link.send(frame)
        self.run(0.2)

    def send(self, orders: list[Order]) -> None:
        self.sent += orders
        silent = []
        for order in orders:
            if order.kind == ObjectKind.SWITCH and order.position is not None:
                frame = self.bus.switch_order(order.name, order.position)
                if frame is not None and self.bus.silent(order.name):
                    silent.append(SwitchReported(order.name, order.position))
            elif order.aspect is not None:
                frame = self.bus.signal_order(order.name, order.aspect)
            else:
                frame = None
            if frame is not None:
                self.link.send(frame)
        if silent:
            self.up += self.it.field_reports(silent).reports

    def pump(self) -> None:
        reports = []
        for data in self.link.receive():
            reports += self.bus.reports(decode(data))
        if reports:
            outcome = self.it.field_reports(reports)
            self.up += outcome.reports
        self.link.tick()
        self.up += self.it.field_tick().reports
        self.send(self.it.take_orders())

    def run(self, seconds: float, step: float = 0.05) -> None:
        """The time goes, and the messages go both ways."""
        end = self.seconds + seconds
        while self.seconds < end:
            self.seconds += step
            for _ in range(20):
                self.pump()
                if self.link.idle and not self.layout._out:
                    break

    def do(self, outcome: object) -> object:
        """An operation's orders sent, as the server does after it."""
        self.send(self.it.take_orders())
        return outcome
