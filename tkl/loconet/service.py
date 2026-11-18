"""The one LocoNet of a local TKL (#85): between the bus, Koppla in and the interlocking.

- Connect: a LocoBuffer USB, a BTLocoBridge, or the pretend LocoNet ("LocoNet ej ansluten",
  which Prova uses, STUDIO-24). On connecting, TKL asks every input for its state with JMRI's
  interrogation, and the interlocking at level 3 takes the field (STV-15). Disconnecting, or a
  link that fails, gives it back: the routes keep their locks and stop.
- Every message both ways goes to Lyssna. What comes is read by Koppla in, which asks its
  questions (STUDIO-04), and by the bus, whose reports go to the interlocking; what the
  interlocking then orders is sent. A switch without feedback is taken at its order.
- Discover finds the MGP cards and reads each one's base address, so that every object's card,
  module and channel can be shown (STUDIO-11, STUDIO-18). The owner names the modules.
- Koppla in's answers and the owner's changes are saved in the station model; level 3 is
  turned on when the model has addresses and the checks for level 3 pass (STD-17, §6).

LocoNet is local only: TKL in the cloud has no service at all and never opens a port
(TKLMOLN-08). The interlocking is read and kept through the store as for every other
operation; the link, Koppla in's questions and Lyssna live in memory only. One lock covers it
all; reports to Hubben go outside it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, TypeVar

from contracts.station_model import (
    WITHOUT,
    Address,
    FeedbackType,
    StationModel,
    SwitchControl,
    SwitchFeedback,
)
from contracts.tkl import (
    AddressState,
    LoconetType,
    ObjectKind,
    TklCard,
    TklCardChannel,
    TklFieldMode,
    TklInterlocking,
    TklKopplaIn,
    TklKopplaObject,
    TklLearnAnswer,
    TklLevel3,
    TklListen,
    TklLoconet,
    TklObjectChange,
    TklPort,
    TklReport,
)
from tkl.loconet.learning import LearnError, Learning
from tkl.loconet.link import Link, LinkError
from tkl.loconet.listen import Listening
from tkl.loconet.messages import (
    MGP_BASE_SV,
    MGP_CHANNELS,
    FrameError,
    Identity,
    Message,
    Sv,
    SvCommand,
    decode,
    discover,
    interrogation,
    read_sv4,
)
from tkl.loconet.objects import (
    KEEP,
    RUNNING,
    Bus,
    FieldReport,
    SwitchReported,
    Wired,
    changed,
    explicit,
    find,
    objects,
)
from tkl.loconet.simulator import MOVEMENT_SECONDS, PretendLoconet
from tkl.loconet.transports import (
    LABEL,
    PRETEND_PORT,
    Port,
    Transport,
    TransportError,
    open_port,
    ports,
)
from tkl.stallverk import Interlocking, Outcome, load, plant_of
from tkl.stallverk.interlocking import Order
from tkl.standard import problems
from tkl.store import InterlockingBusy, TklStore

T = TypeVar("T")
TICK_SECONDS: Final = 0.5
ROUNDS: Final = 100
"""At most this many reads in one pump: a message, its echo and its answers, and the next."""
STEP_SECONDS: Final = 0.05
CLOUD: Final = (
    "TKL i molnet har aldrig LocoNet. Nivå 3 kräver en lokal TKL på stationens dator eller en "
    "Raspberry Pi, med LocoBuffer USB eller BTLocoBridge (STV-27, TKLMOLN-08)."
)
NO_MODEL: Final = "Stationen har ingen stationsmodell. Koppla in kräver en spårplan i Studio."
NOT_CONNECTED: Final = "Anslut till LocoNet först."
BUSY: Final = (
    "Ställverket har lagda vägar eller tågnummer. Lös ut vägarna och ta bort tågnumren i "
    "Ställverket, eller nollställ det med tågnumren, innan stationsmodellen ändras."
)
ROUTES_SET: Final = (
    "Ställverket har lagda vägar. Lös ut dem innan du lär in, så att inget läggs om under ett tåg."
)
PRETEND_LABEL: Final = "Låtsas-LocoNet: LocoNet ej ansluten, som Prova använder"


class Refused(Exception):
    """What Koppla in says no to, with the HTTP status and, for a model, its problems."""

    def __init__(self, message: str, status: int = 409, found: list[str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.problems = found or []


@dataclass(frozen=True)
class Settings:
    """How the service reaches the world; the tests give their own."""

    background: bool = True
    opener: Callable[[LoconetType, str, int], Transport] = open_port
    listing: Callable[[], list[Port]] = ports
    clock: Callable[[], float] = time.monotonic
    movement: float = MOVEMENT_SECONDS
    discover_seconds: float = 1.5
    reply_seconds: float = 0.8


@dataclass(frozen=True)
class Card:
    address: int
    identity: Identity
    base: int | None


class Service:
    """LocoNet for the local station: one connection, Koppla in and Lyssna."""

    def __init__(
        self,
        store: TklStore,
        slot: str,
        settings: Settings | None = None,
        *,
        on_reports: Callable[[list[TklReport]], None] = lambda _reports: None,
    ) -> None:
        self.store = store
        self.slot = slot
        self.settings = settings or Settings()
        self.on_reports = on_reports
        self._lock = threading.RLock()
        self.link: Link | None = None
        self.pretend: PretendLoconet | None = None
        self.kind: LoconetType | None = None
        self.port: str | None = None
        self.channel: int | None = None
        self.since: datetime | None = None
        self.error: str | None = None
        self.listening = Listening()
        self.learning = Learning()
        self.message: str | None = None
        self._bus: tuple[str, Bus] | None = None
        self._replies: list[Sv] | None = None
        self._last_tick = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._release()

    # --- the connection -------------------------------------------------------------------

    def _release(self) -> None:
        """No link: an interlocking that still says LocoNet is connected, from before a
        restart, gives the field back."""
        self._interlock(lambda made: made.field_connect(None), need_field=True)

    def ports(self) -> list[TklPort]:
        found = [TklPort(type=p.type, port=p.path, label=p.label) for p in self.settings.listing()]
        found.append(TklPort(type=LoconetType.PRETEND, port=PRETEND_PORT, label=PRETEND_LABEL))
        return found

    def state(self) -> TklLoconet:
        with self._lock:
            connected = self.link is not None
            label = None
            if connected and self.kind == LoconetType.PRETEND:
                label = "LocoNet ej ansluten · låtsas-LocoNet"
            elif connected and self.kind is not None:
                label = f"LocoNet ansluten via {LABEL[self.kind]} ({self.port})"
            return TklLoconet(
                available=True,
                connected=connected,
                type=self.kind,
                port=self.port,
                channel=self.channel,
                label=label,
                error=self.error,
                since=self.since,
            )

    def connect(self, kind: LoconetType, port: str | None, channel: int = 1) -> None:
        """Anslut: the port opened, the inputs asked, and level 3's field taken."""
        with self._lock:
            if self.link is not None:
                self._close(None)
            model = self.store.station_model(self.slot)
            if model is None:
                raise Refused(NO_MODEL, 404)
            if kind == LoconetType.PRETEND:
                self.pretend = PretendLoconet.from_model(
                    model, clock=self.settings.clock, movement=self.settings.movement
                )
                transport: Transport = self.pretend
                port = PRETEND_PORT
            else:
                if not port:
                    raise Refused("Välj en port.", 400)
                try:
                    transport = self.settings.opener(kind, port, channel)
                except TransportError as error:
                    self.error = str(error)
                    raise Refused(str(error)) from error
            self.link = Link(
                transport,
                clock=self.settings.clock,
                on_sent=lambda data: self.listening.hear("out", data),
                on_error=self.listening.problem,
            )
            self.kind, self.port, self.channel = kind, port, channel
            self.since, self.error = datetime.now(UTC), None
            self.listening.clear()
            self.learning.forget()
            kept = self.store.loconet(self.slot)
            kept.update({"type": kind.value, "port": port, "channel": channel})
            self.store.save_loconet(self.slot, kept)
            try:
                for frame in interrogation():
                    self.link.send(frame)
            except LinkError as error:
                self._close(str(error))
                raise Refused(str(error)) from error
            self._take_field(model)
        self.pump()
        if self.settings.background:
            stop = self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(stop,), name="loconet", daemon=True
            )
            self._thread.start()

    def disconnect(self) -> None:
        with self._lock:
            self._close(None)

    def _close(self, error: str | None) -> None:
        self._stop.set()
        if self.link is not None:
            self.link.close()
        self.link, self.pretend, self.since = None, None, None
        self.error = error
        self.learning.forget()
        self._interlock(lambda made: made.field_connect(None), need_field=True)

    def _take_field(self, model: StationModel) -> None:
        """At level 3 the interlocking follows the layout from now."""
        if model.level != 3 or self.kind is None:
            return
        mode = TklFieldMode.PRETEND if self.kind == LoconetType.PRETEND else TklFieldMode.LOCONET
        self._interlock(lambda made: made.field_connect(mode), need_field=False)

    def _run(self, stop: threading.Event) -> None:
        """The connection's own thread: it ends with its connection."""
        while not stop.is_set():
            self.pump(STEP_SECONDS)
            if self.pretend is not None:
                stop.wait(STEP_SECONDS)

    def close(self) -> None:
        self.disconnect()
        if self._thread is not None:
            self._thread.join(timeout=2)

    # --- messages both ways ---------------------------------------------------------------

    def pump(self, timeout: float = 0.0) -> None:
        """Read what has come, pass it on, and send what follows; tick the link and the
        interlocking's time. A failed link disconnects with the reason."""
        reports: list[TklReport] = []
        with self._lock:
            link = self.link
            if link is None:
                return
            try:
                model = self.store.station_model(self.slot)
                for round_ in range(ROUNDS):
                    frames = link.receive(timeout if round_ == 0 else 0.0)
                    field: list[FieldReport] = []
                    for data in frames:
                        self.listening.hear("in", data)
                        try:
                            message = decode(data)
                        except FrameError:
                            continue
                        if model is not None:
                            self._read(model, message, field)
                    if field:
                        reports += self._interlock(_reported(field))
                    link.tick()
                    if not frames and link.idle:
                        break
                now = self.settings.clock()
                if now - self._last_tick >= TICK_SECONDS:
                    self._last_tick = now
                    reports += self._interlock(lambda made: made.field_tick())
            except LinkError as error:
                self._close(str(error))
                return
        if reports:
            self._deliver(reports)

    def _read(self, model: StationModel, message: Message, field: list[FieldReport]) -> None:
        if isinstance(message, Sv) and message.reply and self._replies is not None:
            self._replies.append(message)
        self.learning.observe(model, message)
        if model.level == 3 and self.kind is not None:
            field += self._bus_of(model).reports(message)

    def _bus_of(self, model: StationModel) -> Bus:
        fingerprint = plant_of(model).fingerprint
        if self._bus is None or self._bus[0] != fingerprint:
            mode = (
                TklFieldMode.PRETEND if self.kind == LoconetType.PRETEND else TklFieldMode.LOCONET
            )
            self._bus = (fingerprint, Bus(model, RUNNING[mode]))
        return self._bus[1]

    def _deliver(self, reports: list[TklReport]) -> None:
        """Up to Hubben, outside the lock: in a thread of its own when TKL runs."""
        if self.settings.background:
            threading.Thread(target=self.on_reports, args=(reports,), daemon=True).start()
        else:
            self.on_reports(reports)

    def _interlock(
        self, act: Callable[[Interlocking], Outcome], *, need_field: bool = True
    ) -> list[TklReport]:
        """One operation on the interlocking in one transaction, and its orders sent."""

        def change(
            model: StationModel | None, revision: int, body: str | None
        ) -> tuple[TklInterlocking | None, tuple[list[TklReport], list[Order]]]:
            if model is None or model.level < 3 or (body is None and need_field):
                return None, ([], [])
            made = load(plant_of(model), revision, body)
            if need_field and made.field is None:
                return None, ([], [])
            outcome = act(made)
            orders = made.take_orders()
            state = made.view() if made.revision != revision else None
            return state, (list(outcome.reports) if outcome.accepted else [], orders)

        reports, orders = self.store.change_interlocking(self.slot, change)
        self.send(orders)
        return reports

    def send(self, orders: list[Order]) -> None:
        """The interlocking's orders as LocoNet messages. A switch without feedback is taken
        at its order."""
        if not orders:
            return
        with self._lock:
            link = self.link
            model = self.store.station_model(self.slot)
            if link is None or model is None:
                return
            bus = self._bus_of(model)
            silent: list[FieldReport] = []
            try:
                for order in orders:
                    if order.kind == ObjectKind.SWITCH and order.position is not None:
                        frame = bus.switch_order(order.name, order.position)
                        if frame is not None and bus.silent(order.name):
                            silent.append(SwitchReported(order.name, order.position))
                    elif order.aspect is not None:
                        frame = bus.signal_order(order.name, order.aspect)
                    else:
                        frame = None
                    if frame is not None:
                        link.send(frame)
            except LinkError as error:
                self._close(str(error))
                return
            if silent:
                self._interlock(lambda made: made.field_reports(silent))

    # --- Koppla in ------------------------------------------------------------------------

    def view(self) -> TklKopplaIn:
        with self._lock:
            model = self.store.station_model(self.slot)
            kept = self.store.loconet(self.slot)
            return shown(
                model,
                self.state(),
                _cards(kept),
                _modules(kept),
                learning=self.learning,
                message=self.learning.message or self.message,
                discovered=_when(kept.get("discovered")),
            )

    def _model(self) -> StationModel:
        model = self.store.station_model(self.slot)
        if model is None:
            raise Refused(NO_MODEL, 404)
        return model

    def _save(self, model: StationModel) -> None:
        wrong = problems(model)
        if wrong:
            raise Refused("Ändringen gör att stationsmodellen inte kan köras.", 422, wrong)
        try:
            kept = self.store.save_model(self.slot, model)
        except InterlockingBusy as error:
            raise Refused(BUSY) from error
        if self.link is not None:
            self._take_field(kept)

    def learn(self, kind: ObjectKind, name: str) -> None:
        """Lär in: Lägg om, Skicka kör, or wait for a wagon."""
        with self._lock:
            link = self.link
            if link is None:
                raise Refused(NOT_CONNECTED)
            model = self._model()
            if kind != ObjectKind.TRACK_CIRCUIT and self._routes_set():
                raise Refused(ROUTES_SET)
            self.message = None
            try:
                frames = self.learning.learn(model, kind, name)
                for frame in frames:
                    link.send(frame)
            except LearnError as error:
                raise Refused(str(error)) from error
            except LinkError as error:
                self._close(str(error))
                raise Refused(str(error)) from error
        self.pump()

    def _routes_set(self) -> bool:
        _, _, body = self.store.interlocking(self.slot)
        if body is None:
            return False
        try:
            return bool(TklInterlocking.model_validate_json(body).routes)
        except ValueError:
            return True

    def answer(self, ask: TklLearnAnswer) -> None:
        with self._lock:
            model = self._model()
            try:
                learnt = self.learning.answer(model, ask.question, ask.answer, ask.object)
            except LearnError as error:
                raise Refused(str(error)) from error
            if learnt.model is not None:
                self._save(learnt.model)
            self.learning.message = None
            self.message = learnt.message
            if self.link is not None:
                try:
                    for frame in learnt.frames:
                        self.link.send(frame)
                except LinkError as error:
                    self._close(str(error))
        self.pump()

    def change(self, ask: TklObjectChange) -> None:
        """The owner's own address, polarity, feedback, or Utan adress."""
        with self._lock:
            model = self._model()
            self._save(object_changed(model, ask))
            self.message = f"{_cap(_said(ask.kind, ask.name))} är ändrad."

    def set_level(self, level: int) -> None:
        with self._lock:
            model = self._model()
            if level == 3:
                trial = model.model_copy(update={"level": 3})
                if not explicit(model):
                    raise Refused(
                        "Ingen adress är angiven än. Koppla in objekten först, eller ange "
                        "adresserna (STUDIO-18)."
                    )
                wrong = problems(trial)
                if wrong:
                    raise Refused("Nivå 3 kan inte slås på än.", 422, wrong)
                self._save(trial)
                self.message = "Nivå 3 är på: med LocoNet styr spårledningarna ställverket."
            else:
                self._save(model.model_copy(update={"level": min(model.level, 2)}))
                self.message = "Nivå 3 är av: ställverket går med knapparna som på nivå 1–2."

    def discover(self) -> None:
        """Discover: every card answers with its identity; each one's base address is read."""
        with self._lock:
            link = self.link
            if link is None:
                raise Refused(NOT_CONNECTED)
            self._replies = []
            try:
                link.send(discover())
            except LinkError as error:
                self._close(str(error))
                raise Refused(str(error)) from error
        found = self._wait(self.settings.discover_seconds, lambda _replies: False)
        cards: dict[int, Identity] = {}
        for sv in found:
            identity = sv.identity
            if identity is not None and sv.cmd == SvCommand.DISCOVER | 0x40:
                cards.setdefault(sv.card, identity)
        read: list[Card] = []
        for address, identity in sorted(cards.items()):
            base = self._base(address)
            read.append(Card(address, identity, base))
        with self._lock:
            kept = self.store.loconet(self.slot)
            kept["cards"] = [
                {
                    "address": c.address,
                    "manufacturer": c.identity.manufacturer,
                    "developer": c.identity.developer,
                    "product": c.identity.product,
                    "serial": c.identity.serial,
                    "base": c.base,
                }
                for c in read
            ]
            kept["discovered"] = datetime.now(UTC).isoformat()
            self.store.save_loconet(self.slot, kept)
            self.message = (
                f"Discover hittade {len(read)} kort." if read else "Inget kort svarade på Discover."
            )

    def _base(self, card: int) -> int | None:
        """SV21 and SV22: the base address, low and high byte. SV21 is the MGP cards' address
        (Benny's trace); that SV22 is its high byte is to be verified on a real card."""
        with self._lock:
            if self.link is None:
                return None
            self._replies = []
            try:
                self.link.send(read_sv4(card, MGP_BASE_SV))
            except LinkError:
                return None

        def answered(replies: list[Sv]) -> bool:
            return any(r.cmd == SvCommand.READ4 | 0x40 and r.card == card for r in replies)

        found = self._wait(self.settings.reply_seconds, answered)
        reply = next((r for r in found if r.cmd == SvCommand.READ4 | 0x40 and r.card == card), None)
        if reply is None:
            return None
        base = reply.data[0] | reply.data[1] << 8
        return base or None

    def _wait(self, seconds: float, done: Callable[[list[Sv]], bool]) -> list[Sv]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.pump()
            with self._lock:
                replies = list(self._replies or [])
            if done(replies):
                break
            time.sleep(0.01)
        with self._lock:
            replies, self._replies = list(self._replies or []), None
        return replies

    def set_module(self, card: int, module: str | None) -> None:
        with self._lock:
            kept = self.store.loconet(self.slot)
            if not any(c.get("address") == card for c in _raw_cards(kept)):
                raise Refused(f"Kort {card} finns inte. Kör Discover först.", 404)
            modules = dict(_modules(kept))
            name = (module or "").strip()
            if name:
                modules[card] = name
            else:
                modules.pop(card, None)
            kept["modules"] = {str(k): v for k, v in modules.items()}
            self.store.save_loconet(self.slot, kept)

    def pretend_wagon(self, track_circuit: str, occupied: bool) -> None:
        """Låtsas-LocoNet: a wagon put on a track circuit, or lifted off."""
        with self._lock:
            if self.pretend is None:
                raise Refused("Det går bara med låtsas-LocoNet.")
            try:
                self.pretend.occupy(track_circuit, occupied)
            except KeyError as error:
                raise Refused(f"{track_circuit} finns inte på låtsas-LocoNet.", 404) from error
        self.pump()

    def listen(self) -> TklListen:
        with self._lock:
            model = self.store.station_model(self.slot)
            return self.listening.view(model, self.link is not None)


