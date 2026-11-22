"""Fjärrstyrning, the station's side towards Hubben (#36 del b, FR12–FR15, FR20–FR29, FR42).

The station's own TKL answers for its station, and only for it: it reads its place's snapshot,
never another place's, so two TKLs on one Hubben each answer for their own station. A look
(`StationRemote.step`), every STEP_SECONDS while TKL is connected and approved, and at once when
the web app asks:

1. Who controls the station, as Hubben says it: while it is remote-controlled, the station's own
   panel lays nothing (FR6, FR17), and its name shows "Fjärrstyrs från …".
2. Every route asked for (`remote.routes` in requested) is tried in the station's own
   interlocking as a train route laid by the controller, and answered with route.response within
   Hubben's ten seconds (FR12, FR14): locked, or no with a reason and the interlocking's words.
   While the controller has not been heard for 45 seconds, no new route is laid (FR28).
3. A cancelled route is released when the interlocking allows, after its train. A train Hubben
   says has arrived, by the driver's Framme or the controller's Ankommit, has the routes laid
   to bring it in released where the interlocking cannot see the passage itself (beslut 22
   november); route.state says on which tracks that is (`unseen`).
4. What the controller decided for the automats and the local areas (`remote.automats_asked`)
   is switched: an automat at once, a local area in when no route goes to, from or through it
   (FR42) and out when it is empty (FR23).
5. What the controller answered the parts (`remote.part_answers`) and did with the list Klara
   att skicka (`remote.ready_asks`) is done as the clearer's Godkänn, Neka, move and Skickat in
   the box, once each, written in the events with the controller's name (FR50, FR51, TKL100).
   The station says so in route.state's `answered`; an approval the interlocking cannot lay yet
   leaves the request waiting with the interlocking's words in its `note`.
6. After 90 seconds without contact with the controller, the default automat is switched on, by
   the automat itself (FR29).
7. The automats lay what the trains want (tkl.stallverk.automats): a train on its way in at a line
   end wants the route in to its track; one on its track with its departure cleared wants the
   route out.
8. route.state goes up whole whenever it differs from what Hubben keeps (FR13). While the station
   is remote-controlled it carries the parts' waiting requests and the list Klara att skicka
   (DRIFT-40); a part's request or Klart att skicka goes up at once (`soon`, from TKL's
   `forward`), not at the next look.

The catalogue and the automats are those of the outside TKL connected with, and the owner's
choice that went with that version. A station with neither has nothing to report, as at level 0
(FR16). The key stays in the server (H31).

No code here names a station (RS13).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final
from uuid import uuid4

from contracts import station
from contracts.reasons import Reason
from contracts.station_model import StationModel
from contracts.station_outside import RemoteRoute, RouteDirection, StationOutside
from contracts.tkl import TklAutomatSpec, TklFjarrChoice, TklInterlocking, TklReport
from tkl.hub_client import HubClient, HubError, Unreachable
from tkl.stallverk import Interlocking, load, plant_of
from tkl.stallverk import automats as automat
from tkl.stallverk.interlocking import Order
from tkl.store import Connection, TklStore
from tkl.studio.fjarr import automats_of

STEP_SECONDS: Final = 2.0
"""How often the station looks: well within the ten seconds Hubben gives it to answer (FR14)."""
SILENT_NO_ROUTES: Final = 45
"""Seconds without the controller after which no new remote route is laid (FR28)."""
SILENT_DEFAULT: Final = 90
"""Seconds without the controller after which the default automat is switched on (FR29)."""
LOGGER = logging.getLogger("tkl.fjarr")


@dataclass(frozen=True)
class Setup:
    """What the station answers with: the catalogue, the automats and the exits' sides."""

    catalogue: list[RemoteRoute]
    specs: list[TklAutomatSpec]
    outside: StationOutside

    @property
    def empty(self) -> bool:
        return not self.catalogue and not self.specs


@dataclass
class Looked:
    """What one look did, for the tests and the log."""

    answered: list[station.RouteResponse] = field(default_factory=list)
    sent_state: station.RouteState | None = None
    said: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    reports: list[TklReport] = field(default_factory=list)
    """The exit signals that changed, to go up as signal.exit (STV-10)."""
    done: list[int] = field(default_factory=list)
    """The controller's answers to the parts and the list done now, by Hubben's seq (FR50)."""
    notes: dict[str, str] = field(default_factory=dict)
    """Why an approval could not be laid yet, by the request it was for (FR50)."""


