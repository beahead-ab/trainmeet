"""Import från AnyRail through CAD's API (#91, ANYRAIL-01–22): the upload, the reading again with
other measures, Skapa modulerna with the assembly, the exports, the rights, AR3's approval, and the
assembly in Studio's Från CAD with its track graph (TKL16, ANYRAIL-06)."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from cad import dxf
from cad.tests.anyrail_syntetisk import station_xml
from cad.tests.conftest import API, A, B, World
from cad.tests.test_assemblies_api import tkl_token

ANYRAIL = f"{API}/anyrail"


def upload(
    world: World,
    person: Any = A,
    data: bytes | None = None,
    name: str = "Exempelstation.xml",
    extra: dict[str, Any] | None = None,
) -> Any:
    return world.as_(person.id).post(
        ANYRAIL,
        files={
            "data": (None, json.dumps({"name": name, **(extra or {})}), "application/json"),
            "file": (name, data if data is not None else station_xml(), "application/xml"),
        },
    )


def made(world: World) -> dict[str, Any]:
    answer = upload(world)
    assert answer.status_code == 201, answer.text
    found: dict[str, Any] = answer.json()
    return found


def test_the_upload_proposes_the_modules_with_the_switches_and_the_checks(world: World) -> None:
    found = made(world)
    assert found["format"] == "xml" and found["scale"] == "H0" and found["revision"] == 1
    assert [m["number"] for m in found["modules"]] == ["1", "2a", "2b", "3", "Ä1", "Ä2"]
    assert [m["standard"] for m in found["modules"]] == [
        "1500 × 700",
        "1500 × 350",
        "1500 × 350",
        "1500 × 700",
        "700 × 355",
        "700 × 355",
    ]
    stats = found["stats"]
    assert (stats["switches"], stats["assumed"], stats["crossings"]) == (4, 1, 1)
    assumed = [s for s in found["switches"] if s["assumed"]]
    assert len(assumed) == 1 and assumed[0]["confirm"].startswith("switch_assumed:anyrail:")
    assert found["defaults"] == found["measures"]
    names = {f["file"] for f in found["files"]}
    assert {"exempelstation-anlaggning.dxf", "exempelstation-vaxlar.csv"} <= names
    # The page opens again from what was kept, without reading the file.
    again = world.as_(A.id).get(f"{ANYRAIL}/{found['id']}")
    assert again.status_code == 200 and again.json()["modules"] == found["modules"]


def test_other_measures_read_the_same_file_again_as_the_next_revision(world: World) -> None:
    found = made(world)
    client = world.as_(A.id)
    measures = {**found["measures"], "join_distance": 5.0}
    changed = client.put(
        f"{ANYRAIL}/{found['id']}", json={"base": 1, "scale": "H0", "measures": measures}
    )
    assert changed.status_code == 200, changed.text
    after = changed.json()
    assert after["revision"] == 2 and after["measures"]["join_distance"] == 5.0
    assert after["stats"]["gaps"] < found["stats"]["gaps"]
    stale = client.put(
        f"{ANYRAIL}/{found['id']}", json={"base": 1, "scale": "H0", "measures": measures}
    )
    assert stale.status_code == 409 and stale.json()["code"] == "changed"
    back = client.put(
        f"{ANYRAIL}/{found['id']}",
        json={"base": 2, "scale": "H0", "measures": found["defaults"]},
    )
    assert back.json()["modules"] == found["modules"]  # the same measures, the same answer


def test_the_exports_are_dxf_and_csv(world: World) -> None:
    found = made(world)
    client = world.as_(A.id)
    files = {f["url"].rsplit("/", 1)[-1]: f for f in found["files"]}
    station = client.get(files["anlaggning.dxf"]["url"])
    assert station.status_code == 200 and station.content.startswith(b"  0\r\nSECTION")
    read = dxf.read(station.content)
    assert read.of("LINE", "SPARMITT") and read.of("LINE", "ANYRAIL-RITNING")
    module = client.get(files[f"modul-{found['modules'][0]['key']}.dxf"]["url"])
    assert module.status_code == 200 and dxf.read(module.content).of("TEXT", "GAVEL")
    switches = client.get(files["vaxlar.csv"]["url"]).content.decode("utf-8-sig").splitlines()
    assert switches[0] == "nr;anyrail_id;typ;radie_mm;modul;antagen;x_mm;y_mm"
    assert len(switches) == 5 and switches[4].endswith(";ja;4800;197")
    gables = client.get(files["gavelprofiler.csv"]["url"]).content.decode("utf-8-sig")
    assert gables.splitlines()[0] == "skarv;skarvlangd_mm;spar_mm_fran_bakkant_kant1;snett_grader"
    assert "Ä1|1;355;140 197;0.0 0.0" in gables
    assert client.get(f"{ANYRAIL}/{found['id']}/files/annat.txt").status_code == 404


def test_only_the_one_who_uploaded_sees_the_file(world: World) -> None:
    found = made(world)
    theirs = world.as_(B.id)
    assert theirs.get(f"{ANYRAIL}/{found['id']}").status_code == 404
    assert theirs.get(f"{ANYRAIL}/{found['id']}/files/vaxlar.csv").status_code == 404
    assert (
        theirs.put(
            f"{ANYRAIL}/{found['id']}",
            json={"base": 1, "scale": "H0", "measures": found["measures"]},
        ).status_code
        == 404
    )
    ask = {"base": 1, "modules": [{"key": "m1", "name": "Modul 1"}]}
    assert theirs.post(f"{ANYRAIL}/{found['id']}/create", json=ask).status_code == 404
    assert world.browser().get(f"{ANYRAIL}/{found['id']}").status_code == 401


def test_a_file_that_is_not_anyrail_is_refused_with_why(world: World) -> None:
    for data in (b"inte en ritning", b'<?xml version="1.0"?><!DOCTYPE layout []><layout/>'):
        refused = upload(world, data=data)
        assert refused.status_code == 422, refused.text
        assert refused.json()["message"].startswith("Filen gick inte att läsa som AnyRail")
    empty = upload(world, data=b"")
    assert empty.status_code == 422


def test_create_makes_drafts_and_an_assembly_and_studio_gets_the_graph(world: World) -> None:
    found = made(world)
    client = world.as_(A.id)
    assumed = next(s for s in found["switches"] if s["assumed"])
    chosen = [{"key": m["key"], "name": f"Exempel {m['number']}"} for m in found["modules"]]
    ask = {"base": 1, "modules": chosen, "confirmed": [], "assembly": "Exempelstation"}
    created = client.post(f"{ANYRAIL}/{found['id']}/create", json=ask)
    assert created.status_code == 200, created.text
    result = created.json()
    assert [m["name"] for m in result["modules"]] == [c["name"] for c in chosen]
    assert {m["status"] for m in result["modules"]} == {"draft"}
    again = client.post(f"{ANYRAIL}/{found['id']}/create", json=ask)
    assert again.status_code == 409
    assert (
        client.get(f"{ANYRAIL}/{found['id']}").json()["created"]["assembly"] == result["assembly"]
    )

    # The modules are drafts with the AnyRail graph; AnyRail's ids stay as the origin.
    by_number = dict(zip([m["number"] for m in found["modules"]], result["modules"], strict=True))
    three = client.get(f"{API}/modules/{by_number['3']['id']}").json()
    assert three["drawing"]["source"] == "anyrail"
    assert all(
        p["origin"]["source"] == "anyrail" and p["origin"]["ref"] for p in three["graph"]["pieces"]
    )
    yellow = [c for c in three["checks"] if c["kind"] == "switch_assumed"]
    assert len(yellow) == 1 and yellow[0]["assumed"] and yellow[0]["answer"] is None

    # AR3: the module with an unconfirmed assumed switch is not approved.
    refused = client.post(f"{API}/modules/{by_number['3']['id']}/approve", json={"version": 1})
    assert refused.status_code == 422, refused.text

    # The assembly places the modules as in the drawing, and its graph joins them.
    assembly = client.get(f"{API}/assemblies/{result['assembly']}").json()
    assert assembly["name"] == "Exempelstation" and len(assembly["modules"]) == 6
    assert any("utkast" in p for p in assembly["problems"])
    graph = assembly["graph"]
    ends = Counter(e for p in graph["pieces"] for e in (p["start"], p["end"]))
    joints = [n for n in graph["nodes"] if n["type"] == "module_joint"]
    assert sum(1 for n in joints if ends[n["id"]] == 2) >= 9  # the gables met, track by track
    assert [n for n in joints if ends[n["id"]] == 1] and len(graph["switches"]) == 4

    # Confirmed in the import, the switch is answered; then every module may be approved.
    fresh = made(world)
    ask = {
        "base": 1,
        "modules": [{"key": m["key"], "name": f"Andra {m['number']}"} for m in fresh["modules"]],
        "confirmed": [s["confirm"] for s in fresh["switches"] if s["assumed"]],
    }
    second = client.post(f"{ANYRAIL}/{fresh['id']}/create", json=ask).json()
    for module in second["modules"]:
        checks = client.get(f"{API}/modules/{module['id']}/checks").json()
        assert not [c for c in checks if c["kind"] == "switch_assumed" and c["answer"] is None]
        answers = [
            {"op": "answer", "key": c["key"], "answer": c["choices"][-1]["id"]}
            for c in checks
            if c["answer"] is None
        ]
        if answers:
            edit = {"base": 1, "operations": answers}
            done = client.post(f"{API}/modules/{module['id']}/drawing/approve", json=edit)
        else:
            done = client.post(f"{API}/modules/{module['id']}/approve", json={"version": 1})
        assert done.status_code == 200, done.text
    confirmed = [
        c
        for module in second["modules"]
        for c in client.get(f"{API}/modules/{module['id']}").json()["drawing"]["answers"]
        if c["key"].startswith("switch_assumed:anyrail:")
    ]
    assert confirmed and confirmed[0]["by"]
    # Studio's Från CAD lists both assemblies: the first not ready while its modules are drafts.
    headers = {"Authorization": f"Bearer {tkl_token(world, A.id)}"}
    with world.browser() as browser:
        sources = browser.get(f"{API}/studio", headers=headers).json()["sources"]
        first = next(s for s in sources if s["id"] == result["assembly"])
        assert not first["ready"] and first["problems"]
        graph_of = browser.get(f"{API}/studio/assembly/{second['assembly']}", headers=headers)
        assert graph_of.status_code == 200, graph_of.text
        studio = graph_of.json()
    assert studio["source"]["kind"] == "assembly" and len(studio["source"]["modules"]) == 6
    assert {p["origin"]["source"] for p in studio["graph"]["pieces"]} == {"anyrail"}
    assert assumed["number"] in {int(s["number"]) for s in studio["graph"]["switches"]}
