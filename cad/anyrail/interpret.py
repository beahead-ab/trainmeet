"""The interpretation of an AnyRail layout (trainmeet-cad-anyrail-import.md, 2–5): the network of
network.py cut into the modules of modules.py, each a proposal ready to be a module with its
shape, gables and track graph, plus the station's graph, the switch list, the gable profiles,
the checks and the numbers the specification reports.

- Cutting (rule 4): every track is cut where it leaves one board for the next; there each module
  has a module joint at its gable, at the same point. A track that leaves the outermost board is
  cut at its edge and becomes the station's connection there: a module joint no other module
  meets (the line, A… to the west and B… to the east, as Studio names it), also where it goes on
  only a little beyond the gable (more than OUTER_END) to its end, as a loop's tracks do (AR4).
  A track over a board's long side is kept whole in the board it starts in, and shown
  (OBLIQUE_JOINT). A switch whose legs cross a gable before they have parted (closer than the
  gable tolerance) has its points moved to the gable, so that the gable has one track there.
- A module's frame (modules.py): x from gable A along Kant 1, y away from Kant 1, in its own mm.
  Its gables' tracks are the module joints there, spår 1 nearest Kant 1. A track end inside a
  module is a buffer stop.
- Numbering from the west (rule 9, ANYRAIL-16): modules (modules.numbered), switches by their
  points; every id stays AnyRail's as the origin (GraphOrigin.ref). The station's tracks are
  numbered 1, 2 … from the top (AR2) on the line across the station where it has the most
  tracks side by side, in the middle of the longest such stretch; a number follows its track
  through joints, never through a switch.
- Checks (4. Kontroller): assumed switches (yellow, AR3), switches over a module joint, tracks
  that cross a joint at an angle (OBLIQUE_ANGLE or more), the mended overlaps, gaps and backward
  pieces, kinks and tight radii after the filters (sampled every 10 mm, the radius over 50 mm),
  loose parts, and the loops, bridges and walls taken away.

Pure, without I/O, and deterministic: the same layout, scale and measures give the same result.
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from cad import checks, curves, editor, switches
from cad.anyrail import modules, network
from cad.anyrail.modules import Board
from cad.anyrail.network import Network
from cad.anyrail.reader import Layout, Part
from cad.curves import Line, Seg
from contracts.cad import (
    ANYRAIL_SAMPLE_STEP,
    MAX_TRACKS,
    AnyRailMeasures,
    AnyRailModule,
    AnyRailStats,
    AnyRailSwitch,
    Certainty,
    CheckChoice,
    CheckItem,
    CheckKind,
    DrawingSource,
    DrawingState,
    Gable,
    GableEnd,
    GraphNode,
    GraphOrigin,
    GraphPiece,
    GraphSource,
    GraphSwitch,
    Scale,
    Straight,
    TrackGraph,
)
from contracts.station_model import NodeType, Point, SwitchType

STEP: Final = 5.0
"""mm between the points a track is followed through the boards by."""
WEDGE: Final = 60.0
"""mm: a track point outside every board but this near one is in it (a gap between boards)."""
WEDGE_RUN: Final = 300.0
"""mm: a track's stretch outside every board, between two boards, is shared by them."""
TINY: Final = 1.0
"""mm: a piece this short between two cuts is no piece; its ends become one."""
STUB: Final = 2.0
"""mm: where a switch's points lie on a board's edge, its leg into the next board is cut this
far out, so that the switch lies wholly in one module."""
FLICKER: Final = 15.0
"""mm: a track's stay in another board shorter than this is the board around it."""
OBLIQUE_ANGLE: Final = 1.0
"""Degrees: a track crossing a module joint at this angle or more is shown."""
OUTER_END: Final = 5.0
"""mm: a track ending this near an outer gable, where no board continues, goes on to the line."""
OUTSIDE: Final = 20.0
"""mm beyond a gable where another board would continue."""
RADIUS_WINDOW: Final = 5
CONFIRM: Final = CheckChoice(id="stammer", text="Det stämmer")
LIBRARY_SCALES: Final = {"ATL0": Scale.ZERO}
"""AnyRail's track libraries whose scale is known: Atlas O (ATL02R …) is scale 0."""


def scale_of(layout: Layout) -> Scale:
    """The scale the file says, from its track library (.any); H0 otherwise (1.65 cm track)."""
    library = (layout.library or "").upper()
    for prefix, scale in LIBRARY_SCALES.items():
        if library.startswith(prefix):
            return scale
    return Scale.H0


@dataclass
class Proposal:
    """A module the import proposes, with what it is made from."""

    key: str
    number: str
    board: Board
    end: bool
    standard: str | None
    drawing: editor.Drawing
    switches: int
    assumed: int
    switch_ids: dict[int, str] = field(default_factory=dict)
    """The network's switch nodes as the module's switch ids."""


@dataclass
class Result:
    scale: Scale
    measures: AnyRailMeasures
    modules: list[AnyRailModule]
    proposals: list[Proposal]
    switches: list[AnyRailSwitch]
    checks: list[CheckItem]
    stats: AnyRailStats
    graph: TrackGraph
    drawing: list[list[Point]]
    left_out: list[list[Point]]
    profiles: list[GableRow] = field(default_factory=list)


@dataclass(frozen=True)
class GableRow:
    """A row of the gable profiles (ANYRAIL-05): a joint between two modules, or a module's
    gable at the line, its length and its tracks from Kant 1 with their angle to the joint."""

    joint: str
    length: float
    tracks: tuple[float, ...]
    angles: tuple[float, ...]


def _r(p: Point) -> Point:
    return (round(p[0], 3) + 0.0, round(p[1], 3) + 0.0)