def _reported(field: list[FieldReport]) -> Callable[[Interlocking], Outcome]:
    def act(made: Interlocking) -> Outcome:
        return made.field_reports(field)

    return act


# --- the page's view, also for TKL in the cloud ----------------------------------------------


def unavailable() -> TklLoconet:
    return TklLoconet(available=False, reason=CLOUD)


def shown(
    model: StationModel | None,
    loconet: TklLoconet,
    cards: list[Card],
    modules: dict[int, str],
    *,
    learning: Learning | None = None,
    message: str | None = None,
    discovered: datetime | None = None,
) -> TklKopplaIn:
    """Koppla in as the page shows it."""
    if model is None:
        return TklKopplaIn(
            loconet=loconet,
            level=0,
            level_3=TklLevel3(on=False, possible=False, reason=NO_MODEL),
            message=message,
        )
    found = objects(model)
    shown_cards = [_card(card, modules.get(card.address), found) for card in cards]
    rows = [_row(o, shown_cards) for o in found]
    return TklKopplaIn(
        loconet=loconet,
        level=model.level,
        level_3=_level_3(model, loconet),
        cards=shown_cards,
        discovered=discovered,
        objects=rows,
        question=learning.shown_question() if learning is not None else None,
        learning=learning.shown_learning() if learning is not None else None,
        message=message,
    )


