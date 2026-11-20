"""Exportera's files (#89 del d1, CAD-07, CAD-24) without the database: DXF R12 with real LINE and
ARC read back and checked against the geometry within 0,01 mm, the FREMO sheet, the print, the
module database's record and CSV, and the MMM measures."""

from __future__ import annotations

import csv
import io
import math
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cad import curves, dxf, export, geometry, graph, sheets
from cad.bildkedjan import syntetisk
from cad.geometry import from_chord
from cad.landscapes import Shown
from contracts.cad import (
    EXPORT_FILES,
    RECORD_COLUMNS,
    SURFACE_COLOURS,
    SURFACE_NAMES,
    Curve,
    Gable,
    GableEnd,
    GableLabel,
    GraphNode,
    GraphPiece,
    Landscape,
    LandscapeArea,
    LandscapeEdit,
    LandscapeMethod,
    LandscapeStatus,
    Module,
    ModuleRecord,
    ModuleStatus,
    Norm,
    Owner,
    OwnerKind,
    Scale,
    Shape,
    Straight,
    Surface,
    SurfaceTotal,
    TrackGraph,
    Trapezoid,
    Visibility,
)
from contracts.station_model import NodeType, Point

CLOSE = 0.01
"""mm: how close an entity read back from the DXF lies to the geometry."""


def module_of(
    shape: Shape,
    gables: list[Gable],
    built: TrackGraph | None = None,
    status: ModuleStatus = ModuleStatus.DRAFT,
    name: str = "Provmodul",
) -> Module:
    built = built if built is not None else graph.from_measures(shape, gables)
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    return Module(
        id=uuid.UUID("7d1c3b2a-1e0f-4a5b-8c9d-0e1f2a3b4c5d"),
        number="M-007",
        name=name,
        owner=Owner(kind=OwnerKind.PERSON, id=uuid.uuid4(), name="Provkonto A"),
        visibility=Visibility.ME,
        scale=Scale.H0,
        shape=shape,
        gables=[
            GableLabel(
                end=g.end,
                label="MMM dubbelspår" if g.norm else "Egen gavel",
                norm=g.norm,
                profile=g.profile,
                tracks=list(g.tracks),
            )
            for g in gables
        ],
        graph=built,
        status=status,
        version=3,
        track_length=graph.track_length(built),
        changed_at=now,
        created_at=now,
        approved_at=now if status == ModuleStatus.APPROVED else None,
        may_edit=True,
        latest=3,
    )


def mmm_gables(tracks: list[float] | None = None) -> list[Gable]:
    tracks = tracks or [140, 197]
    return [
        Gable(end=GableEnd.A, norm=Norm.MMM, profile="h0-mmm-dubbelspar", tracks=tracks),
        Gable(end=GableEnd.B, norm=Norm.MMM, profile="h0-mmm-dubbelspar", tracks=tracks),
    ]


def trapezoid_graph() -> tuple[Trapezoid, list[Gable], TrackGraph]:
    """MMM's trapezoid with the photo test's track: straight, R 645, straight 19°, R 645,
    straight (syntetisk.trapezoid_scene), as LINE and ARC."""
    scene = syntetisk.trapezoid_scene()
    segs = scene.routes[0]
    shape = Trapezoid(
        length=scene.length, width_a=scene.width_a, width_b=scene.width_b, offset=scene.offset
    )
    gables = [
        Gable(end=GableEnd.A, tracks=scene.gables_a),
        Gable(end=GableEnd.B, tracks=scene.gables_b),
    ]
    built = TrackGraph(
        nodes=[
            GraphNode(
                id="n1", type=NodeType.MODULE_JOINT, at=segs[0].start, gable=GableEnd.A, track=1
            ),
            GraphNode(
                id="n2", type=NodeType.MODULE_JOINT, at=segs[-1].end, gable=GableEnd.B, track=1
            ),
        ],
        pieces=[
            GraphPiece(id="p1", start="n1", end="n2", segments=[curves.segment(s) for s in segs])
        ],
        issued=3,
    )
    return shape, gables, built


def ends_match(found: tuple[Point, Point], expected: tuple[Point, Point]) -> bool:
    a, b = found
    c, d = expected
    return (math.dist(a, c) <= CLOSE and math.dist(b, d) <= CLOSE) or (
        math.dist(a, d) <= CLOSE and math.dist(b, c) <= CLOSE
    )


