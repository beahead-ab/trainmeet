"""The panel built from the station's own track plan (STD-25–STD-28, TKL81, TKL82).

When the model has a plan (`StationModel.panel`), the panel is built from it and not laid out by
the engine; the engine's layout is only the first proposal (STD-09). The plan places every
switch, crossing, track end and the turntable in a cell, and every track as a way over the grid
from one node to another, with the joints between its pieces counted in cells along the way.

The rules (STD-26), as tools/panel.py in the spec checks them, ported:

- a track runs horizontally, vertically or diagonally between cells, except at the turntable or
  where it is marked free;
- no two tracks on the same cell, no crossing without a crossing, and no track through a node
  it does not end at (tkl/standard/grid.py);
- the panel hangs together as the station: each track's pieces follow each other in the model
  from its start node to its end node, the same pieces meet in the same switches and crossings
  as in the drawing, a switch's three legs reach it, four tracks meet in a crossing, and every
  route the engine derives can be followed without a gap.

Where the station is rebuilt and its drawing is old, the plan may depart from the drawing, but
only as it says under `deviation` (STD-28, TKL82): what is not shown, which pieces are rewired,
which pieces and switches are new or renumbered, and which nodes are knots on another track. A
rewired piece is still fixed at both ends, and no route goes over a piece that is not shown.

Otherwise the panel is not built, and the problems say why, in Swedish. Nothing here names a
station (RS13).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import Literal

from contracts.station_model import (
    Cell,
    NodeType,
    PanelPlan,
    Point,
    SignalType,
    StationModel,
)
from contracts.tkl import (
    LabelSide,
    Panel,
    PanelLabel,
    PanelLine,
    PanelNode,
    PanelSignal,
    PanelSource,
    PanelSwitch,
    PanelTable,
    PanelTrackName,
)
from tkl.standard.graph import SLIP_TYPES, Graph
from tkl.standard.grid import cell_text, derailers, describe, hits, straight
from tkl.standard.routes import derive

TOLERANCE_MM = 6.0
"""Piece ends this close in the drawing are joined (tools/panel.py)."""
NAME_OVER = 23.4
"""The track name stands this far over the track, in the plan's units, unless it says."""


class PlanError(Exception):
    """The plan does not hold: the panel is not built."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = problems


def build(model: StationModel) -> Panel:
    """The panel from the model's track plan, or PlanError with every problem found."""
    plan = model.panel
    if plan is None:
        raise PlanError(["Stationen har ingen spårplan."])
    builder = _Builder(model, plan)
    found = builder.check()
    if found:
        raise PlanError(found)
    return builder.panel()


def problems(model: StationModel) -> list[str]:
    """Why the model's track plan cannot be built; empty when it can, or when there is none."""
    if model.panel is None:
        return []
    return _Builder(model, model.panel).check()


