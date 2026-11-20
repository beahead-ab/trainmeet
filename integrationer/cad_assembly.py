"""CAD:s anläggning som underlag (K4, CAD-11, CAD-12, IMPORT-10): the cloud hub asks TrainMeet CAD
for the planner's assemblies, and reads one into the places and the tracks between them.

The client calls CAD with the planner's own access token from TrainMeet ID for the client hub
(#78): CAD shows the assemblies and modules the person sees, and nothing else. What CAD answers
(trainmeet.cad-assembly/1, contracts/cad.py) is kept as it came, with its checksum, so that the
same assembly always gives the same draft (IMPORT-15), and it goes with the meet's versions to
the Pi (CAD-12).

The reading, without I/O. The assembly's track graph is in its own mm, with every id prefixed by
its module's id, and one node where two modules' tracks meet (CAD-10):

- A place is a group of modules joined to each other that have a switch or are used by a
  station in TKL (Används i, CAD-15). Two such modules used by different stations are two
  places. Its name is the station's, else its modules'; it stands at the middle of its tracks.
- A link is the tracks between two places through modules without switches (the line): its
  length is the length along the track, from where the tracks leave one place's modules to where
  they reach the other's, the mean over the tracks side by side. Two places joined directly have
  a link of length 0.
- Through a place from one link to another, the shortest way along its tracks, where a switch
  is taken only from its trunk to one of its legs.

Lengths are in the model's mm; the prototype's are the model's times the scale (87 for H0).
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from contracts.cad import (
    ArcSegment,
    AssemblyBrief,
    GraphPiece,
    GraphSwitch,
    MeetAssembly,
    MeetModule,
    Segment,
)
from contracts.meet import MapPoint
from contracts.planning import (
    AssemblyLayout,
    AssemblyLink,
    AssemblyPlace,
    AssemblyThrough,
)
from contracts.station_model import SwitchType

LEVEL: Final = 2  # like the track picture: the assembly can be used instead of it (K4)
MAX_BYTES: Final = 40 * 1024 * 1024
TIMEOUT: Final = 30.0
MEDIA_TYPE: Final = "application/json"
RATIO: Final = {"H0": 87.0, "N": 160.0, "0": 45.0}
"""The scales' ratios, for the prototype's length."""

_BRIEFS: Final = TypeAdapter(list[AssemblyBrief])


class CadError(Exception):
    """CAD said no or did not answer, with what to tell the planner."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class AssemblyError(Exception):
    """The assembly cannot be read."""


# --- The client ---------------------------------------------------------------------------


class CadClient:
    """TrainMeet CAD as the cloud hub reaches it (HUB_CAD), with the planner's token."""

    def __init__(self, address: str, http: httpx.Client | None = None) -> None:
        self.address = address.rstrip("/")
        self.http = http or httpx.Client(timeout=TIMEOUT, follow_redirects=False)

    def _get(self, path: str, token: str) -> bytes:
        try:
            with self.http.stream(
                "GET",
                f"{self.address}/api/cad/1/meet{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": MEDIA_TYPE},
            ) as answer:
                body = bytearray()
                for chunk in answer.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise CadError("Anläggningen är för stor för hubben.", 413)
                status = answer.status_code
        except httpx.HTTPError as error:
            raise CadError(f"TrainMeet CAD svarar inte just nu ({type(error).__name__}).") from None
        if status == 401:
            raise CadError("TrainMeet ID godtog inte inloggningen. Logga in med ID igen.", 401)
        if status == 404:
            raise CadError("Anläggningen finns inte i CAD, eller så ser du den inte.", 404)
        if status == 422:
            raise CadError(_message(bytes(body)) or "CAD kan inte lämna anläggningen.", 422)
        if status != 200:
            raise CadError(f"TrainMeet CAD svarade med fel {status}.")
        return bytes(body)

    def assemblies(self, token: str) -> list[AssemblyBrief]:
        """The assemblies the planner sees in CAD, newest first."""
        try:
            return _BRIEFS.validate_json(self._get("/assemblies", token))
        except ValidationError:
            raise CadError("CAD:s lista gick inte att läsa.") from None

    def assembly(self, token: str, ident: UUID) -> bytes:
        """The assembly as CAD gave it: kept as it came, read with read()."""
        return self._get(f"/assemblies/{ident}", token)


def _message(body: bytes) -> str | None:
    try:
        found = TypeAdapter(dict[str, object]).validate_json(body).get("message")
    except ValidationError:
        return None
    return str(found)[:300] if isinstance(found, str) else None


# --- Reading ------------------------------------------------------------------------------


