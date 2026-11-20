"""CAD:s anläggning som underlag (K4, CAD-11): the client against a pretend CAD, and the reading of
a synthetic assembly into places and the lengths between them, exact to the mm."""

from __future__ import annotations

import json
import math
from uuid import UUID

import httpx
import pytest

from contracts.cad import ArcSegment, LineSegment
from integrationer import cad_assembly, cad_example

TOKEN = "personens-token"


def test_two_stations_and_the_line_between_give_places_and_exact_lengths() -> None:
    layout = cad_assembly.read(cad_example.assembly_bytes(), "u-cad")
    assert (layout.name, layout.revision, layout.scale, layout.ratio) == (
        "Provträffens anläggning",
        3,
        "H0",
        87,
    )
    assert [(p.name, p.modules, p.station_ids) for p in layout.places] == [
        ("Aby", ["M-001 Aby station"], ["aby"]),
        ("Bby", ["M-004 Bby station"], ["bby"]),
        ("Cby", ["M-006 Cby station"], ["cby"]),
    ]
    aby, bby, cby = (p.id for p in layout.places)
    assert layout.places[1].at.x == pytest.approx(5433.3, abs=0.1)
    # Aby – Bby on two tracks, 1 500 + 1 000 mm each; Bby – Cby on one, 1 200 mm.
    assert [(link.a, link.b, link.length, link.tracks, link.modules) for link in layout.links] == [
        (aby, bby, 2500.0, 2, ["M-002 Linje 1", "M-003 Linje 2"]),
        (bby, cby, 1200.0, 1, ["M-005 Linje 3"]),
    ]
    # Through Bby on its straight track, never back through its switch: 1 200 + 800 mm.
    [through] = layout.through
    assert (through.place, through.length) == (bby, 2000.0)
    # The same bytes always give the same reading (IMPORT-15).
    assert cad_assembly.read(cad_example.assembly_bytes(), "u-cad") == layout


def test_without_stations_the_modules_with_switches_are_the_places() -> None:
    layout = cad_assembly.read(cad_example.assembly_bytes(stations=False), "u-cad")
    assert [p.name for p in layout.places] == [
        "M-001 Aby station",
        "M-004 Bby station",
        "M-006 Cby station",
    ]
    assert [p.stations for p in layout.places] == [[], [], []]
    assert [link.length for link in layout.links] == [2500.0, 1200.0]


def test_an_arc_is_as_long_as_its_angle_and_a_line_as_its_ends() -> None:
    quarter = ArcSegment(start=(1000, 0), end=(0, 1000), center=(0, 0), radius=1000, clockwise=True)
    assert cad_assembly.segment_length(quarter) == pytest.approx(math.pi * 500)
    back = quarter.model_copy(update={"clockwise": False})
    assert cad_assembly.segment_length(back) == pytest.approx(math.pi * 1500)
    assert cad_assembly.segment_length(LineSegment(start=(0, 0), end=(300, 400))) == 500


def test_something_else_than_an_assembly_is_refused() -> None:
    with pytest.raises(cad_assembly.AssemblyError):
        cad_assembly.read(b'{"format": "trainmeet.meet/1"}', "u-cad")


def pretend_cad(seen: list[httpx.Request]) -> httpx.Client:
    """CAD as the hub reaches it: the person's assemblies and one of them, with the token."""
    body = cad_example.assembly_bytes()

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"code": "login", "message": "Logga in."})
        path = request.url.path
        if path == "/api/cad/1/meet/assemblies":
            brief = {
                "id": str(cad_example.ASSEMBLY),
                "name": "Provträffens anläggning",
                "owner": {"kind": "person", "id": str(UUID(int=7)), "name": "Planeraren"},
                "scale": "H0",
                "modules": 6,
                "problems": 0,
                "revision": 3,
                "changed_at": "2026-11-20T10:00:00Z",
                "may_edit": True,
            }
            return httpx.Response(200, json=[brief])
        if path == f"/api/cad/1/meet/assemblies/{cad_example.ASSEMBLY}":
            return httpx.Response(200, content=body)
        if path.endswith("/00000000-0000-4000-8000-000000000bad"):
            return httpx.Response(
                422, json={"code": "invalid", "message": "En modul syns inte för dig."}
            )
        return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})

    return httpx.Client(transport=httpx.MockTransport(answer))


def test_the_client_asks_cad_with_the_planners_token() -> None:
    seen: list[httpx.Request] = []
    client = cad_assembly.CadClient("http://cad.invalid/", pretend_cad(seen))
    [brief] = client.assemblies(TOKEN)
    assert (brief.id, brief.revision) == (cad_example.ASSEMBLY, 3)
    body = client.assembly(TOKEN, cad_example.ASSEMBLY)
    assert json.loads(body)["format"] == "trainmeet.cad-assembly/1"
    assert [str(r.url) for r in seen] == [
        "http://cad.invalid/api/cad/1/meet/assemblies",
        f"http://cad.invalid/api/cad/1/meet/assemblies/{cad_example.ASSEMBLY}",
    ]
    with pytest.raises(cad_assembly.CadError) as refused:
        client.assemblies("en-annan-token")
    assert refused.value.status == 401
    with pytest.raises(cad_assembly.CadError) as gone:
        client.assembly(TOKEN, UUID(int=5))
    assert gone.value.status == 404
    with pytest.raises(cad_assembly.CadError, match="syns inte") as unseen:
        client.assembly(TOKEN, UUID("00000000-0000-4000-8000-000000000bad"))
    assert unseen.value.status == 422


def test_a_cad_that_does_not_answer_is_said_plainly() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nej", request=request)

    client = cad_assembly.CadClient(
        "http://cad.invalid", httpx.Client(transport=httpx.MockTransport(down))
    )
    with pytest.raises(cad_assembly.CadError, match="svarar inte") as error:
        client.assemblies(TOKEN)
    assert error.value.status == 502
