"""Derailers (spårspärr, TKL129) on the panel: at their node's cell on the track, with the
number under it, whether the engine lays the station out or the station has its own plan."""

from __future__ import annotations

from contracts.station_model import Derailer, SwitchControl
from contracts.tkl import PanelSource
from tkl.standard.outside import panel_of
from tkl.tests.test_standard_flank import siding
from tkl.tests.test_standard_plan import planned


def test_the_engine_s_panel_shows_the_derailer_at_its_node() -> None:
    panel = panel_of(siding())
    assert panel.source == PanelSource.ENGINE
    [derailer] = panel.derailers
    node = next(n for n in panel.nodes if n.id == "D")
    assert (derailer.number, derailer.node, derailer.cell) == ("D1", "D", node.cell)
    assert derailer.label[0] == node.cell[0] and derailer.label[1] > node.cell[1]
    assert derailer.laid
    assert not panel_of(siding(control=SwitchControl.MANUAL)).derailers[0].laid


def test_a_station_with_its_own_plan_shows_the_derailer_at_its_node() -> None:
    model = planned()
    joint = "p16.0|p16.1"
    with_one = model.model_copy(update={"derailers": [Derailer(number="91", node=joint)]})
    panel = panel_of(with_one)
    assert panel.source == PanelSource.PLAN
    [derailer] = panel.derailers
    assert derailer.cell == next(n.cell for n in panel.nodes if n.id == joint)