def _level_3(model: StationModel, loconet: TklLoconet) -> TklLevel3:
    if not loconet.available:
        return TklLevel3(on=model.level == 3, possible=False, reason=CLOUD)
    if model.level == 3:
        return TklLevel3(on=True, possible=True)
    if not explicit(model):
        return TklLevel3(
            on=False,
            possible=False,
            reason="Ingen adress är angiven än: koppla in objekten först.",
        )
    wrong = problems(model.model_copy(update={"level": 3}))
    reason = "Rätta det som står nedan först." if wrong else None
    return TklLevel3(on=False, possible=not wrong, reason=reason, problems=wrong)


def _channels(card: Card) -> int:
    return MGP_CHANNELS.get(card.identity.product, 0) if card.base else 0


def _card(card: Card, module: str | None, found: list[Wired]) -> TklCard:
    channels = []
    if card.base:
        for k in range(1, _channels(card) + 1):
            address = card.base + k - 1
            names = [
                o.said
                for o in found
                if o.kind != ObjectKind.TRACK_CIRCUIT
                and o.address is not None
                and o.address.number == address
            ]
            channels.append(TklCardChannel(channel=k, address=address, objects=names))
    return TklCard(
        address=card.address,
        name=card.identity.name,
        manufacturer=card.identity.manufacturer,
        developer=card.identity.developer,
        product=card.identity.product,
        serial=card.identity.serial,
        base=card.base,
        module=module,
        channels=channels,
    )


