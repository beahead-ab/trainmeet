"""Studio's Prova (#85 del c): TKL's simulator runs a train through every route (STUDIO-05,
STUDIO-21, STUDIO-27).

Every train route and every shunting route the engine derives, the preferred path of each kind,
start and end, is tried one at a time, each from a clean state:

- at level 3, the interlocking in field mode against the pretend LocoNet, through the same bus
  and link as on the layout, so that the same code is tried as runs for real (STUDIO-21). The
  route is set; its switches move and report; the signal shows kör on the layout; a pretend
  train occupies and frees the track circuits along the route, the train number follows it and
  the interlocking releases section by section behind it. The route ends with the arrival, the
  entry route released after passage (STV-16), or with the departure on a route out;
- at level 1–2, the same interlocking with Kör: section by section, then Ankommit, or out on the
  line.

Each route passes, or fails with the reason in Swedish: the interlocking's own no (locked,
occupied, an object that is grey), no feedback, a signal that does not clear, a train number that
does not follow, a section not released. Everything runs on a virtual clock, so nothing waits
for real; the Runner runs it in the background with its progress. When every route has passed
the station is Klart for that model (STUDIO-05).

Pure Python without I/O. No code here names a station (RS13).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import BaseModel, ValidationError

from contracts.station_model import StationModel, SwitchControl
from contracts.tkl import (
    ObjectKind,
    RouteKind,
    TklAspect,
    TklFieldMode,
    TklProva,
    TklProvaResult,
    TklProvaRoute,
    TklProvaSimulator,
    TklProvaWay,
    TklProvkor,
    TklReport,
    TklReportKind,
    TklSetRoute,
)
from tkl.loconet.link import Link
from tkl.loconet.messages import decode, interrogation
from tkl.loconet.objects import RUNNING, Bus, SwitchReported
from tkl.loconet.simulator import MOVEMENT_SECONDS, PretendLoconet
from tkl.stallverk import Interlocking, Outcome, Plant, Way, plant_of
from tkl.stallverk.interlocking import FEEDBACK_SECONDS, Order
from tkl.stallverk.plant import sign
from tkl.standard import PointKind
from tkl.standard import RouteKind as EngineKind

TRAIN: Final = "1"
"""The pretend train's number."""
EPOCH: Final = datetime(2000, 1, 1, tzinfo=UTC)
STEP: Final = 0.05
"""The virtual clock's step, in seconds."""
ROUNDS: Final = 20
MOST_RUNNING: Final = 4
"""Prova runs at most this many stations at once: TKL in the cloud has many."""
WORD: Final = {EngineKind.TRAIN: "tågvägen", EngineKind.SHUNTING: "växlingsvägen"}

LayoutMaker = Callable[[StationModel], PretendLoconet]
"""The pretend layout for one route; the tests give a broken one."""


def simulator(level: int) -> TklProvaSimulator:
    return TklProvaSimulator.PRETEND if level >= 3 else TklProvaSimulator.KOR


def ways(model: StationModel) -> list[Way]:
    """The routes Prova runs: the engine's route for each kind, start and end, train routes
    first."""
    found = plant_of(model).preferred()
    return [w for w in found if w.kind == EngineKind.TRAIN] + [
        w for w in found if w.kind == EngineKind.SHUNTING
    ]


def way_of(way: Way, pieces: Iterable[str] | None = None) -> TklProvaWay:
    return TklProvaWay(
        kind=RouteKind(way.kind.value),
        start=way.start,
        end=way.end,
        pieces=list(way.pieces if pieces is None else pieces),
    )


def _result(
    way: Way, result: TklProvaResult, reason: str | None, pieces: Iterable[str] | None = None
) -> TklProvaRoute:
    shown = way_of(way, pieces)
    return TklProvaRoute(**shown.model_dump(), result=result, reason=reason)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _listed(names: Iterable[str]) -> str:
    found = list(names)
    if len(found) < 2:
        return "".join(found)
    return f"{', '.join(found[:-1])} och {found[-1]}"


def _sentence(text: str) -> str:
    text = _cap(text.strip())
    return text if text.endswith((".", "!", "?")) else text + "."


class Failed(Exception):
    """A route that did not pass: the reason in Swedish."""


# --- level 3: the interlocking against the pretend LocoNet --------------------------------------