def setup_of(store: TklStore, found: str, made: Connection, model: StationModel) -> Setup | None:
    """The catalogue and the automats of the outside TKL connected with (#36 del b)."""
    outside = store.outside_of_version(found, made.outside_version)
    if outside is None:
        return None
    settings = store.fjarr_of_version(found, made.outside_version) or store.fjarr(found)
    known = {a.code for a in outside.automats}
    specs = [s for s in automats_of(model, settings or TklFjarrChoice()) if s.code in known]
    return Setup(list(outside.remote_routes), specs, outside)


def _track(outside: StationOutside, name: str | None) -> str | None:
    """A track as the plan or Hubben names it, by its id in the outside."""
    if not name:
        return None
    for track in outside.tracks:
        if name in (track.id, track.label, f"Spår {track.id}") or track.label == f"Spår {name}":
            return track.id
    return None


def wants_of(snapshot: station.Snapshot, setup: Setup) -> list[automat.Want]:
    """What the trains at the station want now (FR27): a train on its way in at a line end
    wants the route in to its track; one on its track with its departure cleared, the route out
    to the line its clearance is for."""
    sides = {e.id: e.side for e in setup.outside.exits}
    exits = {s.section: s.exit for s in snapshot.sections}
    calls = {c.call: c for c in snapshot.calls}
    found: list[automat.Want] = []

    def route(direction: RouteDirection, exit_id: str | None, track: str | None) -> RemoteRoute:
        return next(
            r
            for r in setup.catalogue
            if r.direction == direction and r.exit == exit_id and r.track == track
        )

    for coming in snapshot.on_the_way:
        exit_id = exits.get(coming.section)
        call = calls.get(coming.call)
        track = _track(setup.outside, (call.track if call else None) or coming.planned_track)
        try:
            chosen = route(RouteDirection.IN, exit_id, track)
        except StopIteration:
            continue
        found.append(automat.Want(chosen, coming.call, sides.get(exit_id or "")))
    for call in snapshot.calls:
        if call.departure_state != station.DepartureState.CLEARED:
            continue
        if call.arrival_state == station.ArrivalState.ON_THE_WAY:
            continue
        cleared = next(
            (
                c
                for c in snapshot.clearances
                if c.call == call.call
                and c.from_place == snapshot.place.place
                and c.status == station.ClearanceStatus.APPROVED
                and not c.departed
            ),
            None,
        )
        if cleared is None:
            continue
        exit_id = exits.get(cleared.section)
        track = _track(setup.outside, call.track or call.planned_track)
        try:
            chosen = route(RouteDirection.OUT, exit_id, track)
        except StopIteration:
            continue
        found.append(automat.Want(chosen, call.call, sides.get(exit_id or "")))
    return found


def answer_parts(
    it: Interlocking, remote: station.RemoteHere, done: set[int], looked: Looked
) -> None:
    """Step 5: the controller's answers to the parts' requests and its changes to the list Klara
    att skicka, each once, as the clearer's in the box (FR50, FR51, TKL100). done: the answers
    already done, which Hubben still lists until it has the route.state that says so."""
    for answer in remote.part_answers:
        if answer.seq in done:
            continue
        looked.done.append(answer.seq)
        try:
            request = int(answer.request_id)
        except ValueError:
            continue
        reason = answer.reason if not answer.approve else None
        outcome = it.remote_reply(request, answer.approve, answer.by, reason)
        (looked.said if outcome.accepted else looked.refused).append(outcome.message)
        if answer.approve and not outcome.accepted:
            looked.notes[answer.request_id] = outcome.message
    for asked in remote.ready_asks:
        if asked.seq in done:
            continue
        looked.done.append(asked.seq)
        if asked.to is None:
            outcome = it.ready_sent(asked.train_number, by=asked.by)
        else:
            outcome = it.ready_move(asked.train_number, asked.to, by=asked.by)
        (looked.said if outcome.accepted else looked.refused).append(outcome.message)