def parse(data: bytes) -> MeetAssembly:
    try:
        return MeetAssembly.model_validate_json(data)
    except ValidationError as error:
        raise AssemblyError("Anläggningen från CAD gick inte att läsa.") from error


def segment_length(segment: Segment) -> float:
    if not isinstance(segment, ArcSegment):
        return math.dist(segment.start, segment.end)
    a0 = math.atan2(segment.start[1] - segment.center[1], segment.start[0] - segment.center[0])
    a1 = math.atan2(segment.end[1] - segment.center[1], segment.end[0] - segment.center[0])
    turn = ((a1 - a0) if segment.clockwise else (a0 - a1)) % math.tau
    return segment.radius * (turn if turn > 1e-9 else math.tau)


def piece_length(piece: GraphPiece) -> float:
    return sum(segment_length(s) for s in piece.segments)


def _module_of(ident: str) -> str:
    return ident.split(":", 1)[0]


def _title(module: MeetModule) -> str:
    return f"{module.number} {module.name}"


@dataclass
class _Group:
    id: str
    modules: list[MeetModule]

    @property
    def stations(self) -> list[str]:
        return sorted({s.name for m in self.modules for s in m.stations})

    @property
    def station_ids(self) -> list[str]:
        return sorted({s.station_id for m in self.modules for s in m.stations})


def _groups(assembly: MeetAssembly) -> dict[str, _Group]:
    """The places: modules with a switch or a station, joined where they meet, each module by
    its id."""
    modules = {str(m.id): m for m in assembly.modules}
    placed = [str(p.module) for p in assembly.placed if str(p.module) in modules]
    order = {ident: n for n, ident in enumerate(placed)}
    places = {i for i, m in modules.items() if m.graph.switches or m.stations}
    parent = {i: i for i in places}

    def root(i: str) -> str:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for joint in assembly.joints:
        a, b = str(joint.a.module), str(joint.b.module)
        if a not in places or b not in places:
            continue
        names_a = {s.name for s in modules[a].stations}
        names_b = {s.name for s in modules[b].stations}
        if names_a and names_b and not names_a & names_b:
            continue  # two stations next to each other are two places
        parent[root(a)] = root(b)
    members: dict[str, list[str]] = defaultdict(list)
    for ident in sorted(places, key=lambda i: order.get(i, len(order))):
        members[root(ident)].append(ident)
    found: dict[str, _Group] = {}
    for idents in members.values():
        group = _Group(id=f"m-{UUID(min(idents)).hex}", modules=[modules[i] for i in idents])
        for ident in idents:
            found[ident] = group
    return found


def _allowed(switch: GraphSwitch | None, came: str, going: str) -> bool:
    """May a train go from the piece it came by to the next one at this node? Through a switch
    only between its trunk and one of its legs; anywhere else, any way but back."""
    if switch is None or came == going:
        return came != going
    if switch.type not in (SwitchType.ORDINARY, SwitchType.Y) or switch.trunk is None:
        return True
    return switch.trunk in (came, going) and {came, going} <= {
        switch.trunk,
        switch.straight,
        switch.diverging,
    }


