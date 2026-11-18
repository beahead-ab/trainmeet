"""Levers: which position every switch gets when a route needs some of them (STD-29, TKL104).

A route needs its own switches in given positions. Each of them lies on a lever, and the lever
lays all its own switches together, the reversed ones the other way, and drags along the
switches it names in only one position. A dragged switch moves its own lever too. When two of
these need the same switch, or the same lever, in different positions, the route is impossible.

A switch that TKL lays but that no lever names has a lever of its own, with its number.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from contracts.station_model import Lever, Position, StationModel, SwitchControl
from tkl.standard.graph import parts


@dataclass(frozen=True)
class Laid:
    """What laying a set of switches takes: every switch's position and every lever's."""

    positions: dict[str, Position]
    levers: dict[str, Position]


def own_parts(lever: Lever) -> list[str]:
    """The lever's own switches: those it names in both positions."""
    return [part for part in lever.plus if part in lever.minus]


class Levers:
    def __init__(self, model: StationModel) -> None:
        self.levers: dict[str, Lever] = {}
        self.own: dict[str, str] = {}
        for lever in model.levers:
            self.levers.setdefault(lever.id, lever)
            for part in own_parts(lever):
                self.own.setdefault(part, lever.id)
        for switch in model.switches:
            if switch.control != SwitchControl.TKL:
                continue
            for part in parts(switch):
                if part not in self.own and part not in self.levers:
                    self.levers[part] = Lever(
                        id=part, plus={part: Position.PLUS}, minus={part: Position.MINUS}
                    )
                    self.own[part] = part

    def lay(self, wanted: Mapping[str, Position]) -> Laid | None:
        """The positions and levers that `wanted` takes, or None if it needs a lever both ways."""
        positions: dict[str, Position] = {}
        levers: dict[str, Position] = {}
        queue = list(wanted.items())
        while queue:
            part, position = queue.pop(0)
            if part in positions:
                if positions[part] != position:
                    return None
                continue
            positions[part] = position
            lever_id = self.own.get(part)
            if lever_id is None:
                continue
            lever = self.levers[lever_id]
            side = Position.PLUS if lever.plus[part] == position else Position.MINUS
            if lever_id in levers:
                if levers[lever_id] != side:
                    return None
                continue
            levers[lever_id] = side
            queue.extend((lever.plus if side == Position.PLUS else lever.minus).items())
        return Laid(positions, levers)
