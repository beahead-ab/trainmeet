"""The station automats, the magazine and the remote routes in the station's own interlocking
(#36 del b, FR12, FR13, FR15, FR24–FR29, FR40, FR45).

Everything here lays and releases routes through the interlocking's own operations (lay_route,
free_route), with the same checks as on the spot: safety is checked in the station's own
interlocking alone (FR12). What is added is when to try, and who laid what.

A remote route (route.request) is a train route from the catalogue, tried as if the one who
controls the station had laid it on the spot: locked, or no with a reason: conflicting_route when
a set route stands in the way, area_released for a local area, track_occupied for a train in the
way, switch_not_in_control when a switch or a signal does not run at level 3, and route_refused
with the interlocking's own words otherwise. A cancelled route is released when the interlocking
allows, after its train.

The automats (FR24–FR27):

- A3, automatdrift, for the whole station; AN and AU, automatdrift on the down and up track, for
  their entry signals; A1, enstaka möte, for the next two trains from opposite ends; A2, enstaka
  förbigång, for the next two from the same end. A1 and A2 switch off by themselves once both
  trains have been laid out and their routes are released (FR26). There is one A3 per station.
- An automat lays a route when a train is on its way to the signal and the route can be locked
  (FR27): a train on its way in at a line end gets the route in to its track, and one standing on
  its track with its departure cleared gets the route out. Otherwise the train waits at the
  signal. AN, AU, A1 and A2 lay the route out only for the trains they took in; A3 for every one.
- Magasinering (FR45): a route an automat cannot lay because a set route stands in the way goes
  into the magazine. It is laid by itself once those routes are released, when the incoming train
  has reached its end, after MAGAZINE_DELAY seconds so that the train is wholly in.

The state at the overview level (route_state, FR13): every catalogue route the interlocking holds
set, with who laid it and the request it answered, also those laid on the spot; the automats that
are on and who switched them; the local areas; and at level 3 the occupied station tracks. Routes
stay until their train has gone, also when the station is taken back (FR15). While the station is
remote-controlled, also its parts' waiting requests and the list Klara att skicka (#36 del d,
DRIFT-40, FR50, FR51).

Pure Python without I/O. No code here names a station (RS13).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from contracts.common import Side
from contracts.reasons import Reason
from contracts.station import (
    AutomatOn,
    LocalArea,
    LockedRoute,
    PartRequest,
    ReadyToSend,
    RouteBy,
    RouteState,
)
from contracts.station_outside import AutomatKind, RemoteRoute, RouteDirection
from contracts.tkl import TklAutomatOn, TklAutomatSpec, TklMagazined
from tkl.stallverk.interlocking import WAITING, Interlocking, Outcome
from tkl.standard import RouteKind

MAGAZINE_DELAY: Final = 5.0
"""Seconds after the routes a magazined route waited for are released, before it is laid
(FR45): the incoming train is wholly in and nothing behind it is occupied."""
PAIRED: Final = frozenset({AutomatKind.A1, AutomatKind.A2})
"""The automats for one meeting or one passing, that switch off afterwards (FR26)."""
PRIORITY: Final = (AutomatKind.A1, AutomatKind.A2, AutomatKind.AN, AutomatKind.AU, AutomatKind.A3)
"""Which automat lays a route when several could: a meeting or a passing ordered while A3 is on
is done first, and then the station is back in automatdrift (TRVINFRA-00301)."""


@dataclass(frozen=True)
class Want:
    """A train that wants a catalogue route now (FR27): on its way in at a line end, or on its
    track with its departure cleared."""

    route: RemoteRoute
    call: str | None = None
    side: Side | None = None
    """The end of the station the train is at: for A1, from opposite ends; for A2, the same."""


@dataclass(frozen=True)
class Answer:
    """The interlocking's answer to a route asked for from afar (route.response)."""

    locked: bool
    reason: Reason | None
    message: str


# --- the remote routes -------------------------------------------------------------------------


def reason_of(it: Interlocking, route: RemoteRoute, said: str) -> Reason:
    """Why the interlocking said no, as one of the protocol's reasons (FR12)."""
    if it.conflicts(route.start, route.end):
        return Reason.CONFLICTING_ROUTE
    if "lokalt frigivet" in said:
        return Reason.AREA_RELEASED
    if "belagd" in said:
        return Reason.TRACK_OCCUPIED
    if "Koppla in" in said or "kan inte läggas om" in said or "läggs inte" in said:
        return Reason.SWITCH_NOT_IN_CONTROL
    return Reason.ROUTE_REFUSED


