"""Profile Stationsritning read by code (#89 del c4, bildkedjan R1–R4): a synthetic signal plan
as a vector PDF, the same drawing photographed at an angle with a pretend AI's transcription, an
SVG, and the contract. Nothing here needs a database; cad/tests/test_drawings.py has the jobs,
the price and the meter."""

from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path
from uuid import UUID

import pytest

from cad.bildkedjan import ritning, ritning_in
from cad.bildkedjan import ritning_syntetisk as syn
from contracts.cad import (
    DrawingPageKind,
    DrawingPrice,
    DrawingQuestionKind,
    DrawingRead,
    DrawingSummary,
    GraphNode,
    GraphSymbol,
    ReadBy,
    SymbolKind,
    TrackGraph,
)
from contracts.station_model import NodeType


@cache
def vector() -> tuple[ritning_in.Page, ritning.Read, ritning.Assembled]:
    page = ritning_in.take(syn.pdf()).pages[0]
    found = ritning.read(page)
    return page, found, ritning.assemble(found, page)


@cache
def raster(ai: bool) -> tuple[ritning_in.Page, ritning.Assembled]:
    taken = ritning_in.take(syn.photo())
    assert taken.format == "image" and taken.pages[0].kind == "raster"
    pixels = taken.pages[0].pixels
    assert pixels is not None
    page = ritning_in.raster_page(pixels)
    if ai:
        page.words = ritning_in.understand(syn.ai_answer(), page)
    return page, ritning.assemble(ritning.read(page), page)


def _signals(graph: TrackGraph) -> dict[str, GraphSymbol]:
    return {s.name: s for s in graph.symbols if s.kind == SymbolKind.SIGNAL and s.name}


def _truth_signals(graph: TrackGraph) -> None:
    found = _signals(graph)
    for name, (kind, lamps, address, facing) in syn.scene().truth["signals"].items():
        signal = found[name]
        assert signal.signal == kind, name
        assert signal.lamps == lamps, name
        assert signal.address == address, name
        assert signal.facing == facing, name
        assert signal.piece is not None


def test_a_vector_pdf_is_read_by_code() -> None:
    """R1: the tracks, the switches with their numbers where they stand, the line exits and the
    buffer stop, the signals with type, name and address, and the boundaries, all by code."""
    page, _, made = vector()
    truth = syn.scene().truth
    assert page.kind == "vector" and page.text
    assert made.summary == DrawingSummary(
        pieces=truth["pieces"],
        switches=len(truth["switches"]),
        crossings=0,
        line_exits=truth["line_exits"],
        buffer_stops=truth["buffer_stops"],
        signals=len(truth["signals"]),
        boundaries=truth["boundaries"],
        labels=len(syn.scene().texts),
        unknown_symbols=3,
    )
    nodes = {n.id: n for n in made.graph.nodes}
    for switch in made.graph.switches:
        assert switch.number is not None
        assert math.dist(nodes[switch.node].at, truth["switches"][switch.number]) < 0.5
        assert switch.trunk and switch.straight and switch.diverging
    _truth_signals(made.graph)
    # The order west to east: the nodes are numbered from the west.
    xs = [n.at[0] for n in made.graph.nodes]
    assert xs == sorted(xs)
    names = {p.track for p in made.graph.pieces if p.track}
    assert names == set(truth["tracks"])
    assert all(label.read_by == ReadBy.TEXT_LAYER for label in made.graph.labels)
    assert not made.notes


def test_the_legend_is_asked_once_per_colour_and_symbol_type() -> None:
    """R3: one question per class code cannot place, the legend first: the orange lines, and the
    green triangle the catalogue does not know."""
    _, _, made = vector()
    keys = [q.key for q in made.questions]
    assert keys == ["linje.orange-tunna", "symbol.triangle-grona"]
    assert all(q.kind == DrawingQuestionKind.LEGEND for q in made.questions)
    lines, triangles = made.questions
    assert lines.code == "annat" and lines.count == 2
    assert triangles.title == "Vad betyder ▲ i den här ritningen?"
    assert triangles.code is None and triangles.count == 3


def test_an_answer_changes_the_read_without_reading_again() -> None:
    page, _, _ = vector()
    found = ritning.read(page, {"symbol.triangle-grona": "knapp", "linje.orange-tunna": "annat"})
    made = ritning.assemble(found, page)
    assert made.summary.unknown_symbols == 0
    assert {q.key: q.answer for q in made.questions} == {
        "linje.orange-tunna": "annat",
        "symbol.triangle-grona": "knapp",
    }
    as_signals = ritning.assemble(ritning.read(page, {"symbol.triangle-grona": "dvsi"}), page)
    added = [s for s in as_signals.graph.symbols if s.kind == SymbolKind.SIGNAL and not s.name]
    assert len(added) == 2  # the two by the tracks; the legend's own has no track
    assert {s.facing for s in added} == {"east", "west"}


def test_a_photographed_drawing_with_the_ai_transcription() -> None:
    """R2: the paper straightened, the light made even, the lines by LSD and the graph; the
    text from the pretend AI tied to the objects by code."""
    page, made = raster(True)
    truth = syn.scene().truth
    assert made.summary.pieces == truth["pieces"]
    assert made.summary.switches == len(truth["switches"])
    assert made.summary.line_exits == truth["line_exits"]
    assert made.summary.buffer_stops == truth["buffer_stops"]
    assert made.summary.boundaries == truth["boundaries"]
    _truth_signals(made.graph)
    # The straightened paper is the page, each way to its own scale.
    sx, sy = syn.WIDTH / page.width, syn.HEIGHT / page.height
    nodes = {n.id: n for n in made.graph.nodes}
    for switch in made.graph.switches:
        assert switch.number is not None
        x, y = nodes[switch.node].at
        assert math.dist((x * sx, y * sy), truth["switches"][switch.number]) < 3.0
    assert all(label.read_by == ReadBy.AI for label in made.graph.labels)
    assert [q.key for q in made.questions] == ["linje.orange-tunna", "symbol.triangle-grona"]


