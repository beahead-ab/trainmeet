"""Studio's checks of a deck's profile (#86 del c, SD44): every train route and shunting route is
reached from some page, and no key points at something that does not exist.

A route is reached from the deck:

- with its snabbväg, a key that sets exactly that route (SD42);
- with its start, a signal key or a square of Spårplan's cut-out: the goals stand on the page or
  in the list of goals, so that a start and a goal set it (the prototype's rule 5, SD71);
- for a train route, with the places it runs between, where both are on the deck (SD66, SD67).

A page is reached when it is listed among Sidor, or a part's key on a reached page opens it
(SD79). The pages Nu, Dagens vägar and Favoriter follow the traffic and are not counted.

The default reaches every route (del a tried that for the four reference stations); the owner's
changes may not, and then Studio says which route and why, clickable.

The shunter's deck, Bangård (#87 del d), is checked against its part instead: every switch street
to a track of the yard and every route out is reached, with a key for its track from its end, a
key that follows Ände where the deck has Ände, or a dial (SD87). A load track or the depot, with
a street from one end only, is laid on the screen where the deck has no room for it (SD61).

Pure Python without I/O. No code here names a station (RS13).
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.station_model import PartSide
from contracts.tkl import (
    DeckAction,
    DeckDial,
    DeckKeyType,
    DeckMode,
    DeckPageKind,
    DeckProblemKind,
    RouteKind,
    TklDeckChecks,
    TklDeckProblem,
    TklDeckProfile,
    TklDeckRoute,
)
from tkl.deck.deviations import ARROW, Known, cap, describe
from tkl.deck.places import Geography
from tkl.deck.profile import yard_tracks
from tkl.stallverk import Plant
from tkl.standard import RouteKind as EngineKind

K = DeckKeyType
WORD = {RouteKind.TRAIN: "Tågvägen", RouteKind.SHUNTING: "Växlingsvägen"}


@dataclass(frozen=True)
class Reach:
    """What the deck reaches: its starts, its places and its snabbvägar, and on which page."""

    pages: frozenset[int]
    starts: dict[str, int]
    places: dict[str, int]
    quick: dict[tuple[RouteKind, str, str], int]
    cutout: int | None


def reached_pages(profile: TklDeckProfile) -> frozenset[int]:
    """The listed pages, and the pages a part's key on a reached page opens (SD79), or Begär on
    the shunter's Mini (SD87)."""
    found = {i for i, p in enumerate(profile.pages) if p.listed}
    todo = list(found)
    while todo:
        page = profile.pages[todo.pop()]
        for key in page.keys:
            opens = key is not None and (
                key.type == K.PART or (key.type == K.ACTION and key.action == DeckAction.REQUESTS)
            )
            target = key.page if key is not None and opens else None
            if target is not None and target < len(profile.pages) and target not in found:
                found.add(target)
                todo.append(target)
    return frozenset(found)


def reach(profile: TklDeckProfile) -> Reach:
    pages = reached_pages(profile)
    starts: dict[str, int] = {}
    places: dict[str, int] = {}
    quick: dict[tuple[RouteKind, str, str], int] = {}
    cutout = None
    for i in sorted(pages):
        page = profile.pages[i]
        if page.kind == DeckPageKind.CUTOUT and cutout is None:
            cutout = i
        for key in page.keys:
            if key is None:
                continue
            if key.type == K.SIGNAL and key.point:
                starts.setdefault(key.point, i)
            elif key.type in (K.PLACE, K.TRACK) and key.place:
                places.setdefault(key.place, i)
            elif key.type == K.ROUTE and key.route is not None:
                r = key.route
                quick.setdefault((r.kind, r.start, r.end), i)
    for key in profile.pedals:
        if key is not None and key.type == K.ROUTE and key.route is not None:
            r = key.route
            quick.setdefault((r.kind, r.start, r.end), 0)
    if cutout is not None:
        for point in profile.points:
            if point.start:
                starts.setdefault(point.name, cutout)
    return Reach(pages, starts, places, quick, cutout)


def routes_of(plant: Plant) -> list[TklDeckRoute]:
    """Every route of the station, once per kind, start and goal: train routes first."""
    found = [
        TklDeckRoute(start=w.start, end=w.end, kind=RouteKind(w.kind.value))
        for w in plant.preferred()
    ]
    return sorted(found, key=lambda r: (r.kind != RouteKind.TRAIN, r.start, r.end))


def how(route: TklDeckRoute, found: Reach, plant: Plant, geo: Geography) -> tuple[str, int] | None:
    """How the deck reaches a route, and on which page; None when it does not."""
    at = found.quick.get((route.kind, route.start, route.end))
    if at is not None:
        return "snabbväg", at
    start = found.starts.get(route.start)
    if start is not None and route.end in plant.ends(EngineKind(route.kind.value), route.start):
        return "start och mål", start
    if route.kind == RouteKind.TRAIN:
        origin = found.places.get(geo.start_place.get(route.start, ""))
        goal = found.places.get(geo.end_place.get(route.end, ""))
        if origin is not None and goal is not None:
            return "platser", origin
    return None


