"""Grafen som bild (4c2, level 3): the graph's lines, written down by the hub's own AI, here
made from the planning file's own graph lines (the public fixture)."""

from __future__ import annotations

import json

import pytest

from contracts.meet import MeetPackage
from contracts.planning import Certainty
from integrationer import derive
from integrationer.graph_picture import GraphError, lines
from integrationer.tests.test_derive import varnamo
from integrationer.tests.test_station_lists import plan, source

__all__ = ["plan"]


def graph_transcript(plan: MeetPackage) -> str:
    """What the AI writes for the graph: each line's stations in order, with their km."""
    codes = {p.id: p.code for p in plan.places}
    found = []
    for page in plan.display.graph_pages:
        kms: list[float | None] = [*page.distances] if page.distances else [None] * len(page.places)
        stations = [{"label": codes[p], "km": km} for p, km in zip(page.places, kms, strict=True)]
        found.append({"number": page.number, "name": page.name, "stations": stations})
    return json.dumps({"lines": found}, ensure_ascii=False)


def test_the_lines_are_read_with_code(plan: MeetPackage) -> None:
    read = lines("Här är grafen:\n" + graph_transcript(plan))
    assert len(read) == len(plan.display.graph_pages) > 1
    assert all(len(line.stations) >= 2 for line in read)
    with pytest.raises(GraphError, match="gick inte att läsa"):
        lines("Jag ser en graf.")
    assert [line.number for line in read] == [p.number for p in plan.display.graph_pages]
    unnamed = lines('{"lines": [{"stations": [{"label": "Mkd", "km": 0}, {"label": "Lek"}]}]}')
    assert unnamed[0].name == unnamed[0].number == "" and unnamed[0].stations[1] == ("Lek", None)
    with pytest.raises(GraphError, match="ingen linje"):
        lines('{"lines": [{"name": "1", "stations": [{"label": "Mkd", "km": 0}]}]}')


def test_the_graph_gives_the_lines_and_confirms_the_sections(plan: MeetPackage) -> None:
    """Level 3: the lines in Graf in the plan's order, and the sections between stations next
    to each other on a line confirmed by trains and graph together."""
    given = source().model_copy(update={"id": "u-graph", "filename": "Grafen.png", "level": 3})
    result = derive.draft(
        varnamo(plan),
        meet=plan.meet,
        source=source(),
        graph=lines(graph_transcript(plan)),
        graphed=given,
    )
    assert result.report.level == 3
    pages = result.package.display.graph_pages
    codes = {p.id: p.code for p in result.package.places}
    planned = {p.id: p.code for p in plan.places}
    main = next(p for p in plan.display.graph_pages if len(p.places) > 5)
    mine = next(p for p in pages if p.name == main.name)
    assert mine.number == main.number
    wanted = [planned[p] for p in main.places]
    assert [codes[p] for p in mine.places] == [c for c in wanted if c in codes.values()]
    facts = {f.ref: f for f in result.facts}
    sure = [
        s for s in result.package.sections if facts[f"section:{s.id}"].certainty == Certainty.SURE
    ]
    assert sure and all(facts[f"section:{s.id}"].origins[-1].source == "u-graph" for s in sure)
    assert facts[f"graph:{mine.id}"].certainty == Certainty.UNSURE, "written down by AI"
    summary = result.report.notes[0]
    assert summary.startswith("Utkastet är härlett ur 14 stationslistor och grafen.")
    assert f"bekräftade {len(sure)} sträckor av" in summary
