"""A synthetic assembly from TrainMeet CAD (trainmeet.cad-assembly/1), for the tests and the check
of Anläggning från CAD in the hub's image (hub/prov_cad.py), straight along x: three
stations with a switch each, used by stations in TKL, and line modules between them.

    Aby (0–2000) | line 1500 | line 1000 | Bby (4500–6500) | line 1200 | Cby (7700–9000)

Aby's switch makes two tracks towards Bby (y 0 and 46); Bby's joins them again; one track runs
on to Cby. Every length along the track is known: Aby–Bby 2500 mm on both tracks, Bby–Cby
1200 mm, and through Bby 2000 mm on the straight track.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any
from uuid import UUID

from contracts.cad import (
    GableLabel,
    GraphNode,
    GraphPiece,
    GraphSwitch,
    Joint,
    JointEnd,
    LineSegment,
    MeetAssembly,
    MeetModule,
    MeetStation,
    PlacedModule,
    Scale,
    Straight,
    TrackGraph,
)
from contracts.station_model import NodeType, SwitchType

ASSEMBLY = UUID("00000000-0000-4000-8000-0000000000aa")
TRACK_2 = 46.0


def _id(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012d}")


@dataclass
class _Module:
    n: int
    name: str
    x: float
    length: float
    station: tuple[str, str] | None = None
    nodes: list[GraphNode] = field(default_factory=list)
    pieces: list[GraphPiece] = field(default_factory=list)
    switches: list[GraphSwitch] = field(default_factory=list)

    @property
    def id(self) -> UUID:
        return _id(self.n)

    def node(self, ident: str, x: float, y: float, kind: NodeType, gable: str | None = None) -> str:
        track = (1 if y == 0 else 2) if gable else None
        self.nodes.append(
            GraphNode(id=ident, type=kind, at=(x, y), gable=gable, track=track)  # type: ignore[arg-type]
        )
        return ident

    def piece(self, ident: str, a: str, b: str) -> str:
        at = {n.id: n.at for n in self.nodes}
        self.pieces.append(
            GraphPiece(id=ident, start=a, end=b, segments=[LineSegment(start=at[a], end=at[b])])
        )
        return ident


def _station_a(m: _Module) -> None:
    n1 = m.node("n1", 0, 0, NodeType.MODULE_JOINT, "A")
    n2 = m.node("n2", 800, 0, NodeType.SWITCH)
    n3 = m.node("n3", m.length, 0, NodeType.MODULE_JOINT, "B")
    n4 = m.node("n4", m.length, TRACK_2, NodeType.MODULE_JOINT, "B")
    s1, s2, s3 = m.piece("s1", n1, n2), m.piece("s2", n2, n3), m.piece("s3", n2, n4)
    m.switches.append(
        GraphSwitch(id="w1", node=n2, type=SwitchType.ORDINARY, trunk=s1, straight=s2, diverging=s3)
    )


def _station_b(m: _Module) -> None:
    n1 = m.node("n1", 0, 0, NodeType.MODULE_JOINT, "A")
    n2 = m.node("n2", 0, TRACK_2, NodeType.MODULE_JOINT, "A")
    n3 = m.node("n3", 1200, 0, NodeType.SWITCH)
    n4 = m.node("n4", m.length, 0, NodeType.MODULE_JOINT, "B")
    s1, s2, s3 = m.piece("s1", n1, n3), m.piece("s2", n2, n3), m.piece("s3", n3, n4)
    m.switches.append(
        GraphSwitch(id="w1", node=n3, type=SwitchType.ORDINARY, trunk=s3, straight=s1, diverging=s2)
    )


def _station_c(m: _Module) -> None:
    n1 = m.node("n1", 0, 0, NodeType.MODULE_JOINT, "A")
    n2 = m.node("n2", 500, 0, NodeType.SWITCH)
    n3 = m.node("n3", m.length, 0, NodeType.BUFFER_STOP)
    n4 = m.node("n4", m.length, TRACK_2, NodeType.BUFFER_STOP)
    s1, s2, s3 = m.piece("s1", n1, n2), m.piece("s2", n2, n3), m.piece("s3", n2, n4)
    m.switches.append(
        GraphSwitch(id="w1", node=n2, type=SwitchType.ORDINARY, trunk=s1, straight=s2, diverging=s3)
    )


def _line(m: _Module, tracks: int) -> None:
    for t in range(tracks):
        y = t * TRACK_2
        a = m.node(f"n{2 * t + 1}", 0, y, NodeType.MODULE_JOINT, "A")
        b = m.node(f"n{2 * t + 2}", m.length, y, NodeType.MODULE_JOINT, "B")
        m.piece(f"s{t + 1}", a, b)


def modules(stations: bool = True) -> list[_Module]:
    """The modules, each built in its own mm from gable A at Kant 1."""
    found = [
        _Module(1, "Aby station", 0, 2000, ("aby", "Aby") if stations else None),
        _Module(2, "Linje 1", 2000, 1500),
        _Module(3, "Linje 2", 3500, 1000),
        _Module(4, "Bby station", 4500, 2000, ("bby", "Bby") if stations else None),
        _Module(5, "Linje 3", 6500, 1200),
        _Module(6, "Cby station", 7700, 1300, ("cby", "Cby") if stations else None),
    ]
    _station_a(found[0])
    _line(found[1], 2)
    _line(found[2], 2)
    _station_b(found[3])
    _line(found[4], 1)
    _station_c(found[5])
    return found


def _joined(found: list[_Module]) -> TrackGraph:
    """The assembly's graph: every module moved to where it lies, its ids prefixed with its id,
    and one node where two modules' tracks meet (the smaller id), as CAD's Till TKL Studio."""
    nodes: dict[str, GraphNode] = {}
    rename: dict[str, str] = {}
    by_place: dict[tuple[float, float], str] = {}
    for m in found:
        for n in m.nodes:
            ident = f"{m.id}:{n.id}"
            at = (n.at[0] + m.x, n.at[1])
            key = (round(at[0], 3), round(at[1], 3))
            if n.type == NodeType.MODULE_JOINT and key in by_place:
                kept = by_place[key]
                smaller = min(kept, ident)
                rename[ident] = smaller
                rename[kept] = smaller
                nodes[smaller] = nodes.pop(kept).model_copy(update={"id": smaller})
                by_place[key] = smaller
                continue
            by_place[key] = ident
            rename[ident] = ident
            nodes[ident] = n.model_copy(update={"id": ident, "at": at})
    pieces: list[GraphPiece] = []
    switches: list[GraphSwitch] = []
    for m in found:

        def q(local: str | None, m: _Module = m) -> str | None:
            return f"{m.id}:{local}" if local is not None else None

        for p in m.pieces:
            segment = p.segments[0]
            pieces.append(
                GraphPiece(
                    id=f"{m.id}:{p.id}",
                    start=rename[f"{m.id}:{p.start}"],
                    end=rename[f"{m.id}:{p.end}"],
                    segments=[
                        LineSegment(
                            start=(segment.start[0] + m.x, segment.start[1]),
                            end=(segment.end[0] + m.x, segment.end[1]),
                        )
                    ],
                )
            )
        for s in m.switches:
            switches.append(
                s.model_copy(
                    update={
                        "id": f"{m.id}:{s.id}",
                        "node": rename[f"{m.id}:{s.node}"],
                        "trunk": q(s.trunk),
                        "straight": q(s.straight),
                        "diverging": q(s.diverging),
                    }
                )
            )
    return TrackGraph(nodes=list(nodes.values()), pieces=pieces, switches=switches)


def assembly(stations: bool = True, revision: int = 3) -> MeetAssembly:
    found = modules(stations)
    meet_modules = []
    for m in found:
        gable_tracks = sorted({n.at[1] for n in m.nodes if n.gable == "A"}) or [0.0]
        meet_modules.append(
            MeetModule(
                id=m.id,
                number=f"M-{m.n:03d}",
                name=m.name,
                version=1,
                scale=Scale.H0,
                shape=Straight(length=m.length, width=300),
                gables=[
                    GableLabel(end="A", label="Egen gavel", tracks=[t + 100 for t in gable_tracks]),  # type: ignore[arg-type]
                    GableLabel(end="B", label="Egen gavel", tracks=[100.0]),  # type: ignore[arg-type]
                ],
                graph=TrackGraph(nodes=m.nodes, pieces=m.pieces, switches=m.switches),
                track_length=sum(
                    math.dist(p.segments[0].start, p.segments[0].end) for p in m.pieces
                ),
                stations=[MeetStation(station_id=m.station[0], name=m.station[1])]
                if m.station
                else [],
            )
        )
    return MeetAssembly(
        id=ASSEMBLY,
        name="Provträffens anläggning",
        scale=Scale.H0,
        revision=revision,
        placed=[PlacedModule(module=m.id, version=1, at=(m.x, 0), angle=0) for m in found],
        joints=[
            Joint(a=JointEnd(module=a.id, gable="B"), b=JointEnd(module=b.id, gable="A"))  # type: ignore[arg-type]
            for a, b in pairwise(found)
        ],
        graph=_joined(found),
        modules=meet_modules,
    )


def assembly_bytes(**given: Any) -> bytes:
    return assembly(**given).model_dump_json().encode()