def _bringing_in(route: RemoteRoute, call: str | None) -> str | None:
    """The train a route in from the line is laid for, so that the station can release it when
    Hubben has the train's arrival (beslut 22 november). None for a route out."""
    return call if route.direction == RouteDirection.IN else None


def request(
    it: Interlocking, route: RemoteRoute, request_id: str, call: str | None = None
) -> Answer:
    """route.request: the route tried in the station's own interlocking as a train route laid
    by whoever controls the station (FR11, FR12), for the train asked for when there is one.
    Already set for this request: locked again."""
    held = next((r for r in it.routes if r.request_id == request_id), None)
    if held is not None:
        return Answer(True, None, f"Tågvägen {route.start} → {route.end} ligger redan.")
    outcome = it.lay_route(route.start, route.end, RouteKind.TRAIN)
    if outcome.accepted and outcome.route is not None:
        it.mark(
            outcome.route,
            route.id,
            RouteBy.REMOTE,
            request_id=request_id,
            call=_bringing_in(route, call),
        )
        return Answer(True, None, outcome.message)
    return Answer(False, reason_of(it, route, outcome.message), outcome.message)


def cancel(it: Interlocking, request_id: str) -> Outcome | None:
    """route.cancel: the route laid for the request is released when the interlocking allows,
    after its train; None when no such route is set (any more)."""
    held = next((r for r in it.routes if r.request_id == request_id), None)
    if held is None:
        return None
    first = held.chain if held.chain is not None else held.id
    return it.free_route(first)


# --- the automats ------------------------------------------------------------------------------


def _spec(specs: Sequence[TklAutomatSpec], code: str) -> TklAutomatSpec | None:
    return next((s for s in specs if s.code.casefold() == code.casefold()), None)


def set_automat(
    it: Interlocking, specs: Sequence[TklAutomatSpec], code: str, on: bool, by: RouteBy
) -> Outcome:
    """Koppla in eller ur en stationsautomat (FR25): on the spot, from afar or by itself after
    90 seconds without contact (FR29). A local release automat is the local area, switched with
    its function instead."""
    if (stale := it._refuse_stale()) is not None:
        return stale
    spec = _spec(specs, code)
    if spec is None or spec.kind == AutomatKind.LOCAL_RELEASE:
        return Outcome(False, f"Stationen har ingen stationsautomat {code}.")
    automats = list(it.fjarr.automats)
    found = next((a for a in automats if a.code == spec.code), None)
    if (found is not None) == on:
        return Outcome(True, f"{spec.code} är redan {'inkopplad' if on else 'urkopplad'}.")
    if on:
        automats.append(TklAutomatOn(code=spec.code, kind=spec.kind, by=by, since=it.now()))
        said = f"Stationsautomaten {spec.code} kopplades in"
    else:
        automats = [a for a in automats if a.code != spec.code]
        said = f"Stationsautomaten {spec.code} kopplades ur"
    magazine = [m for m in it.fjarr.magazine if on or m.automat != spec.code]
    it.fjarr = it.fjarr.model_copy(update={"automats": automats, "magazine": magazine})
    who = {RouteBy.REMOTE: " från fjärr", RouteBy.AUTOMAT: " av sig själv"}.get(by, "")
    return it._done(f"{said}{who}.")


def _takes(
    automat: TklAutomatOn, spec: TklAutomatSpec, want: Want, trains: dict[str, Side]
) -> bool:
    """Does this automat lay the train's route? (FR24, FR26)"""
    route, call = want.route, want.call
    if route.direction == RouteDirection.OUT:
        return automat.kind == AutomatKind.A3 or (call is not None and call in automat.trains)
    match automat.kind:
        case AutomatKind.A3:
            return True
        case AutomatKind.AN | AutomatKind.AU:
            return not spec.signals or route.start in spec.signals
        case AutomatKind.A1 | AutomatKind.A2:
            if call is None or call in automat.trains:
                return call is not None
            if len(automat.trains) >= 2:
                return False
            if not automat.trains:
                return True
            first = trains.get(automat.trains[0])
            if first is None or want.side is None:
                return True
            return (first != want.side) == (automat.kind == AutomatKind.A1)
        case _:
            return False