def look(
    it: Interlocking,
    snapshot: station.Snapshot,
    setup: Setup,
    done: set[int] | None = None,
) -> Looked:
    """One look at the station's interlocking, as the snapshot says how things stand: steps 1–7
    of the module's list. The caller keeps the state, sends the answers and the route.state.
    done: the controller's answers to the parts already done (step 5)."""
    remote = snapshot.remote
    controller = remote.controller.name if remote.controller is not None else None
    looked = Looked()
    before = it.exit_aspects()
    it.set_remote(controller)
    silent = remote.controller_silent if controller is not None else None
    by_id = {r.id: r for r in setup.catalogue}
    for asked in remote.routes:
        if asked.state != station.RemoteRouteState.REQUESTED:
            continue
        route = by_id.get(asked.route)
        if route is None:
            answer = automat.Answer(False, Reason.NOT_IN_CATALOG, "")
        elif silent is not None and silent >= SILENT_NO_ROUTES:
            answer = automat.Answer(False, Reason.NO_CONTACT, "")
        else:
            answer = automat.request(it, route, asked.request_id, asked.call)
        looked.answered.append(
            station.RouteResponse(
                request_id=asked.request_id,
                locked=answer.locked,
                reason=answer.reason,
                message=(answer.message or None) if not answer.locked else None,
            )
        )
    for asked in remote.routes:
        if asked.state == station.RemoteRouteState.CANCELLED:
            cancelled = automat.cancel(it, asked.request_id)
            if cancelled is not None and not cancelled.accepted:
                looked.refused.append(cancelled.message)
    for call in snapshot.calls:
        if call.arrival_state != station.ArrivalState.ARRIVED:
            continue
        arrived = it.hub_arrival(call.call, call.train_number)
        if arrived is not None:
            (looked.said if arrived.accepted else looked.refused).append(arrived.message)
    for switched in remote.automats_asked:
        function = automat.local_function(setup.specs, switched.code)
        if function is not None:
            done_now = it.switch_local(function, switched.on, empty=not switched.on)
        else:
            done_now = automat.set_automat(
                it, setup.specs, switched.code, switched.on, station.RouteBy.REMOTE
            )
        (looked.said if done_now.accepted else looked.refused).append(done_now.message)
    if controller is not None:
        answer_parts(it, remote, done or set(), looked)
    default = automat.default_automat(setup.specs)
    lost = silent is not None and silent >= SILENT_DEFAULT
    if lost and default is not None and all(a.code != default.code for a in it.fjarr.automats):
        on = automat.set_automat(it, setup.specs, default.code, True, station.RouteBy.AUTOMAT)
        looked.said.append(on.message)
    looked.said += automat.tick(it, setup.specs, wants_of(snapshot, setup))
    if it.problem is None:
        looked.reports = list(it._exit_reports(before))
    return looked


