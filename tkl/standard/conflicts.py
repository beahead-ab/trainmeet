"""When two routes cannot be set together, and what setting one needs.

Ported from compatible() in cda-tkl's src/route-selection.mjs: two routes conflict when they
share a track circuit (two circuits on the same detector count as one), a piece, a crossing or
a slip, when they need a switch in different positions (counting coupled and dragged ones), or
when one shows proceed past a signal that the other needs at stop. A route that starts where
the other ends is its continuation, not a conflict.

Sectional release per track circuit is the interlocking's (#84); it gets the route's track
circuits in order from Route.track_circuits.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from contracts.station_model import Address, Position, StationModel
from tkl.standard.route import PointKind, Route, RouteKind


def detectors(model: StationModel) -> dict[str, str]:
    """Track circuit -> its detector. Circuits on the same detector share one key."""
    found: dict[str, str] = {}
    for circuit in model.track_circuits:
        if isinstance(circuit.detection, Address):
            found[circuit.name] = f"{circuit.detection.bus}:{circuit.detection.number}"
        else:
            found[circuit.name] = circuit.name
    return found


def _proceed(route: Route) -> list[str]:
    """The signals the route clears: its start, and those it passes in its direction."""
    start = [route.start.name] if route.start.kind == PointKind.SIGNAL else []
    return [*start, *route.passed]


def _against(owner: Route, other: Route) -> str | None:
    """A signal that `other` clears and `owner` needs at stop, unless `other` continues it."""
    for signal in _proceed(other):
        if signal not in owner.guards:
            continue
        continues = owner.end.kind == PointKind.SIGNAL and owner.end.name == other.start.name
        if continues and signal == other.start.name:
            continue
        return signal
    return None


def conflict(a: Route, b: Route, detector: Mapping[str, str] | None = None) -> str | None:
    """Why `a` and `b` cannot be set at the same time, in Swedish, or None if they can."""
    key = detector or {}
    mine = {key.get(c, c): c for c in a.track_circuits}
    for circuit in b.track_circuits:
        if key.get(circuit, circuit) in mine:
            return f"Båda går över spårledningen {circuit}."
    shared = set(a.pieces) & set(b.pieces)
    if shared:
        return f"Båda går över spårbiten {min(shared)}."
    crossing = set(a.crossings) & set(b.crossings)
    if crossing:
        return f"Båda går genom {min(crossing)}."
    for part, position in a.positions.items():
        other = b.positions.get(part)
        if other is not None and other != position:
            return f"De behöver växel {part} i olika lägen."
    signal = set(_proceed(a)) & set(_proceed(b))
    if signal:
        return f"Båda ställer signalen {min(signal)} till kör."
    stop = _against(a, b) or _against(b, a)
    if stop is not None:
        return f"Signalen {stop} ska visa stopp för den ena vägen och kör för den andra."
    return None


def must_be_free(route: Route) -> tuple[str, ...]:
    """The track circuits that must be free to set the route.

    A shunting route may go towards an occupied track (TKL28): the circuit it ends in may be
    occupied, so that a locomotive can couple to the wagons there.
    """
    if route.kind == RouteKind.SHUNTING:
        return route.track_circuits[:-1]
    return route.track_circuits


def hindrances(
    route: Route, occupied: Collection[str], locked: Mapping[str, Position]
) -> list[str]:
    """Why the route cannot be set now, in Swedish: occupied track and locked switches."""
    found = [f"Spårledningen {c} är belagd." for c in must_be_free(route) if c in occupied]
    for part, position in route.positions.items():
        lock = locked.get(part)
        if lock is not None and lock != position:
            found.append(f"Växel {part} är låst i läget {lock.value}.")
    return found