def read(data: bytes, source: str) -> AssemblyLayout:
    """The assembly as places and the tracks between them, in the model's mm."""
    assembly = parse(data)
    graph = assembly.graph
    if graph.geometry != "mm":
        raise AssemblyError("Anläggningen från CAD har ingen geometri i mm.")
    groups = _groups(assembly)
    pieces = {p.id: p for p in graph.pieces}
    lengths = {p.id: piece_length(p) for p in graph.pieces}
    switches = {s.node: s for s in graph.switches}
    at_node: dict[str, list[str]] = defaultdict(list)
    for piece in graph.pieces:
        at_node[piece.start].append(piece.id)
        if piece.end != piece.start:
            at_node[piece.end].append(piece.id)
    by_module = {str(m.id): m for m in assembly.modules}

    def group_of(piece: str) -> _Group | None:
        return groups.get(_module_of(piece))

    def other(piece: str, node: str) -> str:
        found = pieces[piece]
        return found.end if found.start == node else found.start

    # Where the line leaves a place: a node a place's piece and a line piece share.
    paths: dict[tuple[str, str, tuple[str, ...]], list[tuple[float, list[str]]]] = defaultdict(list)
    ends: dict[tuple[str, str, tuple[str, ...]], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    walked: set[frozenset[str]] = set()
    direct: dict[tuple[str, str], list[str]] = defaultdict(list)
    for node in sorted(at_node):
        here = at_node[node]
        owners = sorted({g.id for p in here if (g := group_of(p)) is not None})
        if len(owners) == 2 and all(group_of(p) is not None for p in here):
            direct[(owners[0], owners[1])].append(node)
        for start in owners:
            for first in [p for p in here if group_of(p) is None]:
                way, modules, length, at = [first], [_module_of(first)], lengths[first], node
                at = other(first, at)
                end: str | None = None
                while True:
                    touching = at_node[at]
                    reached = sorted({g.id for p in touching if (g := group_of(p)) is not None})
                    if reached:
                        end = reached[0]
                        break
                    onward = [p for p in touching if p not in way]
                    if not onward:
                        break
                    way.append(onward[0])
                    length += lengths[onward[0]]
                    module = _module_of(onward[0])
                    if module != modules[-1]:
                        modules.append(module)
                    at = other(onward[0], at)
                if end is None or end == start or frozenset(way) in walked:
                    continue
                walked.add(frozenset(way))
                a, b = sorted((start, end))
                in_order = modules if a == start else list(reversed(modules))
                key = (a, b, tuple(sorted(set(modules))))
                paths[key].append((length, in_order))
                ends[key][start].add(node)
                ends[key][end].add(at)
    links: list[AssemblyLink] = []
    link_ends: dict[str, dict[str, set[str]]] = {}
    for n, (key, found) in enumerate(sorted(paths.items(), key=lambda item: item[0]), 1):
        ident = f"l{n}"
        links.append(
            AssemblyLink(
                id=ident,
                a=key[0],
                b=key[1],
                length=round(sum(length for length, _ in found) / len(found), 1),
                tracks=len(found),
                modules=[_title(by_module[m]) for m in found[0][1] if m in by_module],
            )
        )
        link_ends[ident] = ends[key]
    for (a, b), joined in sorted(direct.items()):
        ident = f"l{len(links) + 1}"
        links.append(AssemblyLink(id=ident, a=a, b=b, length=0.0, tracks=len(joined)))
        link_ends[ident] = {a: set(joined), b: set(joined)}

    def within(group: str, start: set[str], goal: set[str]) -> float | None:
        """The shortest way along the place's own tracks between two sets of nodes."""
        queue: list[tuple[float, str, str | None]] = [(0.0, n, None) for n in sorted(start)]
        best: dict[tuple[str, str | None], float] = {}
        while queue:
            far, node, came = heapq.heappop(queue)
            if node in goal:
                return round(far, 1)
            if best.get((node, came), math.inf) <= far:
                continue
            best[(node, came)] = far
            for going in at_node[node]:
                owner = group_of(going)
                if owner is None or owner.id != group:
                    continue
                if came is not None and not _allowed(switches.get(node), came, going):
                    continue
                heapq.heappush(queue, (far + lengths[going], other(going, node), going))
        return None

    through: list[AssemblyThrough] = []
    unique = {g.id: g for g in groups.values()}
    for group in sorted(unique):
        attached = [link for link in links if group in (link.a, link.b)]
        for i, one in enumerate(attached):
            for two in attached[i + 1 :]:
                shortest = within(group, link_ends[one.id][group], link_ends[two.id][group])
                if shortest is not None:
                    through.append(
                        AssemblyThrough(place=group, a=one.id, b=two.id, length=shortest)
                    )
    places = [_place(group, groups, pieces) for group in unique.values()]
    return AssemblyLayout(
        source=source,
        assembly=assembly.id,
        name=assembly.name,
        revision=assembly.revision,
        scale=assembly.scale.value,
        ratio=RATIO.get(assembly.scale.value, 87.0),
        places=sorted(places, key=lambda p: (p.at.x, p.at.y, p.id)),
        links=links,
        through=through,
        modules=len(assembly.modules),
        problems=list(assembly.problems),
    )


def _place(
    group: _Group, groups: dict[str, _Group], pieces: dict[str, GraphPiece]
) -> AssemblyPlace:
    own = [p for ident, p in pieces.items() if groups.get(_module_of(ident)) is group]
    points = [pt for p in own for s in p.segments for pt in (s.start, s.end)]
    x = sum(pt[0] for pt in points) / len(points) if points else 0.0
    y = sum(pt[1] for pt in points) / len(points) if points else 0.0
    stations = group.stations
    name = " / ".join(stations) if stations else ", ".join(_title(m) for m in group.modules)
    return AssemblyPlace(
        id=group.id,
        name=name[:200],
        stations=stations,
        station_ids=group.station_ids,
        modules=[_title(m) for m in group.modules],
        at=MapPoint(x=round(x, 1), y=round(y, 1)),
        switches=sum(len(m.graph.switches) for m in group.modules),
    )