def _decimal(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


# --- Cutting the tracks into the boards ------------------------------------------------------


def _board_at(boards: Sequence[Board], p: Point, before: int | None) -> int | None:
    inside = [k for k, b in enumerate(boards) if b.contains(p, 0.5)]
    if before in inside:
        return before
    if inside:
        return min(inside, key=lambda k: (boards[k].length * boards[k].width, k))
    near = [(_distance(boards[k], p), k) for k in range(len(boards))]
    near = [x for x in near if x[0] <= WEDGE]
    return min(near)[1] if near else None


def _distance(board: Board, p: Point) -> float:
    x, y = board.local(p)
    dx = max(0.0, -x, x - board.length)
    dy = max(0.0, -y, y - board.width)
    return math.hypot(dx, dy)


def _crossing(board: Board, a: Point, b: Point) -> Point | None:
    """Where the step from a to b crosses the board's outline."""
    corners = board.corners()
    best: tuple[float, Point] | None = None
    for c, d in zip(corners, [*corners[1:], corners[0]], strict=True):
        hit = network._segment_hit(a, b, c, d)
        if hit is not None:
            t = hit[0]
            point = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            if best is None or t < best[0]:
                best = (t, point)
    return best[1] if best else None


@dataclass
class Cut:
    node: int
    boards: tuple[int | None, int | None]


def cut(net: Network, boards: Sequence[Board]) -> tuple[dict[int, int | None], dict[int, Cut]]:
    """Every leg cut where it changes board: the board of each leg (None: outside), and the cuts."""
    cuts: dict[int, Cut] = {}
    board_of: dict[int, int | None] = {}
    for leg_id in sorted(net.legs):
        leg = net.legs[leg_id]
        total = leg.length
        count = max(2, math.ceil(total / STEP) + 1)
        samples = [curves.path_point(leg.segs, total * k / (count - 1)) for k in range(count)]
        where: list[int | None] = []
        before: int | None = None
        for p in samples:
            before = _board_at(boards, p, before)
            where.append(before)
        step = total / (count - 1) or 1.0
        _steady(where, max(1, int(FLICKER / step)))
        _wedges(where, int(WEDGE_RUN / step))
        _overhang(where, samples, boards, (net.degree(leg.a) == 1, net.degree(leg.b) == 1))
        changes: list[tuple[float, int | None, int | None]] = []
        for k in range(1, count):
            if where[k] == where[k - 1]:
                continue
            a, b = samples[k - 1], samples[k]
            leaving, entering = where[k - 1], where[k]
            found = [
                p
                for p in (
                    _crossing(boards[leaving], a, b) if leaving is not None else None,
                    _crossing(boards[entering], a, b) if entering is not None else None,
                )
                if p is not None
            ]
            if not found:
                found = [
                    p
                    for k_ in (leaving, entering)
                    if k_ is not None
                    for p in [_gable_crossing(boards[k_], a, b)]
                    if p is not None
                ]
            point = (
                (sum(p[0] for p in found) / len(found), sum(p[1] for p in found) / len(found))
                if found
                else ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            )
            s = curves.project_path(leg.segs, point)[0]
            if 0.5 < s < total - 0.5 and (not changes or s > changes[-1][0] + 0.5):
                changes.append((s, where[k - 1], where[k]))
        bounds = [0.0, *(c[0] for c in changes), total]
        middles = [
            where[min(count - 1, round((bounds[k] + bounds[k + 1]) / 2 / step))]
            for k in range(len(bounds) - 1)
        ]
        board_of[leg_id] = middles[0]
        for k in range(len(changes), 0, -1):
            s, first, second = changes[k - 1]
            node = net.split(leg_id, s)
            board_of[net.next_leg - 1] = middles[k]
            cuts[node] = Cut(node, (first, second))
    # Pieces shorter than TINY between cuts are no pieces.
    for leg in sorted(net.legs.values(), key=lambda x: x.id):
        tiny = leg.id in net.legs and leg.length < TINY and leg.a != leg.b
        if tiny and (net.degree(leg.a) == 2 or net.degree(leg.b) == 2):
            keep, drop = (leg.b, leg.a) if net.degree(leg.a) == 2 else (leg.a, leg.b)
            net.remove_leg(leg.id, shown=False)
            board_of.pop(leg.id, None)
            net.merge(keep, drop)
            cuts.pop(drop, None)
    _stubs(net, board_of, cuts)
    if _points_to_edge(net, board_of, cuts):
        _stubs(net, board_of, cuts)
    # Where AnyRail's own pieces end at a board's edge, the node between them is the cut.
    for node, ids in sorted(net.adjacency().items()):
        meeting = sorted({board_of[i] for i in ids}, key=lambda h: -1 if h is None else h)
        if node not in cuts and len(meeting) == 2:
            cuts[node] = Cut(node, (meeting[0], meeting[1]))
    net.drop_empty()
    # A cut is where boards meet: one whose legs all lie in one board is none (a switch's points
    # moved to the edge, its trunk cut STUB further on).
    adjacency = net.adjacency()
    return board_of, {
        n: c
        for n, c in cuts.items()
        if n in net.nodes and len({board_of.get(x, -1) for x in adjacency.get(n, [])}) > 1
    }


def _stubs(net: Network, board_of: dict[int, int | None], cuts: dict[int, Cut]) -> None:
    """A switch on a board's edge keeps its three legs in its own board: its lone leg into the
    next board is cut STUB out."""
    for sw in net.switches:
        legs = [sw.trunk, sw.straight, sw.diverging]
        if any(leg not in net.legs for leg in legs):
            continue
        homes = [board_of.get(leg) for leg in legs]
        if len(set(homes)) == 1:
            continue
        home = max(set(homes), key=lambda h: (homes.count(h), -1 if h is None else -h))
        for leg_id, other in zip(legs, homes, strict=True):
            piece = net.legs[leg_id]
            if other == home or piece.length <= 2 * STUB:
                continue
            at_start = piece.a == sw.node
            node = net.split(leg_id, STUB if at_start else piece.length - STUB)
            new = net.next_leg - 1
            near = leg_id if at_start else new
            board_of[near] = home
            board_of[new if near == leg_id else leg_id] = other
            cuts[node] = Cut(node, (home, other))


def _points_to_edge(net: Network, board_of: dict[int, int | None], cuts: dict[int, Cut]) -> bool:
    """A switch whose two legs cross a board's edge before they have parted, closer there than
    the gable tolerance (two gable tracks that close are one), cannot be built over the joint:
    its points move along the legs to the edge, the trunk grows by as much, and the switch lies
    on the edge, in the board its legs are in (as a switch on an edge does). It is still a switch
    over a joint (4. Kontroller), and the check says how far the points moved. True when one
    moved."""
    moved = False
    for sw in net.switches:
        if not {sw.trunk, sw.straight, sw.diverging} <= set(net.legs):
            continue
        home = board_of.get(sw.trunk)
        straight, diverging = net.legs[sw.straight], net.legs[sw.diverging]
        if board_of.get(straight.id) != home or board_of.get(diverging.id) != home:
            continue
        ends = [leg.b if leg.a == sw.node else leg.a for leg in (straight, diverging)]
        if ends[0] == ends[1] or not all(n in cuts for n in ends):
            continue
        if {*cuts[ends[0]].boards} != {*cuts[ends[1]].boards}:
            continue
        a, b = net.nodes[ends[0]].at, net.nodes[ends[1]].at
        if math.dist(a, b) >= switches.GABLE_TOLERANCE:
            continue
        beyond = [
            next((x for x in net.on(n) if x != leg.id), None)
            for n, leg in zip(ends, (straight, diverging), strict=True)
        ]
        if beyond[0] is None or beyond[1] is None:
            continue
        edge = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        points = net.nodes[sw.node].at
        net.remove_leg(straight.id, shown=False)
        net.remove_leg(diverging.id, shown=False)
        board_of.pop(straight.id, None)
        board_of.pop(diverging.id, None)
        net.merge(ends[0], ends[1], edge)
        cuts.pop(ends[1], None)
        link = net.add_leg(
            ends[0], sw.node, [Line(edge, points)], straight.refs, flex=False, role="trunk"
        )
        other = board_of.get(beyond[0])
        if link.length <= 2 * STUB:
            # Too short to cut STUB on: the trunk's stub is the moved stretch.
            board_of[link.id] = other
            cuts[sw.node] = Cut(sw.node, (other, home))
        else:
            board_of[link.id] = home
        net.moved[id(sw)] = math.dist(edge, points)
        sw.node, sw.trunk, sw.straight, sw.diverging = ends[0], link.id, beyond[0], beyond[1]
        moved = True
    return moved


def _gable_crossing(board: Board, a: Point, b: Point) -> Point | None:
    """Where the step from a to b crosses the line of one of the board's gables, its ends
    included (a step that ends on the gable crosses the outline nowhere inside)."""
    la, lb = board.local(a), board.local(b)
    for x in (0.0, board.length):
        if la[0] != lb[0] and (la[0] - x) * (lb[0] - x) <= 0:
            t = (x - la[0]) / (lb[0] - la[0])
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return None


def _overhang(
    where: list[int | None],
    samples: list[Point],
    boards: Sequence[Board],
    free: tuple[bool, bool],
) -> None:
    """Rule 4: track that goes on beyond a board's gable, more than OUTER_END, to its free end or
    on outside every board, is the line's, not the board's, however near: it is cut at the gable.
    Beyond a gable between two boards it is a wedge (_wedges), a track that bulges out and comes
    back stays, and so does an end just beyond the gable (the outer end, in _proposal)."""
    k = 0
    while k < len(where):
        board = where[k]
        if board is None or _beyond(boards[board], samples[k]) <= 0:
            k += 1
            continue
        j = k
        while j < len(where) and where[j] == board and _beyond(boards[board], samples[j]) > 0:
            j += 1
        outer = (
            (k == 0 and free[0])
            or (j == len(where) and free[1])
            or (k > 0 and where[k - 1] is None)
            or (j < len(where) and where[j] is None)
        )
        if outer and max(_beyond(boards[board], samples[i]) for i in range(k, j)) > OUTER_END:
            for i in range(k, j):
                where[i] = None
        k = j


def _beyond(board: Board, p: Point) -> float:
    """How far beyond the board's gables the point lies, in mm; 0 or less between them."""
    x = board.local(p)[0]
    return max(-x, x - board.length)


def _wedges(where: list[int | None], longest: int) -> None:
    """A short stretch outside every board between two boards (a wedge where an end module
    meets at an angle) is shared by them: the first half the first's, the rest the second's."""
    k = 0
    while k < len(where):
        j = k
        while j < len(where) and where[j] == where[k]:
            j += 1
        if (
            where[k] is None
            and k > 0
            and j < len(where)
            and j - k <= longest
            and where[k - 1] is not None
            and where[j] is not None
        ):
            half = (k + j) // 2
            for i in range(k, j):
                where[i] = where[k - 1] if i < half else where[j]
        k = j


def _steady(where: list[int | None], shortest: int) -> None:
    """A short stay in another board, between two stretches in one, is that one board."""
    k = 0
    while k < len(where):
        j = k
        while j < len(where) and where[j] == where[k]:
            j += 1
        if k > 0 and j < len(where) and j - k < shortest and where[k - 1] == where[j]:
            for i in range(k, j):
                where[i] = where[k - 1]
        k = j


# --- The interpretation ----------------------------------------------------------------------


def interpret(layout: Layout, scale: Scale, measures: AnyRailMeasures) -> Result:
    thin = [p for p in layout.parts if not p.hidden and network.is_thin(p, measures)]
    net = network.run(layout, measures, thin)
    found_boards = modules.boards(thin, scale)
    # A board is a module when it holds track of the layout.
    holding = [
        b
        for b in found_boards
        if any(
            b.contains(p, 0.5)
            for leg in net.legs.values()
            for p in curves.sample_path(leg.segs, 50.0)
        )
    ]
    numbers = modules.numbered(holding, scale)
    order = sorted(range(len(holding)), key=lambda k: _number_key(numbers[k]))
    boards = [holding[k] for k in order]
    numbers = [numbers[k] for k in order]
    board_of, cuts = cut(net, boards)
    findings: list[CheckItem] = []
    # Track outside every board is clipped: the station's connection is the cut.
    for leg_id in [k for k, b in board_of.items() if b is None]:
        net.remove_leg(leg_id)
        board_of.pop(leg_id)
    net.drop_empty()
    # A switch wholly outside every board is no module's: it is not the station's either.
    net.switches = [s for s in net.switches if s.node in net.nodes and s.trunk in net.legs]
    switch_board = _switch_boards(net, board_of)
    numbered_switches = sorted(
        net.switches,
        key=lambda s: (round(net.nodes[s.node].at[0], 1), round(net.nodes[s.node].at[1], 1)),
    )
    switch_number = {id(s): k for k, s in enumerate(numbered_switches, start=1)}
    tracks, middle = _station_tracks(net)
    over_joint = _over_joint(net, board_of, switch_board)
    proposals: list[Proposal] = []
    outer: dict[int, int] = {}
    for k, board in enumerate(boards):
        proposals.append(
            _proposal(
                net,
                k,
                board,
                numbers[k],
                scale,
                board_of,
                cuts,
                switch_board,
                switch_number,
                tracks,
                findings,
                boards,
                outer,
            )
        )
    keys = {k: p.key for k, p in enumerate(proposals)}
    rows = _gable_rows(net, boards, numbers, cuts, board_of, findings, outer)
    switch_rows: list[AnyRailSwitch] = []
    for sw in numbered_switches:
        n = switch_number[id(sw)]
        at = net.nodes[sw.node].at
        home = switch_board.get(id(sw))
        proposal = proposals[home] if home is not None else None
        local_id = proposal.switch_ids.get(sw.node) if proposal else None
        switch_rows.append(
            AnyRailSwitch(
                number=n,
                anyrail=sw.part,
                side=sw.side,
                radius=round(sw.radius, 1) if sw.radius else None,
                angle=round(sw.angle, 2) if sw.angle else None,
                module=keys.get(home) if home is not None else None,
                assumed=sw.assumed,
                over_joint=id(sw) in over_joint,
                at=(round(at[0], 1), round(at[1], 1)),
                confirm=f"{checks.ANYRAIL_ASSUMED}{local_id}" if sw.assumed and local_id else None,
            )
        )
        if sw.assumed:
            findings.append(
                CheckItem(
                    key=f"switch_assumed:anyrail:{n}",
                    kind=CheckKind.SWITCH_ASSUMED,
                    at=(round(at[0], 1), round(at[1], 1)),
                    title=f"Växel {n} är antagen",
                    text="Spåret delar sig utan någon växel i AnyRail. Bekräfta den innan modulen "
                    "publiceras.",
                    refs=[],
                    choices=[CheckChoice(id="vaxel", text="Det är en växel")],
                    assumed=True,
                )
            )
        shift = net.moved.get(id(sw))
        if id(sw) in over_joint or shift is not None:
            findings.append(
                CheckItem(
                    key=f"switch_joint:{n}",
                    kind=CheckKind.SWITCH_JOINT,
                    at=(round(at[0], 1), round(at[1], 1)),
                    title=f"Växel {n} ligger över en modulskarv",
                    text="Växeln sträcker sig in i nästa modul. Den hör till modulen där "
                    "tungspetsen ligger."
                    if shift is None
                    else f"Benen korsade skarven innan de skiljts åt, {_decimal(shift)} mm från "
                    "tungspetsen. Tungspetsen flyttades till skarven, och växeln hör till "
                    "modulen där benen ligger.",
                    refs=[sw.part] if sw.part else [],
                    choices=[CONFIRM],
                )
            )
    kink, radius, kink_items = _kinks(net, scale, measures)
    findings += kink_items
    findings += [_item(f) for f in net.findings]
    findings.sort(key=lambda c: (c.at[0], c.at[1], c.key))
    unique: dict[str, CheckItem] = {}
    for item in findings:
        unique.setdefault(item.key, item)
    made = [_module(p) for p in proposals]
    counts = net.counts
    stats = AnyRailStats(
        parts=len(layout.parts),
        track_parts=sum(1 for p in layout.parts if not p.hidden and network.is_track(p, measures)),
        modules=len(made),
        switches=len(net.switches),
        assumed=sum(1 for s in net.switches if s.assumed),
        crossings=sum(1 for n in net.crossing_nodes if n in net.nodes),
        switches_over_joint=len(over_joint),
        backward_removed=counts.backward,
        gaps=counts.gaps,
        overlaps=counts.overlaps,
        smoothed=counts.smoothed,
        loops_removed=counts.loops,
        bridges_removed=counts.bridges,
        walls_removed=counts.walls,
        doubled_removed=counts.doubled,
        loose=counts.loose,
        side_drawings=counts.side,
        max_kink=round(kink, 2) if kink is not None else None,
        min_radius=round(radius) if radius is not None else None,
        station_tracks=len(set(tracks.values())),
        station_middle=round(middle, 1) if middle is not None else None,
        arcs=counts.arcs,
        arcs_other_way=counts.arcs_other_way,
    )
    return Result(
        scale=scale,
        measures=measures,
        modules=made,
        proposals=proposals,
        switches=switch_rows,
        checks=list(unique.values()),
        stats=stats,
        graph=_station_graph(net, switch_number, tracks),
        drawing=_thin_drawing(thin),
        left_out=net.left_out,
        profiles=rows,
    )


def _number_key(number: str) -> tuple[int, int, str]:
    end = number.startswith("Ä")
    digits = "".join(c for c in number if c.isdigit())
    return (1 if end else 0, int(digits) if digits else 0, number)


def _switch_boards(net: Network, board_of: dict[int, int | None]) -> dict[int, int]:
    """The board each switch lies in: its trunk's, where the points are."""
    found: dict[int, int] = {}
    for sw in net.switches:
        for leg in (sw.trunk, sw.straight, sw.diverging):
            k = board_of.get(leg)
            if k is not None:
                found[id(sw)] = k
                break
    return found


def _over_joint(
    net: Network,
    board_of: dict[int, int | None],
    switch_board: dict[int, int],
) -> set[int]:
    """AnyRail's own turnouts whose own legs reach into another board, or whose points were moved
    to the edge (4. Kontroller). An assumed switch moved there is shown, not counted."""
    found: set[int] = {id(sw) for sw in net.switches if id(sw) in net.moved and sw.part}
    for sw in net.switches:
        if sw.part is None:
            continue
        home = switch_board.get(id(sw))
        for leg in net.legs.values():
            own = leg.refs == (sw.part,) and leg.role in ("straight", "diverging")
            if own and board_of.get(leg.id) != home:
                found.add(id(sw))
    return found


# --- The station's tracks (AR2) --------------------------------------------------------------


def _strand_of(net: Network) -> dict[int, int]:
    """Each leg's strand: legs in a row through plain joints (two legs)."""
    adjacency = net.adjacency()
    strand: dict[int, int] = {}
    for start in sorted(net.legs):
        if start in strand:
            continue
        strand[start] = start
        queue = [start]
        while queue:
            leg = net.legs[queue.pop()]
            for node in (leg.a, leg.b):
                at = adjacency.get(node, [])
                if len(at) == 2 and node not in net.crossing_nodes:
                    for other in at:
                        if other not in strand:
                            strand[other] = start
                            queue.append(other)
    return strand


def _station_tracks(net: Network) -> tuple[dict[int, str], float | None]:
    """The station tracks, 1 … from the top, on the line across the most tracks (AR2)."""
    if not net.legs:
        return {}, None
    polylines = {
        k: curves.sample_path(leg.segs, ANYRAIL_SAMPLE_STEP) for k, leg in net.legs.items()
    }
    xs = [p[0] for line in polylines.values() for p in line]
    lo, hi = math.floor(min(xs) / 10) * 10, math.ceil(max(xs) / 10) * 10
    strand = _strand_of(net)

    def crossing(x: float) -> list[tuple[float, int]]:
        found: list[tuple[float, int]] = []
        for k, line in polylines.items():
            for a, b in itertools.pairwise(line):
                if (a[0] - x) * (b[0] - x) < 0 or (a[0] == x and b[0] != x):
                    t = (x - a[0]) / (b[0] - a[0])
                    found.append((a[1] + (b[1] - a[1]) * t, k))
                    break
        return found

    counts: list[tuple[float, int]] = []
    x = lo + 5.0
    while x < hi:
        counts.append((x, len({strand[k] for _, k in crossing(x)})))
        x += 10.0
    # The stretch with the most tracks side by side for the longest: tracks times length.
    runs: list[tuple[float, float, int]] = []
    start, before = counts[0]
    for x, c in [*counts[1:], (hi + 10, -1)]:
        if c != before:
            runs.append((start, x - 10.0, before))
            start, before = x, c
    first, last, _ = max(runs, key=lambda r: ((r[1] - r[0] + 10) * r[2], -r[0]))
    middle = round((first + last) / 2 / 10) * 10 + 5.0
    across = sorted(crossing(middle))
    tracks: dict[int, str] = {}
    seen: list[int] = []
    for _, k in across:
        if strand[k] not in seen:
            seen.append(strand[k])
    for number, s in enumerate(seen, start=1):
        for leg, of in strand.items():
            if of == s:
                tracks[leg] = str(number)
    return tracks, middle


# --- A module ---------------------------------------------------------------------------------


def _proposal(
    net: Network,
    k: int,
    board: Board,
    number: str,
    scale: Scale,
    board_of: dict[int, int | None],
    cuts: dict[int, Cut],
    switch_board: dict[int, int],
    switch_number: dict[int, int],
    tracks: dict[int, str],
    findings: list[CheckItem],
    boards: Sequence[Board],
    outer: dict[int, int],
) -> Proposal:
    legs = sorted(
        (leg for leg in net.legs.values() if board_of.get(leg.id) == k), key=lambda leg: leg.id
    )
    nodes = sorted({n for leg in legs for n in (leg.a, leg.b)})
    local = {n: board.local(net.nodes[n].at) for n in nodes}
    adjacency: dict[int, int] = defaultdict(int)
    for leg in legs:
        adjacency[leg.a] += 1
        adjacency[leg.b] += 1
    gable_of: dict[int, GableEnd] = {}
    for n in nodes:
        if n not in cuts or adjacency[n] != 1:
            continue
        x, y = local[n]
        edges = {
            "A": abs(x),
            "B": abs(x - board.length),
            "kant1": abs(y),
            "far": abs(y - board.width),
        }
        nearest = min(edges, key=lambda e: (edges[e], e))
        if nearest == "A":
            gable_of[n] = GableEnd.A
        elif nearest == "B":
            gable_of[n] = GableEnd.B
        else:
            at = net.nodes[n].at
            findings.append(
                CheckItem(
                    key=f"oblique_joint:side:{n}",
                    kind=CheckKind.OBLIQUE_JOINT,
                    at=(round(at[0], 1), round(at[1], 1)),
                    title=f"Spåret går över långsidan på modul {number}",
                    text="Spåret går ut genom modulens långsida, inte genom en gavel. Det följer "
                    "med modulen det börjar i.",
                    refs=[],
                    choices=[CONFIRM],
                )
            )
    # A track that ends at an outer gable, where no board continues, goes on to the line there.
    for n in nodes:
        if n in gable_of or adjacency[n] != 1 or n in cuts or net.nodes[n].end in ("buffer", "pit"):
            continue
        x, y = local[n]
        for end, at_x, out in ((GableEnd.A, 0.0, -OUTSIDE), (GableEnd.B, board.length, OUTSIDE)):
            if abs(x - at_x) <= OUTER_END and 0 < y < board.width:
                beyond = board.world((at_x + out, y))
                if not any(b is not board and b.contains(beyond) for b in boards):
                    gable_of[n] = end
                    outer[n] = k
    tracks_at: dict[GableEnd, list[int]] = {
        end: sorted((n for n in gable_of if gable_of[n] == end), key=lambda n: local[n][1])
        for end in (GableEnd.A, GableEnd.B)
    }
    gables = [
        Gable(end=end, tracks=_positions([local[n][1] for n in tracks_at[end]], board.width))
        for end in (GableEnd.A, GableEnd.B)
    ]
    shape = Straight(length=board.length, width=board.width)
    drawing = editor.Drawing.of(
        scale, shape, gables, TrackGraph(), DrawingState(source=DrawingSource.ANYRAIL)
    )
    node_id: dict[int, str] = {}
    ordered = sorted(nodes, key=lambda n: (round(local[n][0], 1), round(local[n][1], 1), n))
    switch_at = {
        sw.node: sw for sw in net.switches if switch_board.get(id(sw)) == k and sw.node in nodes
    }
    for n in ordered:
        made = drawing.new_id("n")
        node_id[n] = made
        if n in gable_of and tracks_at[gable_of[n]].index(n) < MAX_TRACKS:
            end = gable_of[n]
            drawing.nodes[made] = editor.Node(
                made, NodeType.MODULE_JOINT, local[n], end, tracks_at[end].index(n) + 1
            )
        elif n in switch_at:
            drawing.nodes[made] = editor.Node(made, NodeType.SWITCH, local[n])
        elif n in net.crossing_nodes and adjacency[n] == 4:
            drawing.nodes[made] = editor.Node(made, NodeType.CROSSING, local[n])
        elif adjacency[n] == 1:
            drawing.nodes[made] = editor.Node(made, NodeType.BUFFER_STOP, local[n])
        else:
            drawing.nodes[made] = editor.Node(made, NodeType.JOINT, local[n])
    piece_id: dict[int, str] = {}
    for leg in sorted(
        legs, key=lambda leg: (round(local[leg.a][0], 1), round(local[leg.a][1], 1), leg.id)
    ):
        made = drawing.new_id("s")
        piece_id[leg.id] = made
        segs = [_local_seg(board, s) for s in leg.segs]
        drawing.pieces[made] = editor.Piece(
            made,
            node_id[leg.a],
            node_id[leg.b],
            _snap(segs, drawing.nodes[node_id[leg.a]].at, drawing.nodes[node_id[leg.b]].at),
            tracks.get(leg.id),
            GraphOrigin(
                source=GraphSource.ANYRAIL,
                certainty=Certainty.UNCERTAIN if _along_doubled(net, leg) else Certainty.PROBABLE,
                ref="+".join(leg.refs)[:200] or None,
            ),
        )
    count = assumed = 0
    switch_ids: dict[int, str] = {}
    for n in sorted(switch_at, key=lambda n: switch_number[id(switch_at[n])]):
        sw = switch_at[n]
        if drawing.nodes[node_id[n]].type != NodeType.SWITCH:
            continue
        if not {sw.trunk, sw.straight, sw.diverging} <= set(piece_id):
            drawing.nodes[node_id[n]].type = NodeType.JOINT
            continue
        made = drawing.new_id("v")
        switch_ids[n] = made
        count += 1
        assumed += sw.assumed
        away = drawing.away(piece_id[sw.diverging], node_id[n])
        head = curves.start_heading(away[0])
        drawing.switches[made] = editor.Switch(
            id=made,
            node=node_id[n],
            type=SwitchType.Y if sw.side == "y" else SwitchType.ORDINARY,
            trunk=piece_id[sw.trunk],
            straight=piece_id[sw.straight],
            diverging=piece_id[sw.diverging],
            radius=round(sw.radius, 1) if sw.radius and sw.radius <= 20_000 else None,
            angle=round(sw.angle, 2) if sw.angle and 0 < sw.angle < 90 else None,
            origin=GraphOrigin(
                source=GraphSource.ANYRAIL,
                certainty=Certainty.UNCERTAIN if sw.assumed else Certainty.PROBABLE,
                ref=sw.part,
            ),
            number=str(switch_number[id(sw)]),
            design=None,
            toward=GableEnd.B if math.cos(head) >= 0 else GableEnd.A,
        )
    for n in nodes:
        if drawing.nodes[node_id[n]].type == NodeType.SWITCH and n not in switch_ids:
            drawing.nodes[node_id[n]].type = NodeType.JOINT
    try:
        drawing.validate()
    except editor.EditError:
        _loosen(drawing)
    return Proposal(
        key=f"m{k + 1}",
        number=number,
        board=board,
        end=modules.is_end(board, scale),
        standard=modules.standard_of(board.length, board.width, scale),
        drawing=drawing,
        switches=count,
        assumed=assumed,
        switch_ids=switch_ids,
    )


def _along_doubled(net: Network, leg: network.Leg) -> bool:
    """The piece lies where a track drawn twice was taken away: yellow until confirmed."""
    if not net.doubled:
        return False
    middle = curves.path_point(leg.segs, leg.length / 2)
    return any(
        network._to_segment(middle, a, b) <= max(net.measures.lateral, 1.0)
        for points in net.doubled
        for a, b in itertools.pairwise(points)
    )


def _loosen(drawing: editor.Drawing) -> None:
    """A node the graph's rules refuse (three tracks in a plain joint) becomes a buffer stop for
    each extra track, so that the module can still be made; the check shows it."""
    for node in list(drawing.nodes.values()):
        on = drawing.on(node.id)
        if node.type == NodeType.JOINT and len(on) > 2:
            for piece in on[2:]:
                made = drawing.new_id("n")
                drawing.nodes[made] = editor.Node(made, NodeType.BUFFER_STOP, node.at)
                p = drawing.pieces[piece]
                if p.start == node.id:
                    p.start = made
                else:
                    p.end = made
        if node.type == NodeType.MODULE_JOINT and len(on) > 1:
            node.type = NodeType.JOINT
            node.gable = None
            node.track = None
    drawing.validate()


def _positions(values: list[float], width: float) -> list[float]:
    """A gable's tracks from Kant 1, inside the gable and each further than the one before."""
    found: list[float] = []
    for v in sorted(values):
        v = min(max(round(v, 1), 0.1), width - 0.1)
        if found and v <= found[-1]:
            v = round(found[-1] + 0.1, 1)
        found.append(v)
    return found[:12]


def _local_seg(board: Board, seg: Seg) -> Seg:
    if isinstance(seg, curves.Line):
        return curves.Line(board.local(seg.start), board.local(seg.end))
    # The frame turns without mirroring, so a clockwise arc stays clockwise.
    return curves.Arc(
        board.local(seg.start),
        board.local(seg.end),
        board.local(seg.center),
        seg.radius,
        seg.clockwise,
    )


def _snap(segs: list[Seg], a: Point, b: Point) -> list[Seg]:
    if math.dist(segs[0].start, a) < 1e-6 and math.dist(segs[-1].end, b) < 1e-6:
        return segs
    return curves.reshaped(segs, a, b)


def _module(p: Proposal) -> AnyRailModule:
    board = p.board
    built = p.drawing.graph()
    name = f"Ändmodul {p.number}" if p.end else f"Modul {p.number}"
    return AnyRailModule(
        key=p.key,
        number=p.number,
        name=name,
        end=p.end,
        at=(round(board.origin[0], 3), round(board.origin[1], 3)),
        angle=round(board.angle, 6),
        outline=[(round(x, 1), round(y, 1)) for x, y in board.outline],
        shape=Straight(length=board.length, width=board.width),
        standard=p.standard,
        gables=list(p.drawing.gables),
        graph=built,
        switches=p.switches,
        assumed=p.assumed,
        checks=checks.find(p.drawing),
    )


# --- The gable profiles ---------------------------------------------------------------------


def _gable_rows(
    net: Network,
    boards: Sequence[Board],
    numbers: Sequence[str],
    cuts: dict[int, Cut],
    board_of: dict[int, int | None],
    findings: list[CheckItem],
    outer: dict[int, int],
) -> list[GableRow]:
    """Each joint with track (and each gable at the line): its tracks from Kant 1, measured on
    the gable of the board that lies along the station, from the upper end of the stretch the
    two gables share."""
    # A joint is two boards, or a board's gable at the line: (None, board, the gable's end).
    joints: dict[tuple[int | None, int | None, str], list[int]] = defaultdict(list)

    def at_line(n: int, k: int) -> tuple[int | None, int | None, str]:
        x = boards[k].local(net.nodes[n].at)[0]
        return (None, k, "A" if x < boards[k].length / 2 else "B")

    for n in sorted(cuts):
        if n not in net.nodes:
            continue
        on = [board_of.get(leg) for leg in net.on(n)]
        sides = sorted({b for b in on}, key=lambda b: -1 if b is None else b)
        if len(sides) == 1 and sides[0] is not None:
            sides = [None, sides[0]]  # cut at the edge: the line
        if len(sides) != 2:
            continue
        a, b = sides
        joints[at_line(n, b) if a is None and b is not None else (a, b, "")].append(n)
    for n, k in sorted(outer.items()):
        joints[at_line(n, k)].append(n)
    rows: list[GableRow] = []
    for (a, b, _), nodes in joints.items():
        members = [x for x in (a, b) if x is not None]
        reference = min(members, key=lambda k: (abs(boards[k].angle), -boards[k].width, k))
        board = boards[reference]
        x_ref = [board.local(net.nodes[n].at)[0] for n in nodes]
        end = GableEnd.A if sum(x_ref) / len(x_ref) < board.length / 2 else GableEnd.B
        line_x = 0.0 if end == GableEnd.A else board.length
        lo, hi = 0.0, board.width
        other = next((x for x in members if x != reference), None)
        if other is not None:
            ob = boards[other]
            ys = [board.local(c)[1] for c in ob.corners() if abs(board.local(c)[0] - line_x) <= 200]
            if ys:
                lo, hi = max(lo, min(ys)), min(hi, max(ys))
        positions: list[tuple[float, float]] = []
        for n in nodes:
            y = board.local(net.nodes[n].at)[1] - lo
            leg = next(iter(net.on(n)))
            head = net.leaving(leg, n) - math.radians(-board.angle)
            angle = abs(math.degrees(curves.wrap(head)))
            angle = min(angle, 180 - angle)
            positions.append((y, angle))
            if angle >= OBLIQUE_ANGLE and other is not None:
                at = net.nodes[n].at
                findings.append(
                    CheckItem(
                        key=f"oblique_joint:{n}:{angle:.1f}",
                        kind=CheckKind.OBLIQUE_JOINT,
                        at=(round(at[0], 1), round(at[1], 1)),
                        title=f"Spåret korsar skarven {_decimal(angle)}° snett",
                        text="Spåret går inte rakt genom gaveln. Kontrollera att gavlarna passar.",
                        refs=[],
                        choices=[CONFIRM],
                    )
                )
        positions.sort()
        if a is None and b is not None:
            # Gable A is the board's west end (modules.py): the line lies beyond it.
            west, east = (LINE, numbers[b]) if end == GableEnd.A else (numbers[b], LINE)
        else:
            west, east = _west_east(boards, numbers, a, b)
        rows.append(
            GableRow(
                joint=f"{west}|{east}",
                length=round(hi - lo),
                tracks=tuple(round(y) for y, _ in positions),
                angles=tuple(round(x, 1) for _, x in positions),
            )
        )
    return sorted(rows, key=lambda r: _joint_order(r.joint, boards, numbers))


LINE: Final = "Linjen"


def _west_east(
    boards: Sequence[Board], numbers: Sequence[str], a: int | None, b: int | None
) -> tuple[str, str]:
    if a is None or b is None:
        k = a if a is not None else b
        assert k is not None
        mid = (
            min(p[0] for bb in boards for p in bb.corners())
            + max(p[0] for bb in boards for p in bb.corners())
        ) / 2
        return (LINE, numbers[k]) if boards[k].centre[0] < mid else (numbers[k], LINE)
    first, second = sorted((a, b), key=lambda k: boards[k].centre[0])
    return numbers[first], numbers[second]


def _joint_order(joint: str, boards: Sequence[Board], numbers: Sequence[str]) -> tuple[float, str]:
    xs = [boards[numbers.index(n)].centre[0] for n in joint.split("|") if n in numbers]
    return (sum(xs) / len(xs) if xs else 0.0, joint)


# --- Kinks and tight radii (3.3) ---------------------------------------------------------------


def _kinks(
    net: Network, scale: Scale, measures: AnyRailMeasures
) -> tuple[float | None, float | None, list[CheckItem]]:
    """The tracks every 10 mm, through joints and through each switch's two ways: the largest
    angle jump, and the smallest radius over 50 mm."""
    limits = switches.limits(scale)
    worst: tuple[float, Point] | None = None
    tightest: tuple[float, Point] | None = None
    adjacency = net.adjacency()
    chains: list[list[Seg]] = []
    for leg in net.legs.values():
        chains.append(leg.segs)
    for node, legs in adjacency.items():
        if len(legs) == 2:
            chains.append(_through(net, node, legs[0], legs[1]))
    for sw in net.switches:
        chains.append(_through(net, sw.node, sw.trunk, sw.straight))
        chains.append(_through(net, sw.node, sw.trunk, sw.diverging))
    for chain in chains:
        if curves.path_length(chain) < 2 * ANYRAIL_SAMPLE_STEP:
            continue
        points = curves.sample_path(chain, ANYRAIL_SAMPLE_STEP)
        heads = [curves.heading(a, b) for a, b in itertools.pairwise(points)]
        for k, (a, b) in enumerate(itertools.pairwise(heads)):
            jump = math.degrees(abs(curves.wrap(b - a)))
            if worst is None or jump > worst[0]:
                worst = (jump, points[k + 1])
        for k in range(len(heads) - RADIUS_WINDOW):
            turn = abs(curves.wrap(heads[k + RADIUS_WINDOW] - heads[k]))
            run = math.dist(points[k], points[k + 1]) * RADIUS_WINDOW
            if turn > 1e-9:
                radius = run / turn
                if tightest is None or radius < tightest[0]:
                    tightest = (radius, points[k + RADIUS_WINDOW // 2 + 1])
    items: list[CheckItem] = []
    if worst is not None and worst[0] > limits.kink:
        items.append(
            CheckItem(
                key=f"kink:anyrail:{worst[0]:.1f}",
                kind=CheckKind.KINK,
                at=(round(worst[1][0], 1), round(worst[1][1], 1)),
                title=f"Knyck {_decimal(worst[0])}°",
                text=f"Spåret byter riktning mer än {_decimal(limits.kink, 2)}° på 10 mm.",
                refs=[],
                choices=[CONFIRM],
            )
        )
    if tightest is not None and tightest[0] < measures.tight_radius:
        items.append(
            CheckItem(
                key=f"tight_radius:anyrail:{tightest[0]:.0f}",
                kind=CheckKind.TIGHT_RADIUS,
                at=(round(tightest[1][0], 1), round(tightest[1][1], 1)),
                title=f"Snäv radie: R {tightest[0]:.0f} mm",
                text=f"Under {measures.tight_radius:.0f} mm, mätt över 50 mm.",
                refs=[],
                choices=[CONFIRM],
            )
        )
    return (worst[0] if worst else None), (tightest[0] if tightest else None), items


def _through(net: Network, node: int, into: int, out: int) -> list[Seg]:
    """A way through a node: up to 100 mm along one leg into it, and as far along the next."""
    before = curves.reverse_path(net.away(into, node))
    after = net.away(out, node)
    if curves.path_length(before) > 100:
        before = curves.split_path(before, curves.path_length(before) - 100)[1]
    if curves.path_length(after) > 100:
        after = curves.split_path(after, 100)[0]
    return before + after


# --- The station's graph and drawing -----------------------------------------------------------


def _station_graph(net: Network, number: dict[int, int], tracks: dict[int, str]) -> TrackGraph:
    """The whole station in the drawing's mm, for the page: the network's own ids."""
    adjacency = net.adjacency()
    switch_nodes = {sw.node: sw for sw in net.switches}
    nodes: list[GraphNode] = []
    for n in sorted(net.nodes):
        if not adjacency.get(n):
            continue
        if n in switch_nodes:
            kind = NodeType.SWITCH
        elif n in net.crossing_nodes and len(adjacency[n]) == 4:
            kind = NodeType.CROSSING
        elif len(adjacency[n]) == 1:
            kind = NodeType.BUFFER_STOP
        else:
            kind = NodeType.JOINT
        nodes.append(GraphNode(id=f"n{n}", type=kind, at=_r(net.nodes[n].at)))
    pieces = [
        GraphPiece(
            id=f"s{leg.id}",
            start=f"n{leg.a}",
            end=f"n{leg.b}",
            segments=[curves.segment(s) for s in leg.segs],
            track=tracks.get(leg.id),
            origin=GraphOrigin(
                source=GraphSource.ANYRAIL,
                certainty=Certainty.PROBABLE,
                ref="+".join(leg.refs)[:200],
            ),
        )
        for leg in sorted(net.legs.values(), key=lambda x: x.id)
    ]
    found_switches = [
        GraphSwitch(
            id=f"v{number[id(sw)]}",
            node=f"n{sw.node}",
            type=SwitchType.Y if sw.side == "y" else SwitchType.ORDINARY,
            trunk=f"s{sw.trunk}",
            straight=f"s{sw.straight}",
            diverging=f"s{sw.diverging}",
            radius=round(sw.radius, 1) if sw.radius and sw.radius <= 20_000 else None,
            angle=round(sw.angle, 2) if sw.angle and 0 < sw.angle < 90 else None,
            origin=GraphOrigin(
                source=GraphSource.ANYRAIL,
                certainty=Certainty.UNCERTAIN if sw.assumed else Certainty.PROBABLE,
                ref=sw.part,
            ),
            number=str(number[id(sw)]),
        )
        for sw in sorted(net.switches, key=lambda s: number[id(s)])
    ]
    return TrackGraph(geometry="mm", nodes=nodes, pieces=pieces, switches=found_switches)


def _thin_drawing(thin: Sequence[Part]) -> list[list[Point]]:
    lines, chains = modules.thin_lines(thin)
    found = [[(round(a[0], 1), round(a[1], 1)), (round(b[0], 1), round(b[1], 1))] for a, b in lines]
    found += [[(round(x, 1), round(y, 1)) for x, y in chain] for chain in chains]
    return found


def _item(finding: network.Finding) -> CheckItem:
    return CheckItem(
        key=finding.key,
        kind=finding.kind,
        at=finding.at,
        title=finding.title,
        text=finding.text,
        refs=[r for r in finding.refs if r][:20],
        choices=[CONFIRM],
        assumed=finding.assumed,
    )