class Bench:
    """The interlocking, the bus, the link and the pretend LocoNet, on one virtual clock: the
    station as it would run on the layout, with LocoNet ej ansluten (STUDIO-24)."""

    def __init__(
        self,
        plant: Plant,
        *,
        layout: PretendLoconet | None = None,
        mode: TklFieldMode = TklFieldMode.PRETEND,
    ) -> None:
        model = plant.model
        self.plant = plant
        self.mode = mode
        self.seconds = 0.0
        self.layout = layout or PretendLoconet.from_model(
            model, clock=self.clock, movement=MOVEMENT_SECONDS
        )
        self.layout.clock = self.clock
        self.link = Link(self.layout, clock=self.clock)
        self.bus = Bus(model, RUNNING[mode])
        self.it = Interlocking(plant, now=self.now)
        self.up: list[TklReport] = []

    def clock(self) -> float:
        return self.seconds

    def now(self) -> datetime:
        return EPOCH + timedelta(seconds=self.seconds)

    def connect(self) -> Outcome:
        """LocoNet anslutet: every signal to stop, and every input asked for its state."""
        outcome = self.it.field_connect(self.mode)
        if outcome.accepted:
            self.send(self.it.take_orders())
            for frame in interrogation():
                self.link.send(frame)
            self.run(0.2)
        return outcome

    def do(self, outcome: Outcome) -> Outcome:
        """An operation's orders sent, as the server does after it."""
        self.up += outcome.reports
        self.send(self.it.take_orders())
        return outcome

    def send(self, orders: list[Order]) -> None:
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
            self.up += self.it.field_reports(reports).reports
        self.link.tick()
        self.up += self.it.field_tick().reports
        self.send(self.it.take_orders())

    def run(self, seconds: float) -> None:
        """The time goes, and the messages go both ways."""
        end = self.seconds + seconds - STEP / 2
        while self.seconds < end:
            self.seconds += STEP
            for _ in range(ROUNDS):
                self.pump()
                if self.link.idle and not self.layout.pending:
                    break

    def until(self, done: Callable[[], bool], seconds: float) -> bool:
        end = self.seconds + seconds
        while not done():
            if self.seconds >= end:
                return False
            self.run(STEP)
        return True

    def detects(self, section: str) -> bool:
        """The section's circuit is on the bus and on the pretend layout."""
        return (
            ObjectKind.TRACK_CIRCUIT,
            section,
        ) in self.bus.by_name and section in self.layout.wiring.circuits


def _route(bench: Bench, route_id: int) -> TklSetRoute:
    shown = bench.it.shown_route(route_id)
    if shown is None:
        raise Failed("Vägen löstes ut innan tåget hade kört den.")
    return shown


def _box(plant: Plant, exit_id: str | None) -> str | None:
    """The section on the line just outside an exit's entry signal."""
    place = plant.exits.get(exit_id or "")
    if place is None or not place.pieces:
        return None
    return plant.section_of.get(place.pieces[-1])