def test_the_dxf_has_the_track_centres_as_real_line_and_arc_within_a_hundredth() -> None:
    shape, gables, built = trapezoid_graph()
    module = module_of(shape, gables, built)
    data = export.module_dxf(module, None)
    head = data.decode("cp1252").splitlines()[:4]
    assert [line.strip() for line in head] == ["0", "SECTION", "2", "HEADER"]
    read = dxf.read(data)
    assert read.version == "AC1009"
    assert {"MODUL", "KANT1", "GAVEL", "SPARMITT", "TEXT", "MATT", "UTKAST"} <= set(read.layers)
    segments = built.pieces[0].segments
    lines = read.of("LINE", "SPARMITT")
    arcs = read.of("ARC", "SPARMITT")
    assert len(lines) == sum(s.kind == "line" for s in segments) == 3
    assert len(arcs) == sum(s.kind == "arc" for s in segments) == 2
    for seg in segments:
        if seg.kind == "line":
            assert any(ends_match((e.point(10), e.point(11)), (seg.start, seg.end)) for e in lines)
        else:
            match = [e for e in arcs if ends_match(dxf.arc_ends(e), (seg.start, seg.end))]
            assert len(match) == 1, seg
            assert match[0].number(40) == pytest.approx(seg.radius, abs=CLOSE)
            assert math.dist(match[0].point(10), seg.center) <= CLOSE
            assert seg.radius == pytest.approx(645, abs=CLOSE)
    # The outline: four lines, Kant 1 on its own layer; the gable marks at 140 from Kant 1.
    assert len(read.of("LINE", "KANT1")) == 1 and len(read.of("LINE", "MODUL")) == 3
    marks = read.of("TEXT", "GAVEL")
    assert {"140", "A", "B"} <= {m.values[1][0] for m in marks}
    # A draft says so.
    assert any(t.values[1][0] == "UTKAST" for t in read.of("TEXT", "UTKAST"))


def test_a_curve_module_is_arcs_all_through_and_the_rails_follow_the_centre() -> None:
    bend = from_chord(1035, 68)
    shape = Curve(radius=bend.radius, angle=bend.angle, width=500)
    gables = [Gable(end=GableEnd.A, tracks=[200, 250]), Gable(end=GableEnd.B, tracks=[200, 250])]
    module = module_of(shape, gables, status=ModuleStatus.APPROVED)
    read = dxf.read(export.module_dxf(module, None, rails=True))
    centres = read.of("ARC", "SPARMITT")
    assert len(centres) == 2 and not read.of("LINE", "SPARMITT")
    radii = sorted(e.number(40) for e in centres)
    assert radii[1] == pytest.approx(bend.radius, abs=CLOSE)  # track 1, exact (CAD16)
    assert radii[0] == pytest.approx(bend.radius - 50, abs=CLOSE)
    for arc in centres:
        a, b = dxf.arc_ends(arc)
        assert (
            abs(
                math.degrees(
                    math.atan2(-(b[1] - arc.point(10)[1]), b[0] - arc.point(10)[0])
                    - math.atan2(-(a[1] - arc.point(10)[1]), a[0] - arc.point(10)[0])
                )
                % 360
                - bend.angle
            )
            <= 1e-6
        )
    half = (16.5 + 1.0) / 2
    rails = sorted(e.number(40) for e in read.of("ARC", "RALS"))
    assert rails == pytest.approx(sorted(r + s * half for r in radii for s in (-1, 1)), abs=CLOSE)
    # Kant 1 and the far side are arcs; the gables lines. Approved: no UTKAST.
    track1 = 200
    assert read.of("ARC", "KANT1")[0].number(40) == pytest.approx(
        geometry.edge_radius(shape, track1), abs=CLOSE
    )
    assert len(read.of("ARC", "MODUL")) == 1 and len(read.of("LINE", "MODUL")) == 2
    assert "UTKAST" not in read.layers
    assert any("R 2003,2" in t.values[1][0].replace(".", ",") for t in read.of("TEXT", "MATT"))


