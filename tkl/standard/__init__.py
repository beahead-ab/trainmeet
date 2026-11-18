"""Standardställverket (#83): one engine for every station; every station is data (TKL23, TKL40).

Pure Python without I/O, using only the contracts (tests/test_boundaries.py). From a station
model (contracts/station_model.py) it derives what is never stored (STD-07):

- routes.derive: the train routes and shunting routes, with the switch and lever positions,
  the track circuits in order, and the signals passed and guarded (§2, RS9);
- conflicts.conflict: why two routes cannot be set together;
- chains.chains: a route laid through the signals between start and goal (TKL53);
- checks.problems: the checks before a model file may run (STD-04, §6).

No code here names a station (RS13); tkl/tests/test_standard_reference.py greps for it.
"""

from tkl.standard.chains import chains, split
from tkl.standard.checks import problems
from tkl.standard.conflicts import conflict, hindrances, must_be_free
from tkl.standard.route import PointKind, Route, RouteKind, RoutePoint
from tkl.standard.routes import alternatives, derive

__all__ = [
    "PointKind",
    "Route",
    "RouteKind",
    "RoutePoint",
    "alternatives",
    "chains",
    "conflict",
    "derive",
    "hindrances",
    "must_be_free",
    "problems",
    "split",
]