class _Builder:
    def __init__(self, model: StationModel, plan: PanelPlan) -> None:
        self.model = model
        self.plan = plan
        self.graph = Graph(model)
        self.dx, self.dy = plan.grid.dx, plan.grid.dy
        self.table = plan.turntable.node if plan.turntable else None
        deviation = plan.deviation
        self.hidden = set(deviation.not_shown.pieces) if deviation else set()
        self.rewired = set(deviation.rewired) if deviation else set()
        self.new = set(deviation.new_pieces) if deviation else set()
        self.knots = frozenset(deviation.knots) if deviation else frozenset()
        self.paths: dict[str, list[Cell]] = {}
        """Each piece's way, from its start to its end, in cells."""
        self.tracks: dict[str, list[Cell]] = {}
        """Each track's way, by its first piece, in cells."""
        self.track_ends: dict[str, tuple[str, str]] = {}
        self.free: set[str] = set()

    # --- the checks ---------------------------------------------------------------------

    def check(self) -> list[str]:
        found = [*self._deviation(), *self._lay()]
        if found:
            return found
        found += self._grid()
        found += self._like_the_station()
        found += self._like_the_drawing()
        found += self._switches()
        found += self._routes()
        return found

    def _deviation(self) -> list[str]:
        """What the plan says about where it departs from the drawing (TKL82)."""
        deviation = self.plan.deviation
        if deviation is None:
            return []
        found: list[str] = []
        pieces = self.graph.pieces
        hidden_switches = set(deviation.not_shown.switches) | set(deviation.not_shown.crossings)
        numbers = {s.number: s for s in self.model.switches}
        for switch in self.model.switches:
            for leg in (switch.trunk, switch.straight, switch.diverging):
                if leg in self.hidden:
                    found.append(f"Växel {switch.number} har benet {leg}, som inte visas.")
        for lever in self.model.levers:
            for part in dict.fromkeys([*lever.plus, *lever.minus]):
                if part in hidden_switches:
                    found.append(f"Spaken {lever.id} har en växel som inte visas: {part}.")
        for number in sorted(hidden_switches):
            node = numbers[number].node if number in numbers else number
            if node in self.plan.nodes:
                found.append(f"Växeln eller korsningen {number} visas inte, men har en ruta.")
        for piece in sorted(self.rewired | self.new):
            if piece not in pieces:
                word = "omkopplade" if piece in self.rewired else "nya"
                found.append(f"Den {word} spårbiten {piece} finns inte i stationen.")
        for number, renamed in deviation.switches.items():
            if number not in numbers:
                found.append(f"Avvikelsen nämner växel {number}, som inte finns i stationen.")
            was = renamed.drawing_number
            if was and was in numbers and was not in deviation.switches:
                found.append(f"Växel {number} har nummer {was} i ritningen, men {was} finns redan.")
        for knot in sorted(self.knots):
            if knot not in self.plan.nodes:
                found.append(f"Knuten {knot} saknas under noder.")
        return found

    def _lay(self) -> list[str]:
        """Every track on the grid, and every piece in exactly one track."""
        found: list[str] = []
        nodes = self.plan.nodes
        placed: dict[str, str] = {}
        for track in self.plan.tracks:
            name = track.pieces[0].id if track.pieces else f"{track.start}–{track.end}"
            missing = [n for n in (track.start, track.end) if n not in nodes]
            if missing:
                found += [f"Spåret {name}: noden {n} saknas under noder." for n in missing]
                continue
            way = [nodes[track.start], *track.via, nodes[track.end]]
            free = track.free or self.table in (track.start, track.end)
            if not free:
                for a, b in pairwise(way):
                    if not straight(a, b):
                        found.append(
                            f"Spåret {name}: {cell_text(a)} till {cell_text(b)} går varken "
                            "vågrätt, lodrätt eller diagonalt."
                        )
            if len(track.joints) != len(track.pieces) - 1:
                found.append(
                    f"Spåret {name}: {len(track.pieces)} spårbitar kräver "
                    f"{len(track.pieces) - 1} skarvar, har {len(track.joints)}."
                )
                continue
            total = self._length(way, free)
            marks = [0.0, *track.joints, total]
            if any(b - a < 1e-9 for a, b in pairwise(marks)):
                found.append(f"Spåret {name}: skarvarna ligger inte i ordning inom 0–{total:g}.")
                continue
            for i, piece in enumerate(track.pieces):
                if piece.id not in self.graph.pieces:
                    found.append(f"Spårbiten {piece.id} finns inte i stationen.")
                    continue
                if piece.id in self.hidden:
                    found.append(
                        f"Spårbiten {piece.id} står både i ett spår och under avviker som "
                        "något som inte visas."
                    )
                if piece.id in placed:
                    found.append(f"Spårbiten {piece.id} står i två spår.")
                placed[piece.id] = name
                part = self._part(way, free, marks[i], marks[i + 1])
                self.paths[piece.id] = list(reversed(part)) if piece.reversed else part
                if free:
                    self.free.add(piece.id)
            self.tracks[name] = way
            self.track_ends[name] = (track.start, track.end)
        missing_pieces = [p for p in self.graph.pieces if p not in placed and p not in self.hidden]
        if missing_pieces:
            found.append("Spårbitar utan plats i spårplanen: " + ", ".join(missing_pieces) + ".")
        if self.table is not None and self.table not in nodes:
            found.append(f"Vändskivan {self.table} saknas under noder.")
        if not found:
            self._turntable_rim()
        return found

    def _length(self, way: Sequence[Cell], free: bool) -> float:
        if free:
            return sum(math.dist(self._px(a), self._px(b)) / self.dx for a, b in pairwise(way))
        return sum(max(abs(b[0] - a[0]), abs(b[1] - a[1])) for a, b in pairwise(way))

    def _part(self, way: Sequence[Cell], free: bool, start: float, end: float) -> list[Cell]:
        """The stretch of a way between two places along it, counted as the track's joints are."""
        lengths = [
            (math.dist(self._px(a), self._px(b)) / self.dx)
            if free
            else max(abs(b[0] - a[0]), abs(b[1] - a[1]))
            for a, b in pairwise(way)
        ]
        marks = [0.0]
        for length in lengths:
            marks.append(marks[-1] + length)

        def at(t: float) -> Cell:
            for i, (a, b) in enumerate(pairwise(way)):
                if t <= marks[i + 1] + 1e-9:
                    size = marks[i + 1] - marks[i]
                    f = 0.0 if size == 0 else (t - marks[i]) / size
                    return (
                        round(a[0] + (b[0] - a[0]) * f, 4),
                        round(a[1] + (b[1] - a[1]) * f, 4),
                    )
            return way[-1]

        found = [at(start)]
        found += [way[i] for i in range(1, len(way) - 1) if start + 1e-9 < marks[i] < end - 1e-9]
        found.append(at(end))
        return found

    def _px(self, cell: Cell) -> Point:
        return (cell[0] * self.dx, cell[1] * self.dy)

    def _cell(self, point: Point) -> Cell:
        return (round(point[0] / self.dx, 4), round(point[1] / self.dy, 4))

    def _turntable_rim(self) -> None:
        """The turntable's tracks begin at its rim."""
        turntable = self.plan.turntable
        if turntable is None:
            return
        centre = self._px(self.plan.nodes[turntable.node])
        for piece in self.graph.touching.get(turntable.node, []):
            path = self.paths.get(piece)
            if not path:
                continue
            at_start = self.graph.pieces[piece].start == turntable.node
            index = 0 if at_start else -1
            near = self._px(path[1] if at_start else path[-2])
            gone = math.dist(near, centre)
            if gone <= 0:
                continue
            rim = (
                centre[0] + (near[0] - centre[0]) * turntable.radius / gone,
                centre[1] + (near[1] - centre[1]) * turntable.radius / gone,
            )
            path[index] = self._cell(rim)

    def _grid(self) -> list[str]:
        """No two tracks on one cell and no crossing without a crossing (STD-26)."""
        tracks = {n: w for n, w in self.tracks.items() if n not in self._free_tracks()}
        ends = {n: self.track_ends[n] for n in tracks}
        return [describe(hit) for hit in hits(tracks, ends, self.plan.nodes, self.knots)]

    def _free_tracks(self) -> set[str]:
        return {
            t.pieces[0].id
            for t in self.plan.tracks
            if t.pieces and (t.free or self.table in (t.start, t.end))
        }

    def _like_the_station(self) -> list[str]:
        """Each track's pieces follow each other in the model, from its start to its end."""
        found: list[str] = []
        pieces = self.graph.pieces
        for track in self.plan.tracks:
            if not track.pieces:
                continue
            name = track.pieces[0].id
            here = track.start
            for placed in track.pieces:
                piece = pieces[placed.id]
                start, end = (
                    (piece.end, piece.start) if placed.reversed else (piece.start, piece.end)
                )
                if start != here:
                    found.append(
                        f"Spåret {name} hänger inte ihop som i stationen: spårbiten "
                        f"{placed.id} börjar inte i {here}."
                    )
                    break
                here = end
            else:
                if here != track.end:
                    found.append(
                        f"Spåret {name} hänger inte ihop som i stationen: det slutar i {here}, "
                        f"inte i {track.end}."
                    )
        return found

    def _like_the_drawing(self) -> list[str]:
        """The same pieces meet in the panel as in the drawing, except where the plan says it
        departs (TKL82). A rewired piece is still fixed at both ends."""
        excused = self.hidden | self.rewired | self.new
        pieces = self.graph.pieces
        table = self.table
        ends = [
            (p.id, e)
            for p in pieces.values()
            if p.id not in excused and len(p.geometry) >= 2 and p.id in self.paths
            for e in (0, 1)
            if not (table is not None and (p.start if e == 0 else p.end) == table)
        ]
        links = [[p.id for p in t.pieces] for t in self.plan.tracks if t.link]
        linked = {piece for link in links for piece in link}

        def drawn(end: tuple[str, int]) -> Point:
            geometry = pieces[end[0]].geometry
            return geometry[0] if end[1] == 0 else geometry[-1]

        def shown(end: tuple[str, int]) -> tuple[float, float]:
            path = self.paths[end[0]]
            point = path[0] if end[1] == 0 else path[-1]
            return (round(point[0], 3), round(point[1], 3))

        in_drawing = _groups(ends, lambda a, b: math.dist(drawn(a), drawn(b)) < TOLERANCE_MM)
        in_panel = _groups(ends, lambda a, b: shown(a) == shown(b), joined=links)
        found: list[str] = []
        for group in sorted(in_drawing - in_panel, key=sorted):
            found.append(
                "Spårbitarna "
                + ", ".join(sorted({p for p, _ in group}))
                + " hänger inte ihop som i ritningen."
            )
        for group in sorted(in_panel - in_drawing, key=sorted):
            found.append(
                "Spårbitarna "
                + ", ".join(sorted({p for p, _ in group}))
                + " hänger ihop i panelen men inte i ritningen."
            )
        named = {
            n.id
            for n in self.model.nodes
            if n.type
            in (NodeType.BUFFER_STOP, NodeType.LINE_EXIT, NodeType.STOP_POINT, NodeType.TURNTABLE)
        }
        for piece in sorted(self.rewired & set(pieces)):
            for node in (pieces[piece].start, pieces[piece].end):
                others = [p for p in self.graph.touching.get(node, []) if p != piece]
                if not others and node not in named and node not in self.knots:
                    found.append(f"Det omkopplade spåret {piece} slutar i tomma luften.")
        for piece, path in self.paths.items():
            if math.dist(path[0], path[-1]) < 1e-6 and piece not in linked:
                found.append(f"Spårbiten {piece} har ingen längd.")
        return found

    def _switches(self) -> list[str]:
        """A switch's legs reach it, and four tracks meet in a crossing."""
        found: list[str] = []
        nodes = self.plan.nodes
        for switch in self.model.switches:
            if switch.node not in nodes:
                found.append(f"Växel {switch.number} saknas under noder.")
                continue
            at = nodes[switch.node]
            if switch.type in SLIP_TYPES:
                meeting = [
                    p
                    for p in self.graph.touching.get(switch.node, [])
                    if p in self.paths and _touches(self.paths[p], at)
                ]
                if len(meeting) != 4:
                    found.append(f"Korsningen {switch.number}: fyra spår ska mötas i den.")
                continue
            for leg in (switch.trunk, switch.straight, switch.diverging):
                if leg is None or leg not in self.paths:
                    continue
                if not _touches(self.paths[leg], at):
                    found.append(f"Växel {switch.number}: benet {leg} når inte växeln.")
        return found

    def _routes(self) -> list[str]:
        """Every route the engine derives can be followed without a gap, and none goes over a
        piece that is not shown (STD-27, STD-28)."""
        found: list[str] = []
        for route in derive(self.model):
            over = [p for p in route.pieces if p in self.hidden]
            if over:
                found.append(f"Vägen {route.name} går över ett spår som inte visas: {over[0]}.")
                continue
            for one, other in pairwise(route.steps):
                a, b = self.paths.get(one.piece), self.paths.get(other.piece)
                if not a or not b:
                    break
                left = a[-1] if one.forward else a[0]
                right = b[0] if other.forward else b[-1]
                if self._at_table(one.piece) and self._at_table(other.piece):
                    continue
                if math.dist(self._px(left), self._px(right)) > 1.0:
                    found.append(f"Vägen {route.name}: glapp mellan {one.piece} och {other.piece}.")
                    break
        return found

    def _at_table(self, piece: str) -> bool:
        p = self.graph.pieces[piece]
        return self.table is not None and self.table in (p.start, p.end)

    # --- the panel ------------------------------------------------------------------------

    def panel(self) -> Panel:
        model = self.model
        plan = self.plan
        graph = self.graph
        cells: dict[str, Cell] = dict(plan.nodes)
        for piece in model.pieces:
            path = self.paths.get(piece.id)
            if not path:
                continue
            cells.setdefault(piece.start, path[0])
            cells.setdefault(piece.end, path[-1])
        real = _node_points(model)
        lines = [
            PanelLine(
                piece=p.id,
                track=p.track,
                cells=self.paths[p.id],
                real=list(p.geometry),
                free=p.id in self.free,
            )
            for p in model.pieces
            if p.id in self.paths
        ]
        nodes = [
            PanelNode(id=n.id, type=n.type, cell=cells[n.id], real=real.get(n.id))
            for n in model.nodes
            if n.id in cells
        ]
        switches = []
        for switch in model.switches:
            if switch.node not in cells:
                continue
            at = cells[switch.node]
            switches.append(
                PanelSwitch(
                    number="/".join(p.number for p in switch.parts) or switch.number
                    if switch.type in SLIP_TYPES
                    else switch.number,
                    type=switch.type,
                    node=switch.node,
                    cell=at,
                    real=real.get(switch.node),
                    trunk=switch.trunk,
                    straight=switch.straight,
                    diverging=switch.diverging,
                    pieces=[p for p in graph.touching.get(switch.node, []) if p in graph.pieces]
                    if switch.type in SLIP_TYPES
                    else [],
                    paths=switch.paths if switch.type in SLIP_TYPES else [],
                    label=(at[0], round(at[1] - 0.25, 4)),
                    laid=graph.laid_by_tkl(switch),
                )
            )
        signals, labels = self._placements(real)
        names = []
        offset = (plan.name_offset if plan.name_offset is not None else NAME_OVER) / self.dy
        for name in plan.track_names:
            point, _ = self._along(name.piece, name.at)
            if point is None:
                continue
            names.append(
                PanelTrackName(
                    name=name.name,
                    cell=(round(point[0] - 0.05, 4), round(point[1] - offset, 4)),
                    train_number=(round(point[0] + 0.05, 4), round(point[1] - offset - 0.2, 4)),
                    real=_mid(model, name.piece),
                )
            )
        tables = []
        for turntable in model.turntables:
            if turntable.node in cells and plan.turntable is not None:
                tables.append(
                    PanelTable(
                        id=turntable.id,
                        node=turntable.node,
                        cell=cells[turntable.node],
                        radius=round(plan.turntable.radius / self.dx, 4),
                        real=real.get(turntable.node),
                        real_radius=turntable.diameter / 2 if turntable.diameter else None,
                    )
                )
        xs = [p[0] for path in self.tracks.values() for p in path]
        ys = [p[1] for path in self.tracks.values() for p in path]
        every = [p for piece in model.pieces for p in piece.geometry]
        box = None
        if every:
            x0, y0 = min(p[0] for p in every), min(p[1] for p in every)
            box = (x0, y0, max(p[0] for p in every) - x0, max(p[1] for p in every) - y0)
        return Panel(
            source=PanelSource.PLAN,
            width=round(max(xs) - min(xs)) + 1,
            height=round(max(ys) - min(ys)) + 1,
            cell=(self.dx, self.dy),
            lines=lines,
            nodes=nodes,
            switches=switches,
            derailers=derailers(model, cells, real),
            signals=signals,
            labels=labels,
            track_names=names,
            tables=tables,
            platforms=list(plan.platforms),
            building=plan.building,
            real_box=box,
        )

    def _along(self, piece: str, at: float) -> tuple[Cell | None, tuple[float, float]]:
        """The place a fraction along a piece, and its direction there, in cells."""
        path = self.paths.get(piece)
        if not path:
            return None, (1.0, 0.0)
        px = [self._px(p) for p in path]
        marks = [0.0]
        for a, b in pairwise(px):
            marks.append(marks[-1] + math.dist(a, b))
        t = at * marks[-1]
        for i, (a, b) in enumerate(pairwise(px)):
            if t <= marks[i + 1] + 1e-9 or i == len(px) - 2:
                size = marks[i + 1] - marks[i]
                f = 0.0 if size == 0 else (t - marks[i]) / size
                point = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                toward = ((b[0] - a[0]) / size, (b[1] - a[1]) / size) if size else (1.0, 0.0)
                return self._cell(point), toward
        return self._cell(px[-1]), (1.0, 0.0)

    def _placements(self, real: dict[str, Point]) -> tuple[list[PanelSignal], list[PanelLabel]]:
        """Signals and the other named points, where the plan puts them."""
        model = self.model
        plan = self.plan
        by_name = {s.name: s for s in model.signals}
        exits = {e.id: e for e in model.line_exits}
        signals: list[PanelSignal] = []
        labels: list[PanelLabel] = []
        for name, placement in plan.signals.items():
            point, toward = self._along(placement.piece, placement.at)
            if point is None:
                continue
            if placement.reversed:
                toward = (-toward[0], -toward[1])
            # In cells, the direction is scaled by the cell's shape.
            unit = _unit(toward[0] / self.dx, toward[1] / self.dy)
            signal = by_name.get(name)
            if signal is None:
                kind: Literal["exit", "point"] = "exit" if name in exits else "point"
                labels.append(
                    PanelLabel(
                        text=name,
                        kind=kind,
                        cell=(point[0], round(point[1] + 0.3, 4)),
                        real=real.get(exits[name].node if name in exits else name),
                    )
                )
                continue
            east = unit[0] > 1e-9 or (abs(unit[0]) <= 1e-9 and unit[1] < 0)
            side: LabelSide = "over" if east else "under"
            if signal.type == SignalType.STOP_LAMP:
                left = (unit[1], -unit[0])
                symbol = (point[0] + left[0] * 0.12, point[1] + left[1] * 0.2)
            else:
                symbol = point
            label_y = symbol[1] - 0.3 if side == "over" else symbol[1] + 0.45
            approach = self.graph.pieces.get(signal.approach)
            real_toward = None
            if approach is not None and len(approach.geometry) >= 2:
                geometry = approach.geometry
                a, b = (
                    (geometry[-2], geometry[-1])
                    if approach.end == signal.node
                    else (geometry[1], geometry[0])
                )
                real_toward = _unit(b[0] - a[0], b[1] - a[1])
            signals.append(
                PanelSignal(
                    name=name,
                    type=signal.type,
                    node=signal.node,
                    cell=point,
                    toward=(round(unit[0], 3), round(unit[1], 3)),
                    symbol=(round(symbol[0], 4), round(symbol[1], 4)),
                    label=(round(symbol[0], 4), round(label_y, 4)),
                    side=side,
                    planned=signal.planned,
                    real=real.get(signal.node),
                    real_toward=real_toward,
                )
            )
        return signals, labels