class StationRemote:
    """The station's TKL towards Hubben for remote control, for every station TKL keeps."""

    def __init__(
        self,
        store: TklStore,
        hub: Callable[[Connection], HubClient],
        home: Callable[[str], tuple[Connection, str] | str],
        report: Callable[[str, list[TklReport]], list[TklReport]] | None = None,
        orders: Callable[[list[Order]], None] | None = None,
    ) -> None:
        self.store = store
        self.hub = hub
        self.home = home
        self.report = report
        self.orders = orders
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._done: dict[str, set[int]] = {}
        """The controller's answers to the parts done, per station, until Hubben drops them."""
        self._notes: dict[str, dict[str, str]] = {}
        """Why an approval could not be laid yet, per station and request (FR50)."""
        self._soon: set[str] = set()
        self._again: set[str] = set()
        self._soon_lock = threading.Lock()

    def step(self, found: str) -> Looked | None:
        """One look for the station: None when there is nothing to look at (not connected, no
        model, no catalogue or automats, no contact)."""
        with self._lock:
            return self._step(found)

    def _step(self, found: str) -> Looked | None:
        # Nothing to answer for, nothing asked of Hubben: no key, no model, no catalogue.
        kept = self.store.connection(found)
        model, _, _ = self.store.interlocking(found)
        if kept is None or kept.key is None or model is None:
            return None
        setup = setup_of(self.store, found, kept, model)
        if setup is None or setup.empty:
            return None
        reached = self.home(found)
        if isinstance(reached, str):
            return None
        made, place = reached
        hub = self.hub(made)
        try:
            snapshot = hub.snapshot(place)
        except (Unreachable, HubError):
            return None
        plant = plant_of(model)
        pending = {a.seq for a in snapshot.remote.part_answers}
        pending |= {a.seq for a in snapshot.remote.ready_asks}
        done = self._done.setdefault(found, set())
        done &= pending

        def change(
            kept_model: StationModel | None, revision: int, body: str | None
        ) -> tuple[TklInterlocking | None, tuple[Looked, station.RouteState, list[Order]]]:
            if kept_model is None:
                return None, (Looked(), station.RouteState(), [])
            it = load(plant, revision, body)
            looked = look(it, snapshot, setup, done)
            state = automat.route_state(it, setup.catalogue, setup.specs)
            orders = it.take_orders()
            kept = it.view() if it.revision != revision else None
            return kept, (looked, state, orders)

        looked, state, orders = self.store.change_interlocking(found, change)
        done |= set(looked.done)
        state = self._answered(found, state, looked, done & pending)
        if orders and self.orders is not None:
            self.orders(orders)
        if looked.reports and self.report is not None:
            looked.reports = self.report(found, looked.reports)
        for answer in looked.answered:
            self._send(hub, made, snapshot, place, station.Action.ROUTE_RESPONSE, answer)
        hub_state = snapshot.remote.route_state or station.RouteState()
        sent = state != hub_state and self._send(
            hub, made, snapshot, place, station.Action.ROUTE_STATE, state
        )
        if sent:
            looked.sent_state = state
        for line in looked.said:
            LOGGER.info("Fjärrstyrning: %s", line)
        return looked

    def _answered(
        self, found: str, state: station.RouteState, looked: Looked, done: set[int]
    ) -> station.RouteState:
        """route.state with what the station has done of the controller's answers (FR50): their
        seqs while Hubben still lists them, and why an approval waits, on its request."""
        notes = self._notes.setdefault(found, {})
        notes.update(looked.notes)
        waiting = {r.request_id for r in state.part_requests}
        for gone in set(notes) - waiting:
            del notes[gone]
        requests = [
            r.model_copy(update={"note": notes[r.request_id]}) if r.request_id in notes else r
            for r in state.part_requests
        ]
        return state.model_copy(update={"part_requests": requests, "answered": sorted(done)})

    def soon(self, found: str) -> None:
        """A look for the station at once, in the background: a part's request or Klart att
        skicka goes up to whoever controls the station without waiting for the next look
        (TKL100). Several asks while one runs give one more look."""
        with self._soon_lock:
            if found in self._soon:
                self._again.add(found)
                return
            self._soon.add(found)

        def run() -> None:
            while True:
                try:
                    self.step(found)
                except Exception:  # the next look tries again
                    LOGGER.exception("Fjärrstyrning: en titt gick fel.")
                with self._soon_lock:
                    if found not in self._again:
                        self._soon.discard(found)
                        return
                    self._again.discard(found)

        threading.Thread(target=run, name="tkl-fjarr-nu", daemon=True).start()

    @staticmethod
    def _send(
        hub: HubClient,
        made: Connection,
        snapshot: station.Snapshot,
        place: str,
        action: station.Action,
        payload: station.RouteResponse | station.RouteState,
    ) -> bool:
        command = station.Command(
            message_id=f"tkl-{uuid4().hex}",
            client_id=made.client_id,
            place=place,
            context=snapshot.context,
            action=action,
            payload=payload.model_dump(mode="json", exclude_none=True),
        )
        try:
            reply = hub.command(command)
        except (Unreachable, HubError):
            return False
        if reply.status == station.ReplyStatus.REJECTED:
            LOGGER.info("Fjärrstyrning: Hubben sa nej till %s: %s", action.value, reply.message)
            return False
        return True

    # --- in the background ------------------------------------------------------------------

    def start(self, slots: Callable[[], Sequence[str]]) -> None:
        """Look for every connected station every STEP_SECONDS, until stop."""
        if self._thread is not None:
            return
        self._stop.clear()

        def run() -> None:
            while not self._stop.wait(STEP_SECONDS):
                for found in slots():
                    try:
                        self.step(found)
                    except Exception:  # the loop goes on for the other stations
                        LOGGER.exception("Fjärrstyrning: en titt gick fel.")

        self._thread = threading.Thread(target=run, name="tkl-fjarr", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
