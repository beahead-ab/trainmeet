"""Landskapet and Exportera through CAD's API (#89 del d1, CAD-04, CAD-05, CAD-07, CAD-08, CAD-17,
CAD-18, CAD-21, CAD-33): made from the measuring image, painted, saved as versions, approved, and
exported; who may do what.

The measuring image is the synthetic one (cad/tests/landskap_bild.py), put on the version as the
photo chain leaves it (a done job with its measuring image and display copy), so the tests need
not run the chain."""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

import cv2
from psycopg.types.json import Jsonb

from cad.store import new_key
from cad.tests import landskap_bild
from cad.tests.conftest import API, A, B, World, straight
from cad.tests.test_library import make


def photographed(world: World, module: dict[str, Any], version: int) -> None:
    """The version's track plan as if it came from the synthetic measuring image."""
    pixels, _ = landskap_bild.image()
    owner = uuid.UUID(module["owner"]["id"])
    store = world.app.state.photos.store
    job = uuid.uuid4()
    h, w = pixels.shape[:2]
    small = cv2.resize(pixels, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    with world.app.state.db.transaction() as conn:
        conn.execute(
            "INSERT INTO photo_job (id, module_id, owner_kind, owner_id, person_id, person_name, "
            "key, state, start, result, chain) VALUES (%s, %s, 'person', %s, %s, 'Provkonto A', "
            "%s, 'done', '{}', %s, 'prov')",
            (job, module["id"], owner, owner, "a" * 64, Jsonb({"grid": [0, 0, 2.0, w, h]})),
        )
        for kind, image in (("measure", pixels), ("display", small)):
            key = new_key(owner, "png")
            data = cv2.imencode(".png", image)[1].tobytes()
            store.put(key, data)
            conn.execute(
                "INSERT INTO photo_file (key, job_id, owner_id, kind, bytes, width, height, "
                "counted) VALUES (%s, %s, %s, %s, %s, %s, %s, true)",
                (key, job, owner, kind, len(data), image.shape[1], image.shape[0]),
            )
        conn.execute(
            "UPDATE module_version SET drawing = jsonb_set(drawing, '{photo}', to_jsonb(%s::text)) "
            "WHERE module_id = %s AND version = %s",
            (str(job), module["id"], version),
        )


def synthetic(world: World) -> dict[str, Any]:
    made = make(world, straight("Landskapsprov", length=800, width=400, a=[140]))
    photographed(world, made, 1)
    return made


def test_a_landscape_from_the_measuring_image_is_a_proposal_until_approved(world: World) -> None:
    made = synthetic(world)
    client = world.as_(A.id)
    url = f"{API}/modules/{made['id']}/landscape"
    assert (
        client.post(f"{API}/modules/{made['id']}/approve", json={"version": 1}).status_code == 200
    )
    before = client.get(url).json()
    assert before["status"] == "none" and before["may_edit"] and before["photo"]["url"]
    assert len(before["track_bed"]) == 1 and len(before["surfaces"]) == 9

    proposal = client.post(f"{url}/make", json={"base": 1}).json()
    assert (proposal["status"], proposal["version"], proposal["saved_in"]) == ("proposal", 2, 2)
    assert (proposal["method"], proposal["made_by"]) == ("colour", "Färgklustring 1")
    surfaces = {t["surface"] for t in proposal["totals"]}
    assert surfaces == {
        "grass",
        "ballast",
        "ground",
        "platform",
        "water",
        "building",
        "trees",
        "path",
    }
    assert not any(a["painted"] for a in proposal["areas"])
    module = client.get(f"{API}/modules/{made['id']}").json()
    assert (module["latest"], module["status"], module["approved_version"]) == (2, "draft", 1)
    assert module["graph"] == made["graph"] and module["drawing"]["photo"]
    history = client.get(f"{API}/modules/{made['id']}/history").json()
    assert history[0]["text"] == "Version 2: landskapet gjort ur mätbilden (Färgklustring 1)"

    # Paint a pond on the grass: shown, not saved.
    pond = {"op": "paint", "surface": "water", "radius": 30, "points": [[260, 300], [320, 300]]}
    shown = client.post(url, json={"base": 2, "operations": [pond]}).json()
    assert shown["changed"] and shown["status"] == "proposal"
    assert any(a["painted"] and a["surface"] == "water" for a in shown["areas"])
    assert client.get(f"{API}/modules/{made['id']}").json()["latest"] == 2
    stale = client.post(f"{url}/save", json={"base": 1, "operations": [pond]})
    assert stale.status_code == 409 and stale.json()["code"] == "changed"
    nothing = client.post(f"{url}/save", json={"base": 2, "operations": []})
    assert nothing.status_code == 422

    saved = client.post(f"{url}/save", json={"base": 2, "operations": [pond]}).json()
    assert (saved["version"], saved["saved_in"], saved["status"]) == (3, 3, "proposal")
    history = client.get(f"{API}/modules/{made['id']}/history").json()
    assert history[0]["text"] == "Version 3: landskapet ändrat (ett drag målat)"
    approved = client.post(f"{url}/approve", json={"base": 3, "operations": []}).json()
    assert (approved["status"], approved["version"]) == ("approved", 3)
    module = client.get(f"{API}/modules/{made['id']}").json()
    assert (module["status"], module["approved_version"]) == ("approved", 3)

    # The older versions keep their own: none in version 1, the unapproved proposal in 2.
    assert client.get(f"{url}?version=1").json()["status"] == "none"
    assert client.get(f"{url}?version=2").json()["status"] == "proposal"
    assert client.get(f"{url}?version=9").status_code == 404


def test_who_sees_the_module_sees_its_landscape_and_only_the_owner_paints(world: World) -> None:
    made = synthetic(world)
    url = f"{API}/modules/{made['id']}/landscape"
    other = world.as_(B.id)
    assert other.get(url).status_code == 404
    world.as_(A.id).put(f"{API}/modules/{made['id']}/visibility", json={"visibility": "all"})
    seen = other.get(url).json()
    assert seen["status"] == "none" and not seen["may_edit"]
    for path, body in (("/make", {"base": 1}), ("", {"base": 1}), ("/save", {"base": 1})):
        assert other.post(url + path, json=body).status_code == 403
    assert world.browser().get(url).status_code == 401


def test_a_module_without_a_photo_gets_an_empty_landscape_to_paint(world: World) -> None:
    made = make(world, straight("Handmålad", length=800, width=400, a=[140]))
    client = world.as_(A.id)
    url = f"{API}/modules/{made['id']}/landscape"
    refused = client.post(url, json={"base": 1, "operations": []})
    assert refused.status_code == 422 and "Gör landskapet först" in refused.json()["message"]
    empty = client.post(f"{url}/make", json={"base": 1}).json()
    assert (empty["method"], empty["made_by"], empty["areas"]) == ("hand", "Målat för hand", [])
    assert [t["surface"] for t in empty["totals"]] == ["ballast"]
    ops = [
        {"op": "fill", "surface": "grass", "at": [400, 300]},
        {"op": "paint", "surface": "ground", "radius": 15, "points": [[0, 380], [800, 380]]},
    ]
    saved = client.post(f"{url}/save", json={"base": 2, "operations": ops}).json()
    kinds = sorted((a["surface"], a["painted"]) for a in saved["areas"])
    assert kinds == [("grass", True), ("ground", True)]
    track = client.post(
        url, json={"base": 3, "operations": [{"op": "fill", "surface": "water", "at": [400, 140]}]}
    )
    assert track.status_code == 422
    assert track.json()["message"] == "Fyll i en yta på modulen, inte på spåret eller utanför."


def test_later_versions_keep_the_landscape_and_approval_waits_for_att_kolla(world: World) -> None:
    made = make(world, straight("Öppen", a=[], width=700))
    client = world.as_(A.id)
    drawn = client.post(
        f"{API}/modules/{made['id']}/drawing/save",
        json={"base": 1, "operations": [{"op": "line", "start": [100, 300], "end": [900, 300]}]},
    )
    assert drawn.status_code == 200
    url = f"{API}/modules/{made['id']}/landscape"
    client.post(f"{url}/make", json={"base": 2})
    refused = client.post(f"{url}/approve", json={"base": 3, "operations": []})
    assert refused.status_code == 422 and "saker att kolla" in refused.json()["message"]
    # A new version of the measures keeps the landscape it does not change.
    module = client.get(f"{API}/modules/{made['id']}").json()
    renamed = client.put(
        f"{API}/modules/{made['id']}",
        json={
            "base": 3,
            "name": "Öppen, omdöpt",
            "scale": "H0",
            "shape": module["shape"],
            "gables": [{"end": g["end"], "tracks": g["tracks"]} for g in module["gables"]],
        },
    )
    assert renamed.status_code == 200, renamed.text
    kept = client.get(url).json()
    assert (kept["version"], kept["saved_in"], kept["status"]) == (4, 3, "proposal")


def test_export_the_approved_version_and_a_draft_marked_utkast(world: World) -> None:
    made = make(
        world,
        straight(
            "Exportmodul",
            length=1200,
            width=480,
            a=[140, 197],
            profile_a="h0-mmm-dubbelspar",
            profile_b="h0-mmm-dubbelspar",
        ),
    )
    client = world.as_(A.id)
    base = f"{API}/modules/{made['id']}/export"
    draft = client.get(base).json()
    assert (draft["version"], draft["status"], draft["landscape"]) == (1, "draft", False)
    assert [v["label"] for v in draft["versions"]] == ["Utkastet, version 1"]
    assert [f["kind"] for f in draft["files"]] == [
        "fremo",
        "print",
        "database",
        "database",
        "mmm",
        "dxf",
    ]
    assert draft["record"]["status"] == "draft"
    assert [t["deviation"] for t in draft["mmm"][0]["tracks"]] == [0, 0]
    dxf_file = next(f for f in draft["files"] if f["kind"] == "dxf")
    assert dxf_file["file"] == "M-001-exportmodul-v1.dxf"
    answer = client.get(dxf_file["url"])
    assert answer.status_code == 200 and answer.headers["content-type"] == "application/dxf"
    assert answer.headers["content-disposition"].startswith(
        'attachment; filename="M-001-exportmodul-v1.dxf"'
    )
    lines = answer.content.decode("cp1252").splitlines()
    assert [x.strip() for x in lines[:4]] == ["0", "SECTION", "2", "HEADER"]
    assert "UTKAST" in answer.text
    assert "UTKAST" in client.get(f"{base}/1/fremo.svg").text

    # Approved, then a landscape makes a new draft: the approved version is what exports.
    client.post(f"{API}/modules/{made['id']}/approve", json={"version": 1})
    client.post(f"{API}/modules/{made['id']}/landscape/make", json={"base": 1})
    chosen = client.get(base).json()
    assert (chosen["version"], chosen["status"]) == (1, "approved")
    assert [v["label"] for v in chosen["versions"]] == ["Godkänd version 1", "Utkastet, version 2"]
    fremo = client.get(f"{base}/1/fremo.svg")
    assert fremo.headers["content-type"] == "image/svg+xml"
    assert fremo.headers["content-disposition"].startswith("inline")
    assert "UTKAST" not in fremo.text and "Exportmodul" in fremo.text
    newest = client.get(f"{base}?version=2").json()
    assert (newest["status"], newest["landscape"], newest["record"]["landscape"]) == (
        "draft",
        True,
        True,
    )
    assert "Landskapet" in client.get(f"{base}/2/utskrift.svg").text
    railed = client.get(f"{base}/2/modul.dxf?rails=true&landscape=false").text
    assert "RALS" in railed and "LANDSKAP-BALLAST" not in railed
    assert "LANDSKAP-BALLAST" in client.get(f"{base}/2/modul.dxf").text
    record = json.loads(client.get(f"{base}/1/moduldatabas.json").content)
    assert record["format"] == "trainmeet.cad.moduldatabas/1" and record["status"] == "approved"
    rows = list(csv.reader(io.StringIO(client.get(f"{base}/1/moduldatabas.csv").text)))
    assert rows[1][rows[0].index("gable_a_tracks")] == "140/197"
    mmm = list(csv.DictReader(io.StringIO(client.get(f"{base}/1/mmm.csv").text)))
    assert [r["fran_kant1_mm"] for r in mmm] == ["140", "197", "140", "197"]
    assert client.get(f"{base}/1/annat.txt").status_code == 404
    assert client.get(f"{base}/9/modul.dxf").status_code == 404
    assert world.as_(B.id).get(base).status_code == 404