def _record(it: Interlocking, code: str, want: Want) -> None:
    """The automat has laid a train's route: in, or out."""
    if want.call is None:
        return
    automats = []
    for automat in it.fjarr.automats:
        if automat.code == code:
            field = "trains" if want.route.direction == RouteDirection.IN else "out"
            known = getattr(automat, field)
            if want.call not in known:
                automat = automat.model_copy(update={field: [*known, want.call]})
        automats.append(automat)
    it.fjarr = it.fjarr.model_copy(update={"automats": automats})


def tick(
    it: Interlocking,
    specs: Sequence[TklAutomatSpec],
    wants: Sequence[Want],
    sides: dict[str, Side] | None = None,
) -> list[str]:
    """One look by the automats that are on (FR24–FR27, FR45): what they laid and did, in
    words. `sides` remembers the end each train came from, for A1 and A2."""
    if it.problem is not None or not it.fjarr.automats:
        return []
    trains = dict(sides or {})
    for want in wants:
        if want.call is not None and want.side is not None and want.route.direction == "in":
            trains.setdefault(want.call, want.side)
    said: list[str] = []
    said += _paired_done(it)
    said += _magazine(it, wants)
    waiting = {(m.start, m.end) for m in it.fjarr.magazine}
    for want in wants:
        route = want.route
        if (route.start, route.end) in waiting or it.set_by(route.start, route.end) is not None:
            continue
        chosen = _chosen(it, specs, want, trains)
        if chosen is None:
            continue
        outcome = it.lay_route(route.start, route.end, RouteKind.TRAIN)
        if outcome.accepted and outcome.route is not None:
            call = _bringing_in(route, want.call)
            it.mark(outcome.route, route.id, RouteBy.AUTOMAT, automat=chosen.code, call=call)
            _record(it, chosen.code, want)
            said.append(f"{chosen.code}: {outcome.message}")
            continue
        blocked = it.conflicts(route.start, route.end)
        if blocked:
            # Magasinering (FR45): laid by itself when what stands in the way is released.
            kept = TklMagazined(
                route=route.id,
                start=route.start,
                end=route.end,
                automat=chosen.code,
                call=want.call,
                since=it.now(),
                blocked_by=blocked,
            )
            it.fjarr = it.fjarr.model_copy(update={"magazine": [*it.fjarr.magazine, kept]})
            waiting.add((route.start, route.end))
            said.append(
                it._done(f"{chosen.code}: {route.start} → {route.end} magasinerad.").message
            )
    return said


def _chosen(
    it: Interlocking, specs: Sequence[TklAutomatSpec], want: Want, trains: dict[str, Side]
) -> TklAutomatOn | None:
    """The automat that lays the train's route, in PRIORITY's order, or None."""
    on = sorted(
        it.fjarr.automats, key=lambda a: PRIORITY.index(a.kind) if a.kind in PRIORITY else 9
    )
    for automat in on:
        spec = _spec(specs, automat.code)
        if spec is not None and _takes(automat, spec, want, trains):
            return automat
    return None


def _magazine(it: Interlocking, wants: Sequence[Want]) -> list[str]:
    """The magazine (FR45): a route whose blockers are released is laid after the delay; one no
    train wants any more is dropped."""
    wanted = {(w.route.start, w.route.end): w for w in wants}
    set_ids = {r.id for r in it.routes}
    now = it.now()
    kept: list[TklMagazined] = []
    said: list[str] = []
    changed = False
    for entry in it.fjarr.magazine:
        want = wanted.get((entry.start, entry.end))
        if want is None:
            changed = True
            continue
        alive = [b for b in entry.blocked_by if b in set_ids]
        if alive:
            if entry.free_since is not None or alive != entry.blocked_by:
                entry = entry.model_copy(update={"blocked_by": alive, "free_since": None})
                changed = True
            kept.append(entry)
            continue
        if entry.free_since is None:
            kept.append(entry.model_copy(update={"blocked_by": [], "free_since": now}))
            changed = True
            continue
        if (now - entry.free_since).total_seconds() < MAGAZINE_DELAY:
            kept.append(entry)
            continue
        outcome = it.lay_route(entry.start, entry.end, RouteKind.TRAIN)
        if outcome.accepted and outcome.route is not None:
            call = _bringing_in(want.route, want.call)
            it.mark(outcome.route, entry.route, RouteBy.AUTOMAT, automat=entry.automat, call=call)
            _record(it, entry.automat, want)
            said.append(f"{entry.automat}: ur magasinet: {outcome.message}")
            changed = True
            continue
        blocked = it.conflicts(entry.start, entry.end)
        if blocked != entry.blocked_by:
            entry = entry.model_copy(update={"blocked_by": blocked, "free_since": None})
            changed = True
        kept.append(entry)
    if changed:
        it.fjarr = it.fjarr.model_copy(update={"magazine": kept})
        it.revision += 1
    return said