def _row(o: Wired, cards: list[TklCard]) -> TklKopplaObject:
    card = module = channel = None
    if o.address is not None and o.kind != ObjectKind.TRACK_CIRCUIT:
        for c in cards:
            hit = next((ch for ch in c.channels if ch.address == o.address.number), None)
            if hit is not None:
                card, module, channel = c.address, c.module, hit.channel
                break
    feedback = o.feedback
    note = o.note
    if o.default and note is None:
        note = "Adressen är växelns nummer, som förval."
    return TklKopplaObject(
        kind=o.kind,
        name=o.name,
        state=o.state,
        address=o.address.number if o.address is not None else None,
        default=o.default,
        reversed=o.reversed,
        feedback=feedback.type if feedback is not None else None,
        straight=feedback.straight.number if feedback and feedback.straight else None,
        diverging=feedback.diverging.number if feedback and feedback.diverging else None,
        control=o.control,
        card=card,
        module=module,
        channel=channel,
        note=note,
    )


def object_changed(model: StationModel, ask: TklObjectChange) -> StationModel:
    """The model with the owner's change of one object (STUDIO-17, STUDIO-19, STUDIO-24). The
    address keeps its confirmation only while its number and polarity stay the same."""
    o = find(model, ask.kind, ask.name)
    if o is None:
        raise Refused(f"{_cap(_said(ask.kind, ask.name))} finns inte i stationsmodellen.", 404)
    if ask.kind == ObjectKind.SWITCH:
        if ask.without or ask.feedback == FeedbackType.MANUAL:
            return changed(
                model,
                ask.kind,
                ask.name,
                address=None,
                feedback=SwitchFeedback(type=FeedbackType.MANUAL),
                control=SwitchControl.MANUAL,
            )
        address = _address(o, ask)
        feedback: SwitchFeedback | None = None
        if ask.feedback == FeedbackType.SENSORS:
            feedback = SwitchFeedback(
                type=FeedbackType.SENSORS,
                straight=Address(number=ask.straight) if ask.straight else None,
                diverging=Address(number=ask.diverging) if ask.diverging else None,
            )
        elif ask.feedback is not None:
            feedback = SwitchFeedback(type=ask.feedback)
        kept_address = address if not (o.default and address == o.address) else KEEP
        return changed(
            model,
            ask.kind,
            ask.name,
            address=kept_address,
            feedback=feedback,
            control=SwitchControl.TKL,
        )
    if ask.without:
        return changed(model, ask.kind, ask.name, address=WITHOUT)
    return changed(model, ask.kind, ask.name, address=_address(o, ask))


