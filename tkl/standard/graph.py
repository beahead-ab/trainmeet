"""The station model as a graph the engine can walk.

A step is a track piece taken in one direction. At the node where the step ends, the node
decides where the walk may go on: the other piece of a joint, the legs of a switch with the
position each needs, the paths through a slip or a crossing, or the opposite track over the
turntable. Nothing here knows about a particular station (RS13).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import pairwise

from contracts.station_model import (
    NodeType,
    Position,
    Signal,
    StationModel,
    Switch,
    SwitchControl,
    SwitchType,
    TrackPiece,
    Turntable,
)

# Two turntable tracks are opposite, so the bridge joins them, when their angles differ by
# 180 degrees within this many degrees.
OPPOSITE_TOLERANCE = 0.5

SLIP_TYPES = frozenset({SwitchType.SINGLE_SLIP, SwitchType.DOUBLE_SLIP, SwitchType.CROSSING})


@dataclass(frozen=True, order=True)
class Step:
    """A track piece, taken from its start to its end (forward) or the other way."""

    piece: str
    forward: bool


@dataclass(frozen=True)
class Move:
    """Where a walk may go from the end of a step, and what that needs."""

    step: Step
    node: str
    positions: Mapping[str, Position] = field(default_factory=dict)
    switch: Switch | None = None


def parts(switch: Switch) -> list[str]:
    """The numbers a lever lays: an ordinary or Y switch's own number, a slip's parts."""
    if switch.type in (SwitchType.ORDINARY, SwitchType.Y):
        return [switch.number]
    return [part.number for part in switch.parts]


def opposite(a: float, b: float) -> bool:
    return abs((a - b) % 360 - 180) <= OPPOSITE_TOLERANCE


def length(piece: TrackPiece) -> float:
    """The piece's length in the real geometry, in millimetres; 0 without geometry."""
    points = piece.geometry
    return sum(math.dist(a, b) for a, b in pairwise(points))


class Graph:
    """The model's pieces, nodes, switches, signals and turntables, indexed for walking."""

    def __init__(self, model: StationModel) -> None:
        self.model = model
        self.pieces = {p.id: p for p in model.pieces}
        self.node_type = {n.id: n.type for n in model.nodes}
        self.touching: dict[str, list[str]] = {n.id: [] for n in model.nodes}
        for piece in model.pieces:
            for node in (piece.start, piece.end):
                self.touching.setdefault(node, []).append(piece.id)
        self.switch_at: dict[str, Switch] = {s.node: s for s in model.switches}
        self.switch_of_part: dict[str, Switch] = {
            number: s for s in model.switches for number in parts(s)
        }
        self.signals_at: dict[str, list[Signal]] = {}
        for signal in model.signals:
            self.signals_at.setdefault(signal.node, []).append(signal)
        self.turntable_at: dict[str, Turntable] = {t.node: t for t in model.turntables}
        self.circuit_of: dict[str, str] = {
            piece: circuit.name for circuit in model.track_circuits for piece in circuit.pieces
        }

    # --- steps ------------------------------------------------------------------------

    def end_node(self, step: Step) -> str:
        piece = self.pieces[step.piece]
        return piece.end if step.forward else piece.start

    def leaving(self, piece: str, node: str) -> Step:
        """The step that takes `piece` away from `node`."""
        return Step(piece, self.pieces[piece].start == node)

    def arriving(self, piece: str, node: str) -> Step:
        """The step that takes `piece` towards `node`."""
        return Step(piece, self.pieces[piece].end == node)

    def length(self, step: Step) -> float:
        return length(self.pieces[step.piece])

    # --- where a walk goes on ---------------------------------------------------------

    def moves(self, step: Step) -> list[Move]:
        """The ways on from the node at the end of `step`, with the positions they need.

        A turntable gives none here; the routes decide what the bridge does.
        """
        node = self.end_node(step)
        here = step.piece
        switch = self.switch_at.get(node)
        if switch is not None:
            return self._through_switch(switch, here)
        if self.node_type.get(node) in (NodeType.TURNTABLE, NodeType.BUFFER_STOP):
            return []
        if self.node_type.get(node) == NodeType.LINE_EXIT:
            return []
        others = [p for p in self.touching.get(node, []) if p != here]
        if len(others) != 1:
            return []
        return [Move(self.leaving(others[0], node), node)]

    def _through_switch(self, switch: Switch, here: str) -> list[Move]:
        node = switch.node
        found: list[Move] = []
        if switch.type in SLIP_TYPES:
            for path in switch.paths:
                a, b = path.between
                other = b if here == a else a
                if here in (a, b) and other in self.pieces:
                    found.append(Move(self.leaving(other, node), node, path.positions, switch))
            return found
        legs = [
            (switch.straight, Position.PLUS),
            (switch.diverging, Position.MINUS),
        ]
        if here == switch.trunk:
            for leg, position in legs:
                if leg in self.pieces:
                    found.append(
                        Move(self.leaving(leg, node), node, {switch.number: position}, switch)
                    )
        else:
            for leg, position in legs:
                if leg == here and switch.trunk in self.pieces:
                    found.append(
                        Move(
                            self.leaving(switch.trunk, node),
                            node,
                            {switch.number: position},
                            switch,
                        )
                    )
        return found

    def across_turntable(self, step: Step) -> list[Step]:
        """The tracks the bridge joins to the one `step` arrives on: those opposite it."""
        table = self.turntable_at.get(self.end_node(step))
        if table is None:
            return []
        angles = {t.piece: t.angle for t in table.tracks}
        if step.piece not in angles:
            return []
        mine = angles[step.piece]
        return [
            self.leaving(piece, table.node)
            for piece, angle in angles.items()
            if piece != step.piece and opposite(mine, angle)
        ]

    def laid_by_tkl(self, switch: Switch | None) -> bool:
        return switch is None or switch.control == SwitchControl.TKL