def _paired_done(it: Interlocking) -> list[str]:
    """A1 and A2 switch off by themselves once both trains are laid out and their routes are
    released: the meeting or the passing is over (FR26)."""
    laid_by = {r.automat for r in it.routes if r.automat is not None}
    said = []
    for automat in list(it.fjarr.automats):
        if automat.kind not in PAIRED or len(automat.out) < 2 or automat.code in laid_by:
            continue
        rest = [a for a in it.fjarr.automats if a.code != automat.code]
        it.fjarr = it.fjarr.model_copy(update={"automats": rest})
        done = "mötet" if automat.kind == AutomatKind.A1 else "förbigången"
        said.append(it._done(f"{automat.code} kopplades ur av sig själv efter {done}.").message)
    return said


# --- the state at the overview level -----------------------------------------------------------


def route_state(
    it: Interlocking,
    catalogue: Sequence[RemoteRoute],
    specs: Sequence[TklAutomatSpec],
) -> RouteState:
    """route.state (FR13): the catalogue routes the interlocking holds set and who laid them,
    the automats that are on, the local areas and, at level 3, the occupied station tracks; and
    the station tracks where the interlocking cannot see a train come in, where the driver's
    Framme counts as the arrival (beslut 22 november)."""
    routes = {r.id: r for r in it.routes}
    locked = []
    for route in catalogue:
        first = it.set_by(route.start, route.end)
        if first is None:
            continue
        shown = routes[first]
        locked.append(
            LockedRoute(
                route=route.id,
                by=shown.by or RouteBy.STATION,
                request_id=shown.request_id,
                automat=shown.automat,
            )
        )
    areas = []
    for spec in specs:
        if spec.kind != AutomatKind.LOCAL_RELEASE or spec.function is None:
            continue
        if it.on.get(spec.function):
            areas.append(LocalArea(code=spec.code, tracks=it.area_tracks(spec.function)))
    requests, ready = forwarded(it)
    return RouteState(
        locked=locked,
        automats=[AutomatOn(code=a.code, by=a.by) for a in it.fjarr.automats],
        local_areas=areas,
        occupied=it.occupied_tracks() if it.level == 3 else [],
        unseen=it.unseen_tracks(),
        part_requests=requests,
        ready_to_send=ready,
    )


def forwarded(it: Interlocking) -> tuple[list[PartRequest], list[ReadyToSend]]:
    """What the station forwards of its parts while it is remote-controlled (DRIFT-40, FR50,
    FR51, TKL100): the requests that wait for an answer, the oldest first, and the list Klara att
    skicka in the station's order. Nothing while the station is manned: the clearer answers in
    its own box then."""
    if it.fjarr.controller is None:
        return [], []
    requests = []
    for part_id, state in it.parts.items():
        part = it.plant.parts[part_id]
        for asked in state.requests:
            if asked.state != WAITING:
                continue
            requests.append(
                (
                    asked.asked,
                    PartRequest(
                        request_id=str(asked.id),
                        part=part.id,
                        part_name=part.name,
                        said=asked.said,
                        text=f"{part.name} begär {asked.said}.",
                    ),
                )
            )
    ready = [
        ReadyToSend(
            train_number=r.number,
            call=r.call,
            part=r.part,
            part_name=r.part_name,
            departure=r.departure,
            track=r.track,
            moved=r.moved,
        )
        for r in it.ready
    ]
    return [r for _, r in sorted(requests, key=lambda found: found[0])], ready


def local_function(specs: Sequence[TklAutomatSpec], code: str) -> str | None:
    """The local release function behind a code (FR39)."""
    spec = _spec(specs, code)
    if spec is None or spec.kind != AutomatKind.LOCAL_RELEASE:
        return None
    return spec.function


def default_automat(specs: Sequence[TklAutomatSpec]) -> TklAutomatSpec | None:
    """The automat the station switches on itself after 90 seconds without contact (FR29)."""
    return next((s for s in specs if s.default and s.kind != AutomatKind.LOCAL_RELEASE), None)
