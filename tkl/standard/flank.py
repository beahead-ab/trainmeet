"""Flank protection (sidoskydd): what keeps vehicles from rolling in on a route from the side.

Benny in trainmeet #37 (15 November): the switches and derailers that could let trains or
wagons in on the reserved track are locked and shown yellow. As in Trafikverket's
TDOK 2013:0623 (Sidoskydd), the nearest object on each joining track protects the route:

- a switch the walk reaches on one of its legs, laid to the other leg, away from the route;
- a derailer (spårspärr, TKL129), laid på (-);
- a signal facing the route, which shows stop, a stop point, a buffer stop or the line.

The walk starts at every switch, slip and crossing the route runs through, on each piece there
that the route does not use, and goes away from the route. Where it meets a switch from its
trunk, a slip or a crossing, vehicles can come from every way that leads in, so it goes on along
each of them. A switch that TKL does not lay, or that the route itself or its levers need the
other way, cannot protect; the walk goes on behind it, from its trunk. Where nothing is found,
the route has no protection on that side, as before.

Pure Python without I/O, using only the contracts (tests/test_boundaries.py).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise

from contracts.station_model import NodeType, Position, SwitchControl
from tkl.standard.graph import SLIP_TYPES, Graph, Step
from tkl.standard.levers import Levers

ENDS = frozenset(
    {NodeType.BUFFER_STOP, NodeType.LINE_EXIT, NodeType.TURNTABLE, NodeType.STOP_POINT}
)


def flank(
    graph: Graph, levers: Levers, steps: Sequence[Step], own: Mapping[str, Position]
) -> dict[str, tuple[Position, str]]:
    """The protection switches of a route: each one's position and the node it protects.

    `own` is what the route's own path needs. The positions are chosen so that the route's own
    switches, its levers and every protection switch can be laid together.
    """
    used = {step.piece for step in steps}
    found: dict[str, tuple[Position, str]] = {}
    wanted = dict(own)
    for before, _after in pairwise(steps):
        node = graph.end_node(before)
        if node not in graph.switch_at:
            continue
        for piece in sorted(graph.touching.get(node, [])):
            if piece not in used:
                _walk(graph, levers, piece, node, used, wanted, found)
    return found


def _faces(graph: Graph, node: str, piece: str) -> bool:
    """A signal at `node` for vehicles coming along `piece`: it shows stop to them."""
    return any(signal.approach == piece for signal in graph.signals_at.get(node, []))


def _walk(
    graph: Graph,
    levers: Levers,
    piece: str,
    origin: str,
    used: set[str],
    wanted: dict[str, Position],
    found: dict[str, tuple[Position, str]],
) -> None:
    """From `origin` on the route out along `piece`, to the nearest object that protects."""
    queue: list[tuple[str, str]] = [(piece, origin)]
    seen: set[str] = set()
    while queue:
        here, near = queue.pop(0)
        if here in used or here in seen:
            continue
        seen.add(here)
        if _faces(graph, near, here):
            continue
        p = graph.pieces[here]
        far = p.end if p.start == near else p.start
        derailer = graph.derailer_at.get(far)
        if derailer is not None and _protects(
            levers, derailer.control, derailer.number, Position.MINUS, wanted
        ):
            wanted[derailer.number] = Position.MINUS
            found.setdefault(derailer.number, (Position.MINUS, origin))
            continue
        switch = graph.switch_at.get(far)
        if switch is None:
            if graph.node_type.get(far) in ENDS:
                continue
            others = [o for o in graph.touching.get(far, []) if o != here]
            if len(others) == 1:
                queue.append((others[0], far))
            continue
        inward: list[str | None]
        if switch.type in SLIP_TYPES:
            inward = [_other(path.between, here) for path in switch.paths if here in path.between]
        elif here == switch.trunk:
            inward = [switch.straight, switch.diverging]
        else:
            away = Position.MINUS if here == switch.straight else Position.PLUS
            if _protects(levers, switch.control, switch.number, away, wanted):
                wanted[switch.number] = away
                found.setdefault(switch.number, (away, origin))
                continue
            inward = [switch.trunk]
        queue.extend(
            (other, far) for other in inward if other is not None and other in graph.pieces
        )


def _other(between: Sequence[str], piece: str) -> str:
    a, b = between
    return b if piece == a else a


def _protects(
    levers: Levers,
    control: SwitchControl,
    number: str,
    away: Position,
    wanted: Mapping[str, Position],
) -> bool:
    """Whether the switch can be laid away from the route together with all the route needs."""
    if control != SwitchControl.TKL or wanted.get(number, away) != away:
        return False
    return levers.lay({**wanted, number: away}) is not None