def _address(o: Wired, ask: TklObjectChange) -> Address | None:
    if ask.address is None:
        return None
    reversed_ = o.reversed if ask.reversed is None else ask.reversed
    before = o.address
    if (
        before is not None
        and o.state != AddressState.WITHOUT
        and before.number == ask.address
        and before.reversed == reversed_
    ):
        return before
    return Address(number=ask.address, reversed=reversed_)


def _said(kind: ObjectKind, name: str) -> str:
    if kind == ObjectKind.TRACK_CIRCUIT:
        return f"spårledningen {name}"
    return f"{'växel' if kind == ObjectKind.SWITCH else 'signal'} {name}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _raw_cards(kept: dict[str, object]) -> list[dict[str, object]]:
    cards = kept.get("cards")
    return [c for c in cards if isinstance(c, dict)] if isinstance(cards, list) else []


def _cards(kept: dict[str, object]) -> list[Card]:
    found = []
    for c in _raw_cards(kept):
        try:
            identity = Identity(
                int(str(c["manufacturer"])),
                int(str(c["developer"])),
                int(str(c["product"])),
                int(str(c["serial"])),
            )
            base = c.get("base")
            found.append(
                Card(int(str(c["address"])), identity, int(str(base)) if base is not None else None)
            )
        except (KeyError, ValueError):
            continue
    return found


def _modules(kept: dict[str, object]) -> dict[int, str]:
    given = kept.get("modules")
    if not isinstance(given, dict):
        return {}
    return {int(k): str(v) for k, v in given.items() if str(k).isdigit()}


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