def test_a_photographed_drawing_without_ai_has_no_names() -> None:
    _, made = raster(False)
    assert made.summary.switches == 5
    assert made.summary.labels == 0
    signals = [s for s in made.graph.symbols if s.kind == SymbolKind.SIGNAL]
    assert len(signals) == 5  # the figures; the two text signals need their text
    assert all(s.name is None and s.lamps in (2, 3) for s in signals)
    assert any("inte avskrivna" in note for note in made.notes)


def test_the_transcription_is_read_failing_closed() -> None:
    page = ritning_in.Page(1, "raster", 1000.0, 500.0)
    good = {"texter": [{"text": "113", "x": 10, "y": 20, "b": 30, "h": 10}]}
    words = ritning_in.understand("```json\n" + json.dumps(good) + "\n```", page)
    assert words[0].box == (10.0, 10.0, 40.0, 15.0) and words[0].read_by == ReadBy.AI
    for bad in (
        "inget svar",
        json.dumps({"texter": [{"text": "113", "x": 1200, "y": 20, "b": 30, "h": 10}]}),
        json.dumps({"texter": [{"text": "", "x": 1, "y": 20, "b": 30, "h": 10}]}),
        json.dumps({"texter": [{"text": "1", "x": "1", "y": 2, "b": 3, "h": 4}]}),
        json.dumps({"texter": [{"text": "1", "x": 1, "y": 2, "b": 3, "h": 4}] * 700}),
    ):
        with pytest.raises(ritning_in.Unreadable):
            ritning_in.understand(bad, page)


def test_an_svg_drawing() -> None:
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
      <g stroke="#3a7bd5" stroke-width="1" fill="none">
        <line x1="10" y1="100" x2="390" y2="100"/>
        <path d="M 120 100 L 150 70 H 300"/>
      </g>
      <line x1="200" y1="62" x2="200" y2="78" stroke="red" stroke-width="3"/>
      <text x="112" y="116" font-size="9">7</text>
      <text x="230" y="64" font-size="9">Spår 2</text>
      <text x="20" y="120" font-size="9">Spår 1</text>
      <text x="204" y="60" font-size="9">Dvsi 9 (309)</text>
    </svg>""".encode()
    taken = ritning_in.take(svg)
    assert taken.format == "svg"
    made = ritning.assemble(ritning.read(taken.pages[0]), taken.pages[0])
    assert made.summary.switches == 1 and made.summary.boundaries == 1
    assert made.summary.line_exits == 2 and made.summary.buffer_stops == 1
    assert [s.number for s in made.graph.switches] == ["7"]
    signal = _signals(made.graph)["9"]
    assert (signal.signal, signal.address, signal.facing) == ("dvsi", 309, "west")


@pytest.mark.parametrize(
    ("data", "said"),
    [
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64, "HEIC"),
        (b"%PDF-1.4\nnot a pdf", "PDF:en kunde inte läsas"),
        (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "b">]><svg/>', "DOCTYPE"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><line", "SVG-filen kunde inte läsas"),
    ],
)
def test_the_intake_refuses(data: bytes, said: str) -> None:
    with pytest.raises(ritning_in.Refused) as refused:
        ritning_in.take(data)
    assert said in refused.value.message


def test_the_read_round_trips_as_the_contract() -> None:
    """R4: the read is the contract both ways; a read is always "schema", line exits only in a
    drawing, a symbol by a track that exists."""
    _, _, made = vector()
    read = DrawingRead(
        job=UUID("00000000-0000-4000-8000-000000000001"),
        page=1,
        kind=DrawingPageKind.VECTOR,
        graph=made.graph,
        boundaries=made.boundaries,
        questions=made.questions,
        summary=made.summary,
        price=DrawingPrice(tokens=0, why="vector", text="Gratis."),
        cost=0,
    )
    again = DrawingRead.model_validate_json(read.model_dump_json())
    assert again == read
    with pytest.raises(ValueError, match="ritningens koordinater"):
        DrawingRead.model_validate({**read.model_dump(), "graph": TrackGraph().model_dump()})
    exit_node = GraphNode(id="n1", type=NodeType.LINE_EXIT, at=(0.0, 0.0))
    with pytest.raises(ValueError, match="En modul har inga noder"):
        TrackGraph(geometry="mm", nodes=[exit_node])
    with pytest.raises(ValueError, match="står vid ett spår som inte finns"):
        TrackGraph(
            geometry="schema",
            symbols=[GraphSymbol(id="s1", kind=SymbolKind.UNKNOWN, at=(0, 0), piece="p9")],
        )


def test_the_underlay_is_the_drawing_drawn() -> None:
    page, _, _ = vector()
    pixels, transform = ritning.render(page, 1200)
    assert pixels.shape[1] == 1200 and transform[0] == pytest.approx(1200 / syn.WIDTH)
    raster_page, _ = raster(False)
    same, identity = ritning.render(raster_page)
    assert same is raster_page.pixels and identity == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def test_the_contracts_example_is_this_readers_read() -> None:
    """contracts/examples/exempelby.drawing-read.json is what this reader makes of the synthetic
    vector PDF: Studio's tests and the browser test's pretend CAD answer with it."""
    example = Path(__file__).resolve().parents[2] / "contracts/examples/exempelby.drawing-read.json"
    assert example.read_text(encoding="utf-8") == syn.example_read(), (
        "Kör: uv run python -m cad.bildkedjan.ritning_syntetisk avlasning "
        "contracts/examples/exempelby.drawing-read.json"
    )