def _on_layout(plant: Plant, way: Way, layout: PretendLoconet | None) -> list[str]:
    """One route at level 3 against the pretend LocoNet. Returns its pieces; Failed with the
    reason."""
    bench = Bench(plant, layout=layout)
    said = bench.connect()
    if not said.accepted:
        raise Failed(said.message)
    laid = bench.do(bench.it.set_route(way.start, way.end, way.kind))
    if not laid.accepted or laid.route is None:
        raise Failed(laid.message)
    route_id = laid.route
    names = [s.section for s in _route(bench, route_id).sections]
    pieces = [p for s in _route(bench, route_id).sections for p in s.pieces]

    # The switches move and report, and the signal clears on the layout (STV-11).
    def settled() -> bool:
        shown = _route(bench, route_id)
        return not shown.waiting or shown.held is not None

    bench.until(settled, FEEDBACK_SECONDS + 1.0)
    shown = _route(bench, route_id)
    if shown.held:
        raise Failed(shown.held)
    if shown.waiting:
        raise Failed(f"ingen återrapport från växel {_listed(shown.waiting)}")
    bench.run(0.3)
    layout_ = bench.layout
    for part, position in shown.positions.items():
        if plant.control.get(part) != SwitchControl.TKL or part not in layout_.wiring.switches:
            continue
        if (ObjectKind.SWITCH, part) not in bench.bus.by_name:
            continue
        lies = layout_.position(part)
        if lies != position:
            where = "i rörelse" if lies is None else f"i {sign(lies)}"
            raise Failed(f"växel {part} ligger {where} på banan, men vägen kräver {sign(position)}")
    signal = way.route.start.kind == PointKind.SIGNAL
    if signal and shown.aspect == TklAspect.STOP:
        raise Failed(f"signalen {way.start} visar stopp fast vägen ligger")
    on_bus = (ObjectKind.SIGNAL, way.start) in bench.bus.by_name
    if signal and on_bus and not layout_.proceed(way.start):
        raise Failed(f"signalen {way.start} visar inte kör på banan")

    # The train at the start: on the line at an exit, or in a section before the route.
    circuits: list[str] = []
    numbered = False
    for kind, name in sorted(way.starts):
        if kind == "exit":
            put = bench.do(bench.it.put_train(TRAIN, exit=name))
            box = _box(plant, name)
            if box is not None and box not in names and bench.detects(box):
                circuits = [box]
        elif name not in names:
            put = bench.do(bench.it.put_train(TRAIN, section=name))
            if bench.detects(name):
                circuits = [name]
        else:
            continue
        if not put.accepted:
            raise Failed(put.message)
        numbered = True
        break
    inside = not numbered
    """No place for the train before the route: it stands in the route's own first section, as
    from a buffer stop, and enters without a number."""
    if circuits:
        layout_.put_train(TRAIN, circuits)
        bench.run(0.1)

    # Along the route: the front into each circuit, the tail out of the one behind it.
    detected = [i for i, name in enumerate(names) if bench.detects(name)]
    if not detected:
        raise Failed("ingen spårledning på vägen säger var tåget är")
    for i in detected:
        name = names[i]
        if circuits:
            layout_.move_train(TRAIN, name)
        else:
            layout_.put_train(TRAIN, [name])
        circuits = list(layout_.trains[TRAIN].circuits)
        bench.run(0.1)
        shown = _route(bench, route_id)
        if shown.at != i:
            raise Failed(
                f"tåget syns inte i {plant.said(name)}: tågnumret följde inte spårledningen"
            )
        tail = circuits[0]
        behind = names.index(tail) if tail in names else 0
        for j in range(behind):
            if not shown.sections[j].released:
                raise Failed(f"{plant.said(names[j])} löstes inte ut efter tåget")
    last = names[detected[-1]]

    if way.leaves is None and inside and len(detected) == 1:
        # The train never leaves the one circuit it started in: nothing can tell the passage,
        # and occupancy frees nothing (STV-16). The operator releases it, as on the layout.
        released = bench.do(bench.it.release(route_id))
        if not released.accepted:
            raise Failed(released.message)
        return pieces
    if way.leaves is None:
        # The tail comes in: the entry route is released after passage (STV-16).
        layout_.move_train(TRAIN, last, length=1)
        bench.run(0.1)
        if bench.it.shown_route(route_id) is not None:
            raise Failed(
                f"vägen löstes inte ut efter passagen: tåget står i {plant.said(last)}, men "
                "ankomsten kom inte"
            )
        if numbered and way.kind == EngineKind.TRAIN:
            arrived = [u for u in bench.up if u.kind == TklReportKind.ARRIVED]
            if not arrived:
                raise Failed("ankomsten rapporterades inte")
        return pieces
    box = _box(plant, way.leaves)
    if box is not None and box not in names and bench.detects(box):
        layout_.move_train(TRAIN, box)
        bench.run(0.1)
        layout_.move_train(TRAIN, box, length=1)
    else:
        layout_.remove_train(TRAIN)
    bench.run(0.1)
    if bench.it.shown_route(route_id) is not None:
        raise Failed(f"tåget lämnade mot {way.leaves}, men avgången kom inte: vägen ligger kvar")
    if numbered and not any(u.kind == TklReportKind.DEPARTED for u in bench.up):
        raise Failed("avgången rapporterades inte")
    return pieces


# --- level 1–2: the same interlocking with Kör ------------------------------------------------


def _put_at_start(it: Interlocking, way: Way) -> bool:
    for kind, name in sorted(way.starts):
        put = (
            it.put_train(TRAIN, section=name)
            if kind == "section"
            else it.put_train(TRAIN, exit=name)
        )
        if put.accepted:
            return True
    return False