def _unit(dx: float, dy: float) -> tuple[float, float]:
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 0 else (1.0, 0.0)


def _touches(path: Sequence[Cell], at: Cell) -> bool:
    return any(abs(p[0] - at[0]) < 1e-3 and abs(p[1] - at[1]) < 1e-3 for p in (path[0], path[-1]))


def _groups(
    ends: list[tuple[str, int]],
    same: Callable[[tuple[str, int], tuple[str, int]], bool],
    joined: list[list[str]] | None = None,
) -> set[frozenset[tuple[str, int]]]:
    """The piece ends that meet, as groups: by `same`, and all ends of a link's pieces always
    (a crossover switch drawn as two switches with a link between, as in the drawing)."""
    parent = {e: e for e in ends}

    def find(e: tuple[str, int]) -> tuple[str, int]:
        while parent[e] != e:
            parent[e] = parent[parent[e]]
            e = parent[e]
        return e

    for i, a in enumerate(ends):
        for b in ends[i + 1 :]:
            if find(a) != find(b) and same(a, b):
                parent[find(a)] = find(b)
    for link in joined or []:
        tied = [(piece, e) for piece in link for e in (0, 1) if (piece, e) in parent]
        for a, b in pairwise(tied):
            parent[find(a)] = find(b)
    groups: dict[tuple[str, int], set[tuple[str, int]]] = defaultdict(set)
    for e in ends:
        groups[find(e)].add(e)
    return {frozenset(g) for g in groups.values()}


def _node_points(model: StationModel) -> dict[str, Point]:
    found: dict[str, Point] = {}
    for piece in model.pieces:
        if len(piece.geometry) >= 2:
            found.setdefault(piece.start, piece.geometry[0])
            found.setdefault(piece.end, piece.geometry[-1])
    return found


def _mid(model: StationModel, piece: str) -> Point | None:
    for p in model.pieces:
        if p.id == piece and p.geometry:
            return p.geometry[len(p.geometry) // 2]
    return None


__all__ = ["PlanError", "build", "problems"]
