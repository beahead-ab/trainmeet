"""A derived route: what the engine gives the interlocking (#84) and the panel (del b).

Routes are never stored (STD-07); they are computed from the model each time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from contracts.station_model import Position
from tkl.standard.graph import Step


class RouteKind(StrEnum):
    TRAIN = "train"  # tågväg
    SHUNTING = "shunting"  # växlingsväg


class PointKind(StrEnum):
    SIGNAL = "signal"
    STOP_POINT = "stop_point"
    BUFFER_STOP = "buffer_stop"
    LINE_EXIT = "line_exit"
    TURNTABLE = "turntable"


@dataclass(frozen=True, order=True)
class RoutePoint:
    """Where a route starts or ends: a signal by its name, or a node by its id."""

    kind: PointKind
    name: str
    node: str


@dataclass(frozen=True)
class Route:
    kind: RouteKind
    start: RoutePoint
    end: RoutePoint
    steps: tuple[Step, ...]
    switches: Mapping[str, Position]
    """The positions the route's own path needs."""
    positions: Mapping[str, Position]
    """Every switch the route lays: its own, the coupled ones, those dragged along and its
    flank protection."""
    levers: Mapping[str, Position]
    track_circuits: tuple[str, ...]
    """The track circuits in the order the route runs through them, for sectional release."""
    passed: tuple[str, ...] = ()
    """Signals in the direction of travel that the route passes (they show proceed)."""
    guards: tuple[str, ...] = ()
    """Signals that must show stop while the route is set: those facing it, and its end."""
    crossings: tuple[str, ...] = ()
    """Crossings and slips the route goes through, by their number."""
    turntable: str | None = None
    """The turntable track the bridge must point at: the first one the route uses."""
    length: float = 0.0
    """In millimetres, from the real geometry; 0 where the model has none."""
    diverging: int = 0
    """How many of the route's own switches lie diverging (TKL53)."""
    flank: Mapping[str, str] = field(default_factory=dict)
    """The switches laid only for flank protection, each with the node on the route it protects
    (STV-20, trainmeet #37), and those their levers lay with them."""

    @property
    def pieces(self) -> tuple[str, ...]:
        return tuple(step.piece for step in self.steps)

    @property
    def key(self) -> tuple[RouteKind, str, str]:
        return (self.kind, self.start.name, self.end.name)

    @property
    def name(self) -> str:
        return f"{self.start.name} → {self.end.name}"