def _with_kor(plant: Plant, way: Way) -> list[str]:
    """One route at level 1–2: set, a train at its start, Kör section by section, then
    Ankommit or out on the line (STV-06, STV-16). Returns its pieces; Failed with the reason."""
    it = Interlocking(plant, now=lambda: EPOCH)
    laid = it.set_route(way.start, way.end, way.kind)
    if not laid.accepted or laid.route is None:
        raise Failed(laid.message)
    route_id = laid.route
    if not _put_at_start(it, way):
        # From a stop point or a buffer stop the train stands in the route's own first section,
        # having come in over the same switches: they stay as the route laid them.
        it.release(route_id)
        if not _put_at_start(it, way):
            raise Failed(f"det finns ingen plats för ett tåg vid starten {way.start}")
        laid = it.set_route(way.start, way.end, way.kind)
        if not laid.accepted or laid.route is None:
            raise Failed(laid.message)
        route_id = laid.route
    shown = it.shown_route(route_id)
    assert shown is not None
    pieces = [p for s in shown.sections for p in s.pieces]
    if way.route.start.kind == PointKind.SIGNAL and shown.aspect == TklAspect.STOP:
        raise Failed(f"signalen {way.start} visar stopp fast vägen ligger")
    last = len(shown.sections) - 1
    for _ in range(len(shown.sections) + 1):
        if shown.at == last:
            break
        stepped = it.step(route_id)
        if not stepped.accepted:
            raise Failed(stepped.message)
        after = it.shown_route(route_id)
        if after is None:
            raise Failed("vägen löstes ut innan tåget kom fram")
        shown = after
        behind = shown.sections[shown.at - 1] if shown.at > 0 else None
        if behind is not None and not behind.released:
            raise Failed(f"{plant.said(behind.section)} löstes inte ut bakom tåget")
    if shown.at != last:
        raise Failed("tåget kom inte fram till målet med Kör")
    if way.leaves is not None:
        left = it.step(route_id)
        if not left.accepted:
            raise Failed(left.message)
        if not any(r.kind == TklReportKind.DEPARTED for r in left.reports):
            raise Failed("avgången rapporterades inte")
    else:
        arrived = it.arrive(route_id)
        if not arrived.accepted:
            raise Failed(arrived.message)
        if not any(r.kind == TklReportKind.ARRIVED for r in arrived.reports):
            raise Failed("ankomsten rapporterades inte")
    view = it.view()
    if view.routes:
        raise Failed("vägen ligger kvar efter tåget")
    locked = sorted(p for p, s in view.switches.items() if s.routes)
    if locked:
        raise Failed(f"växel {_listed(locked)} är fortfarande låst")
    return pieces


def try_route(model: StationModel, way: Way, layout: LayoutMaker | None = None) -> TklProvaRoute:
    """One route from a clean state: passed, or failed with the reason (STUDIO-27)."""
    plant = plant_of(model)
    try:
        if model.level >= 3:
            pieces = _on_layout(plant, way, layout(model) if layout is not None else None)
        else:
            pieces = _with_kor(plant, way)
    except Failed as failed:
        return _result(way, TklProvaResult.FAILED, _sentence(str(failed)))
    except Exception as error:  # a bug must not stop the other routes
        said = f"Simulatorn kunde inte köra vägen ({type(error).__name__})."
        return _result(way, TklProvaResult.FAILED, said)
    return _result(way, TklProvaResult.PASSED, None, pieces)


def try_all(
    model: StationModel,
    *,
    layout: LayoutMaker | None = None,
    progress: Callable[[TklProvaRoute], None] = lambda _route: None,
    stop: threading.Event | None = None,
) -> list[TklProvaRoute]:
    """Every route, one at a time from a clean state, in the engine's order."""
    found: list[TklProvaRoute] = []
    for way in ways(model):
        if stop is not None and stop.is_set():
            break
        tried = try_route(model, way, layout)
        found.append(tried)
        progress(tried)
    return found


ORDER: Final = {TklProvaResult.FAILED: 0, TklProvaResult.SKIPPED: 1, TklProvaResult.PASSED: 2}


def failures_first(routes: Iterable[TklProvaRoute]) -> list[TklProvaRoute]:
    """The routes that did not pass first, then the rest, each in the engine's order."""
    numbered = list(enumerate(routes))
    return [r for _, r in sorted(numbered, key=lambda item: (ORDER[item[1].result], item[0]))]


# --- what is kept with the station -----------------------------------------------------------


class Saved(BaseModel):
    """Prova's results as TKL keeps them with the station, for one model (tkl/store.py)."""

    simulator: TklProvaSimulator
    routes: list[TklProvaRoute] = []
    total: int = 0
    started: datetime | None = None
    finished: datetime | None = None
    provkor: list[TklProvaRoute] = []
    provkor_finished: datetime | None = None

    @property
    def tried(self) -> bool:
        """Klart: every route the model has ran, and every one passed."""
        return (
            self.finished is not None
            and self.total > 0
            and len(self.routes) == self.total
            and all(r.result == TklProvaResult.PASSED for r in self.routes)
        )


def read(body: str | None) -> Saved | None:
    if body is None:
        return None
    try:
        return Saved.model_validate_json(body)
    except ValidationError:
        return None


# --- the background ---------------------------------------------------------------------------


class Busy(Exception):
    """Prova already runs as many stations as it takes."""


