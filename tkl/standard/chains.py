"""Routes laid through the signals between start and goal (TKL53), and split again.

The goal can lie several signals away: the interlocking lays the whole way as a chain of the
derived routes, train routes through train routes and shunting routes through shunting routes,
only through real signals and never twice over the same track or past the same signal. Where
there are several chains, the one with fewest diverging switches is taken, then the one with
fewest parts, then the shortest (docs/tkl-vagar.md, "Sammansatta vägar"). A chain is
split only at a signal where one of its routes ends and the next begins, never at a point found
from the drawing (splitRouteAt in cda-tkl's src/route-sections.mjs).
"""

from __future__ import annotations

from collections.abc import Iterable

from contracts.station_model import Position
from tkl.standard.route import PointKind, Route, RouteKind

Chain = tuple[Route, ...]


def _fits(laid: dict[str, Position], route: Route) -> bool:
    return all(laid.get(part, position) == position for part, position in route.positions.items())


def chains(
    routes: Iterable[Route], kind: RouteKind, start: str, goal: str, *, most: int = 6
) -> list[Chain]:
    """Every chain of `kind` routes from `start` to `goal`, the preferred first.

    The routes follow on at the signal where the one before ends, no signal is passed twice,
    and no switch is needed in two positions.
    """
    by_start: dict[str, list[Route]] = {}
    for route in routes:
        if route.kind == kind:
            by_start.setdefault(route.start.name, []).append(route)
    found: list[Chain] = []

    def extend(chain: Chain, laid: dict[str, Position], seen: set[str], used: set[str]) -> None:
        here = chain[-1].end if chain else None
        name = start if here is None else here.name
        if here is not None and (here.name == goal or here.kind != PointKind.SIGNAL):
            if here.name == goal:
                found.append(chain)
            return
        if len(chain) >= most:
            return
        for route in by_start.get(name, []):
            passed = {route.end.name, *route.passed}
            if passed & seen or used & set(route.pieces) or not _fits(laid, route):
                continue
            extend(
                (*chain, route),
                {**laid, **route.positions},
                seen | passed,
                used | set(route.pieces),
            )

    extend((), {}, {start}, set())
    return sorted(found, key=preference)


def preference(chain: Chain) -> tuple[int, int, float, tuple[str, ...]]:
    """Fewest diverging switches (TKL53), then the fewest parts, then the shortest."""
    return (
        sum(r.diverging for r in chain),
        len(chain),
        sum(r.length for r in chain),
        tuple(p for r in chain for p in r.pieces),
    )


def positions(chain: Chain) -> dict[str, Position]:
    laid: dict[str, Position] = {}
    for route in chain:
        laid.update(route.positions)
    return laid


def split(chain: Chain, signal: str) -> tuple[Chain, Chain] | None:
    """The chain cut at `signal`: the part before and the part after, or None.

    Only where a route of the chain ends and the next begins; not at the chain's own start or
    end, and not at a signal the chain only passes.
    """
    for i, route in enumerate(chain[:-1]):
        if route.end.kind == PointKind.SIGNAL and route.end.name == signal:
            return chain[: i + 1], chain[i + 1 :]
    return None