def check(profile: TklDeckProfile, plant: Plant, geo: Geography, known: Known) -> TklDeckChecks:
    """SD44 for one size: the routes the deck reaches, its snabbvägar, and the problems."""
    if profile.part is not None:
        return yard_check(profile, plant, known)
    found = reach(profile)
    routes = routes_of(plant)
    problems: list[TklDeckProblem] = []
    reached = 0
    quick = 0
    pedal = profile.grid.columns * profile.grid.rows == 0
    for route in routes:
        if (route.kind, route.start, route.end) in found.quick:
            quick += 1
        if how(route, found, plant, geo) is not None:
            reached += 1
        elif not pedal:
            problems.append(
                TklDeckProblem(
                    kind=DeckProblemKind.UNREACHED,
                    text=f"{WORD[route.kind]} {route.start} {ARROW} {route.end} nås inte från "
                    "decket.",
                    route=route,
                )
            )
    problems += missing_keys(profile, known)
    return TklDeckChecks(routes=len(routes), reached=reached, quick=quick, problems=problems)


def missing_keys(profile: TklDeckProfile, known: Known) -> list[TklDeckProblem]:
    """The keys that point at something the station does not have."""
    problems: list[TklDeckProblem] = []
    for i, page in enumerate(profile.pages):
        for cell, key in enumerate(page.keys):
            missing = known.has(key) if key is not None else None
            if key is not None and key.type == K.PART:
                target = key.page
                if target is None or target >= len(profile.pages):
                    missing = missing or "Delens sida finns inte."
            if missing:
                problems.append(
                    TklDeckProblem(
                        kind=DeckProblemKind.MISSING,
                        text=f"{cap(describe(key))} på sidan {page.name}: {missing}",
                        page=i,
                        cell=cell,
                        route=key.route if key is not None else None,
                    )
                )
    for n, key in enumerate(profile.pedals):
        missing = known.has(key) if key is not None else None
        if missing:
            problems.append(
                TklDeckProblem(
                    kind=DeckProblemKind.MISSING,
                    text=f"Pedal {n + 1}: {missing}",
                    route=key.route if key is not None else None,
                )
            )
    return problems


# --- Bangård (#87 del d) --------------------------------------------------------------------


@dataclass(frozen=True)
class YardReach:
    """What the shunter's deck reaches: its keys by type, track and end, whether it has Ände,
    and its dials."""

    keys: frozenset[tuple[DeckKeyType, str, PartSide | None]]
    end: bool
    dials: frozenset[DeckDial]

    def has(self, kind: DeckKeyType, track: str, side: PartSide | None) -> bool:
        """A street or a route out to a track from an end (None: both)."""
        if kind == K.REQUEST and DeckDial.REQUEST in self.dials and (self.end or side != RIGHT):
            return True
        if kind == K.STREET and DeckDial.STREET in self.dials and (self.end or side != RIGHT):
            return True
        for k, t, s in self.keys:
            if k != kind or t != track:
                continue
            if side is None or s == side or (s is None and (self.end or side == LEFT)):
                return True
        return False


LEFT = PartSide.LEFT
RIGHT = PartSide.RIGHT


def yard_reach(profile: TklDeckProfile) -> YardReach:
    keys: set[tuple[DeckKeyType, str, PartSide | None]] = set()
    end = False
    for i in reached_pages(profile):
        for key in profile.pages[i].keys:
            if key is None:
                continue
            if key.type == K.END:
                end = True
            elif key.type in (K.STREET, K.REQUEST) and key.track:
                keys.add((key.type, key.track, key.side))
    return YardReach(frozenset(keys), end, frozenset(profile.dials.get(DeckMode.YARD, [])))


def yard_check(profile: TklDeckProfile, plant: Plant, known: Known) -> TklDeckChecks:
    """SD44 for the shunter's deck: every street to a track of the yard and every route out is
    reached (SD61, SD87). The load tracks and the depot are laid on the screen."""
    part = plant.parts.get(profile.part or "")
    problems: list[TklDeckProblem] = []
    pedal = profile.grid.columns * profile.grid.rows == 0
    if part is None:
        if not pedal:
            problems.append(
                TklDeckProblem(
                    kind=DeckProblemKind.MISSING,
                    text=f"Delen {profile.part} finns inte i stationsmodellen.",
                )
            )
        return TklDeckChecks(routes=0, reached=0, problems=problems)
    through = {t.track for t in yard_tracks(part.streets.values()) if t.through}
    found = yard_reach(profile)
    total = 0
    reached = 0
    for street in part.streets.values():
        if street.track not in through:
            continue
        total += 1
        if found.has(K.STREET, street.track, street.side):
            reached += 1
        elif not pedal:
            problems.append(
                TklDeckProblem(
                    kind=DeckProblemKind.UNREACHED,
                    text=f"Växelgatan {street.name} till {street.track} nås inte från decket.",
                )
            )
    for out in part.routes_out.values():
        total += 1
        if found.has(K.REQUEST, out.track, out.side):
            reached += 1
        elif not pedal:
            problems.append(
                TklDeckProblem(
                    kind=DeckProblemKind.UNREACHED,
                    text=f"Vägen ut {out.name} ({out.start} {ARROW} {out.end}) nås inte från "
                    "decket.",
                    route=TklDeckRoute(start=out.start, end=out.end, kind=RouteKind.SHUNTING),
                )
            )
    problems += missing_keys(profile, known)
    return TklDeckChecks(routes=total, reached=reached, problems=problems)


__all__ = [
    "Reach",
    "YardReach",
    "check",
    "how",
    "reach",
    "reached_pages",
    "routes_of",
    "yard_check",
    "yard_reach",
]