def test_a_placed_module_is_shifted_and_turned_as_in_an_assembly() -> None:
    shape = Straight(length=1000, width=400)
    gables = [Gable(end=GableEnd.A, tracks=[140]), Gable(end=GableEnd.B, tracks=[140])]
    built = graph.from_measures(shape, gables)
    doc = dxf.Dxf()
    place = dxf.Placement(at=(2000.0, 500.0), angle=90.0)
    dxf.draw_module(doc, shape, gables, built, Scale.H0, place)
    read = dxf.read(doc.write())
    (centre,) = read.of("LINE", "SPARMITT")
    # Turned a quarter counterclockwise as the drawing shows it: gable B lies above gable A.
    assert math.dist(centre.point(10), (2140.0, 500.0)) <= CLOSE
    assert math.dist(centre.point(11), (2140.0, -500.0)) <= CLOSE
    assert place.point((1000.0, 140.0)) == pytest.approx((2140.0, -500.0))


def test_texts_and_landscape_in_the_dxf() -> None:
    shape = Straight(length=800, width=400)
    gables = mmm_gables([140])
    module = module_of(shape, gables, name="Ängen – norra ≈ 2")
    pond = LandscapeArea(
        surface=Surface.WATER,
        outline=[(500.0, 250.0), (600.0, 250.0), (600.0, 330.0), (500.0, 330.0)],
        area=8000,
    )
    shown = Shown([pond], [[(0.0, 117.0), (800.0, 117.0), (800.0, 163.0), (0.0, 163.0)]], [])
    data = export.module_dxf(module, shown)
    read = dxf.read(data)
    (water,) = read.of("POLYLINE", "LANDSKAP-VATTEN")
    assert water.values[70] == ["1"] and water.vertices[2] == pytest.approx((600.0, 330.0))
    assert len(read.of("POLYLINE", "LANDSKAP-BALLAST")) == 1
    title = next(t for t in read.of("TEXT", "TEXT") if t.values[1][0].startswith("M-007"))
    assert title.values[1][0] == "M-007 Ängen – norra \\U+2248 2 · version 3 · utkast"
    assert "Ängen".encode("cp1252") in data


def test_the_fremo_sheet_has_the_plan_the_measures_and_the_gables() -> None:
    shape = Straight(length=1500, width=600)
    module = module_of(shape, mmm_gables(), status=ModuleStatus.APPROVED, name="Exempel & Co")
    svg = sheets.fremo_sheet(module)
    root = ET.fromstring(svg)
    assert root.get("width") == "297mm" and root.get("viewBox") == "0 0 297 210"
    texts = [t.text or "" for t in root.iter("{http://www.w3.org/2000/svg}text")]
    for expected in (
        "1500",
        "600",
        "140",
        "57",
        "Gavel A sedd utifrån · 1:10",
        "KANT 1",
        "Exempel & Co",
        "M-007 · version 3",
        "Ritningen 1:10",
    ):
        assert expected in texts, expected
    assert "MMM dubbelspår · MMM" in texts
    assert not any("UTKAST" in t for t in texts)
    draft = sheets.fremo_sheet(module.model_copy(update={"status": ModuleStatus.DRAFT}))
    assert "UTKAST" in draft and "UTKAST, INTE GODKÄND" in draft