@dataclass
class Job:
    """One station's run: its progress and its results so far."""

    model: str
    """The fingerprint of the model it runs."""
    simulator: TklProvaSimulator
    total: int
    started: datetime
    routes: list[TklProvaRoute] = field(default_factory=list)
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    @property
    def done(self) -> int:
        return len(self.routes)


class Runner:
    """Prova in the background, one run per station and a few at a time, with the progress
    in memory. The results are kept with the station by `finish` when the run is over."""

    def __init__(self, *, most: int = MOST_RUNNING, layout: LayoutMaker | None = None) -> None:
        self.most = most
        self.layout = layout
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def job(self, slot: str) -> Job | None:
        with self._lock:
            return self._jobs.get(slot)

    def start(
        self,
        slot: str,
        model: StationModel,
        fingerprint: str,
        finish: Callable[[Job, bool], None],
    ) -> Job:
        """A new run for the station, unless one already runs: then that one. `finish` gets
        the job and whether it ran to its end."""
        with self._lock:
            running = self._jobs.get(slot)
            if running is not None:
                return running
            if len(self._jobs) >= self.most:
                raise Busy()
            job = Job(
                model=fingerprint,
                simulator=simulator(model.level),
                total=len(ways(model)),
                started=datetime.now(UTC),
            )
            self._jobs[slot] = job

        def run() -> None:
            complete = False
            try:
                try_all(model, layout=self.layout, progress=job.routes.append, stop=job.stop)
                complete = not job.stop.is_set()
            finally:
                try:
                    finish(job, complete)
                finally:
                    with self._lock:
                        self._jobs.pop(slot, None)

        job.thread = threading.Thread(target=run, name=f"prova-{slot[:8]}", daemon=True)
        job.thread.start()
        return job

    def stop(self, slot: str) -> None:
        job = self.job(slot)
        if job is not None:
            job.stop.set()

    def close(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.stop.set()
        for job in jobs:
            if job.thread is not None:
                job.thread.join(timeout=5)


def saved_of(job: Job, before: Saved | None) -> Saved:
    """A finished run as it is kept: Provkör's results stay when the model is the same."""
    kept = before if before is not None else None
    return Saved(
        simulator=job.simulator,
        routes=list(job.routes),
        total=job.total,
        started=job.started,
        finished=datetime.now(UTC),
        provkor=kept.provkor if kept is not None else [],
        provkor_finished=kept.provkor_finished if kept is not None else None,
    )


# --- the page ---------------------------------------------------------------------------------

NOT_TRIED: Final = (
    "Stationen är inte provad i Studio \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} Prova"
)


def view(
    model: StationModel | None,
    current: str | None,
    saved: tuple[str, Saved | None] | None,
    job: Job | None,
    provkor: TklProvkor,
) -> TklProva:
    """Prova as the page shows it: the run in progress, else the kept results when they are for
    the model as it is now."""
    if model is None:
        return TklProva(
            level=0,
            message="Stationen har ingen stationsmodell. Prova kräver en spårplan i Studio.",
            provkor=provkor,
        )
    kind = simulator(model.level)
    if job is not None and job.model == current:
        routes = failures_first(job.routes)
        failed = sum(1 for r in routes if r.result == TklProvaResult.FAILED)
        return TklProva(
            level=model.level,
            simulator=job.simulator,
            running=True,
            done=job.done,
            total=job.total,
            routes=routes,
            passed=job.done - failed,
            failed=failed,
            started=job.started,
            provkor=provkor,
        )
    kept = saved[1] if saved is not None and saved[0] == current else None
    invalidated = saved is not None and saved[0] != current
    if kept is None:
        total = len(ways(model))
        message = (
            "Stationsmodellen har ändrats sedan Prova kördes: prova stationen igen."
            if invalidated
            else NOT_TRIED + "."
        )
        return TklProva(
            level=model.level,
            simulator=kind,
            total=total,
            invalidated=invalidated,
            message=message,
            provkor=provkor,
        )
    routes = failures_first(kept.routes)
    failed = sum(1 for r in routes if r.result == TklProvaResult.FAILED)
    if kept.tried:
        message = "Klart: varje väg gick igenom. Stationen kan öppnas i Ställverket."
    elif len(kept.routes) < kept.total:
        message = f"Prova avbröts efter {len(kept.routes)} av {kept.total} vägar."
    else:
        message = f"{failed} av {kept.total} vägar gick inte igenom."
    return TklProva(
        level=model.level,
        simulator=kept.simulator,
        done=len(kept.routes),
        total=kept.total,
        routes=routes,
        passed=len(routes) - failed,
        failed=failed,
        tried=kept.tried,
        started=kept.started,
        finished=kept.finished,
        message=message,
        provkor=provkor,
    )
