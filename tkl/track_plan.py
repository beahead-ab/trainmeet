"""Spårplan in Studio (#83): a station's model as the web app shows it, and the reference
stations to look at or use.

The view of a model is its summary, the checks (problems and notes, STD-04), the routes the
engine derives by kind, and the panel: built from the station's own track plan when it has one,
else laid out by the engine (STD-09). The routes are only shown, never set: setting them is the
interlocking's (#84).

The reference stations are the model files in tkl/referens/ (TKL40). They are read-only here;
"Använd som min station" copies one into the station.
"""

from __future__ import annotations

import math
from collections import Counter
from functools import cache
from pathlib import Path

from contracts.station_model import StationModel
from contracts.tkl import (
    LabelSide,
    Panel,
    PanelFunctionButton,
    RouteKind,
    TklChecks,
    TklModelSummary,
    TklReference,
    TklRoute,
    TklTrackPlan,
)
from tkl.standard import LayoutError, PlanError, build, checks, derive, lay_out

REFERENCES = Path(__file__).resolve().parent / "referens"
SUFFIX = ".tkl.json"


BUTTON_OFFSET = 0.8
"""How far a function's button stands from the track, in the panel's smaller cell side."""


def panel_of(model: StationModel) -> Panel | None:
    """The station's panel: from its track plan, else the engine's; None if neither can be
    made (the checks say why)."""
    try:
        panel = build(model) if model.panel is not None else lay_out(model)
    except (PlanError, LayoutError):
        return None
    return panel.model_copy(update={"functions": function_buttons(model, panel)})


def function_buttons(model: StationModel, panel: Panel) -> list[PanelFunctionButton]:
    """The buttons of the panel functions that belong to a node, such as the programming
    track's on its stub (STV-53): beside the node, over or under the track as the plan's
    `function_sides` says, else under it. The others are only in the row of buttons."""
    sides = model.panel.function_sides if model.panel is not None else {}
    nodes = {n.id: n.cell for n in panel.nodes}
    nodes.update({t.id: t.cell for t in panel.tables})
    dx, dy = panel.cell
    u = min(dx, dy)
    found = []
    for function in model.functions:
        at = function.at
        if at is None or at not in nodes:
            continue
        cell = nodes[at]
        side: LabelSide = sides.get(function.name) or sides.get(at) or "under"
        # Across the track at the node, in pixels: the first line that touches it says how
        # the track runs; a node no line touches gets its button straight over or under.
        along = (1.0, 0.0)
        for line in panel.lines:
            for a, b in ((line.cells[0], line.cells[1]), (line.cells[-1], line.cells[-2])):
                if math.isclose(a[0], cell[0]) and math.isclose(a[1], cell[1]):
                    along = ((b[0] - a[0]) * dx, (b[1] - a[1]) * dy)
                    break
        length = math.hypot(*along) or 1.0
        nx, ny = -along[1] / length, along[0] / length
        if (ny > 0) == (side == "over") or (ny == 0 and (nx > 0) == (side == "over")):
            nx, ny = -nx, -ny
        offset = BUTTON_OFFSET * u
        found.append(
            PanelFunctionButton(
                name=function.name,
                type=function.type,
                node=at,
                cell=(round(cell[0] + nx * offset / dx, 3), round(cell[1] + ny * offset / dy, 3)),
                side=side,
            )
        )
    return found


def view(model: StationModel) -> TklTrackPlan:
    found, remarks = checks(model)
    routes = derive(model) if not found else []
    counted = Counter(r.kind.value for r in routes)
    return TklTrackPlan(
        summary=summary(model),
        checks=TklChecks(problems=found, notes=remarks),
        routes={kind: counted.get(kind.value, 0) for kind in RouteKind},
        route_list=[
            TklRoute(
                kind=RouteKind(r.kind.value),
                start=r.start.name,
                end=r.end.name,
                pieces=list(r.pieces),
                positions=dict(r.positions),
                turntable=r.turntable,
            )
            for r in routes
        ],
        panel=panel_of(model) if not found else None,
    )


def summary(model: StationModel) -> TklModelSummary:
    return TklModelSummary(
        station_id=model.station_id,
        name=model.name,
        level=model.level,
        pieces=len(model.pieces),
        switches=len(model.switches),
        levers=len(model.levers),
        signals=len(model.signals),
        track_circuits=len(model.track_circuits),
        station_tracks=[t.label for t in model.station_tracks],
        line_exits=[e.id for e in model.line_exits],
        turntables=len(model.turntables),
        plan=model.panel is not None,
    )


def references() -> list[TklReference]:
    """The reference stations, in the order of their ids (their file names)."""
    found = []
    for station_id in _ids():
        model = reference(station_id)
        if model is not None:
            found.append(
                TklReference(
                    id=station_id, name=model.name, level=model.level, plan=model.panel is not None
                )
            )
    return found


def _ids() -> list[str]:
    return sorted(p.name.removesuffix(SUFFIX) for p in REFERENCES.glob(f"*{SUFFIX}"))


@cache
def reference(station_id: str) -> StationModel | None:
    if station_id not in _ids():
        return None
    text = (REFERENCES / f"{station_id}{SUFFIX}").read_text("utf-8")
    return StationModel.model_validate_json(text)


@cache
def reference_view(station_id: str) -> TklTrackPlan | None:
    """A reference station's view: the same every time, so it is made once."""
    model = reference(station_id)
    return view(model) if model is not None else None