def test_the_print_has_the_landscape_and_its_legend() -> None:
    module = module_of(Straight(length=800, width=400), mmm_gables([140]))
    pond = LandscapeArea(
        surface=Surface.WATER, outline=[(500.0, 250.0), (600.0, 250.0), (600.0, 330.0)], area=4000
    )
    totals = [
        SurfaceTotal(surface=Surface.GRASS, area=250_000, share=0.78),
        SurfaceTotal(surface=Surface.WATER, area=4_000, share=0.0125),
    ]
    svg = sheets.print_sheet(module, sheets.SheetLandscape([pond], [], totals))
    root = ET.fromstring(svg)
    texts = [t.text or "" for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert {"Landskapet", "Gräs", "Vatten", "0,25 m² · 78 %", "UTKAST"} <= set(texts)
    assert 'fill="#5b8fc7"' in svg


def test_the_module_database_record_and_its_csv() -> None:
    shape = Straight(length=1500, width=600)
    module = module_of(shape, mmm_gables(), status=ModuleStatus.APPROVED, name="=SUM(A1)")
    found = export.record(module, landscape=True)
    assert found.format == "trainmeet.cad.moduldatabas/1"
    assert (found.length, found.radius, found.switches, found.landscape) == (1500, None, 0, True)
    assert [g.width for g in found.gables] == [600, 600]
    rows = list(csv.reader(io.StringIO(export.record_csv(found).decode())))
    assert rows[0] == list(RECORD_COLUMNS)
    row = dict(zip(rows[0], rows[1], strict=True))
    assert row["format"] == "trainmeet.cad.moduldatabas/1"
    assert row["name"] == "'=SUM(A1)"  # never a formula in a spreadsheet
    assert row["gable_a_tracks"] == "140/197" and row["gable_b_norm"] == "mmm"
    assert row["status"] == "approved" and row["radius"] == ""


def test_the_mmm_measures_against_mmms_positions() -> None:
    shape = Straight(length=1200, width=480)
    gables = [
        Gable(end=GableEnd.A, norm=Norm.MMM, profile="h0-mmm-fyrspar", tracks=[140, 197, 283, 340]),
        Gable(end=GableEnd.B, norm=Norm.FREMO, tracks=[150, 210]),
    ]
    module = module_of(shape, gables)
    a, b = export.mmm(module)
    assert [(t.from_kant1, t.spacing, t.mmm, t.deviation) for t in a.tracks] == [
        (140, None, 140, 0),
        (197, 57, 197, 0),
        (283, 86, 283, 0),
        (340, 57, 340, 0),
    ]
    assert [(t.spacing, t.mmm) for t in b.tracks] == [(None, None), (60, None)]
    rows = list(csv.DictReader(io.StringIO(export.mmm_csv(module).decode())))
    assert len(rows) == 6 and rows[1]["avstand_till_forra_mm"] == "57"
    assert rows[0]["status"] == "utkast"
    off = module_of(shape, mmm_gables([143, 200]))
    assert [t.deviation for t in export.mmm(off)[0].tracks] == [3, 3]


def test_file_names_are_plain() -> None:
    module = module_of(Straight(length=800, width=400), mmm_gables([140]), name="Ängen östra")
    assert export.file_stem(module) == "M-007-angen-ostra-v3"
    assert export.disposition("M-007-ä.dxf") == (
        "attachment; filename=\"M-007-?.dxf\"; filename*=UTF-8''M-007-%C3%A4.dxf"
    )


def test_the_landscape_and_export_contracts_round_trip() -> None:
    edit = LandscapeEdit.model_validate(
        {
            "base": 2,
            "operations": [
                {"op": "paint", "surface": "water", "radius": 20, "points": [[1, 2], [3, 4]]},
                {"op": "erase", "radius": 5, "points": [[1, 2]]},
                {"op": "fill", "surface": "grass", "at": [10, 20]},
            ],
        }
    )
    assert [type(o).__name__ for o in edit.operations] == [
        "PaintLandscape",
        "EraseLandscape",
        "FillLandscape",
    ]
    assert LandscapeEdit.model_validate_json(edit.model_dump_json()) == edit
    for bad in (
        {"op": "paint", "surface": "water", "radius": 0, "points": [[1, 2]]},
        {"op": "paint", "surface": "lava", "radius": 5, "points": [[1, 2]]},
        {"op": "erase", "radius": 5, "points": []},
        {"op": "flood", "at": [1, 2]},
    ):
        with pytest.raises(ValidationError):
            LandscapeEdit.model_validate({"base": 1, "operations": [bad]})
    shape = Straight(length=1500, width=600)
    module = module_of(shape, mmm_gables(), status=ModuleStatus.APPROVED)
    found = export.record(module, landscape=False)
    assert ModuleRecord.model_validate_json(found.model_dump_json()) == found
    flat = set(found.model_dump()) - {"gables"}
    gables = {f"gable_{e}_{k}" for e in "ab" for k in ("norm", "profile", "width", "tracks")}
    assert set(RECORD_COLUMNS) == flat | gables
    infos = [SURFACE_NAMES[s] for s in Surface]
    assert (
        infos[:3] == ["Gräs", "Ballast", "Mark och väg"] and len(set(SURFACE_COLOURS.values())) == 9
    )
    shown = Landscape(
        module=module.id,
        version=3,
        latest=3,
        status=LandscapeStatus.PROPOSAL,
        method=LandscapeMethod.COLOUR,
        areas=[LandscapeArea(surface=Surface.WATER, outline=[(0, 0), (10, 0), (10, 10)], area=50)],
        may_edit=True,
    )
    assert Landscape.model_validate_json(shown.model_dump_json()) == shown
    assert set(EXPORT_FILES) == {
        "fremo.svg",
        "utskrift.svg",
        "moduldatabas.json",
        "moduldatabas.csv",
        "mmm.csv",
        "modul.dxf",
    }
