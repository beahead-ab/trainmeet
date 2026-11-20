"""Mätbilden i TKL:s Foto through CAD's API (#89 del d4, CAD-13, CAD-33, CAD-21): each module's
measuring image in an assembly or a single module, at the version it pins, with its frame and
where the assembly put it; only for those who see the module, and for Studio's token, never
another app's.

The measuring images are synthetic: a made-up module seen from above at 2 px per mm with a
margin, a dark track at its place from Kant 1, put on the version as the photo chain leaves it (a
done job with its measuring image and display copy). The track is found again in the image CAD
sends and taken through the matrix to the assembly's mm, where it must lie on the track graph
that the station's real geometry is made from. Nothing here is a real station."""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray
from psycopg.types.json import Jsonb

from cad import matbilder
from cad.store import new_key
from cad.tests.conftest import API, A, B, World, straight
from cad.tests.test_assemblies_api import ASSEMBLIES, approved, change, end, new, tkl_token

LENGTH, WIDTH, TRACK = 600.0, 300.0, 140.0
MARGIN, PPM = 10.0, 2.0
MIRRORED = [1.0, 0.0, 0.0, -1.0, 0.0, WIDTH]
"""A photo read with Kant 1 on the other side: its mm to the module's."""


def synthetic(mirrored: bool = False) -> NDArray[np.uint8]:
    """The measuring image of a LENGTH × WIDTH module with its track TRACK mm from Kant 1, in
    the frame it was read in: mirrored, the track lies WIDTH - TRACK from the edge it saw first."""
    w, h = round((LENGTH + 2 * MARGIN) * PPM), round((WIDTH + 2 * MARGIN) * PPM)
    y0 = -MARGIN + 0.5 / PPM
    yy = y0 + np.arange(h, dtype=np.float32) / PPM
    picture = np.empty((h, w, 3), np.uint8)
    picture[:] = (64, 112, 82)
    board = (yy >= 0) & (yy <= WIDTH)
    picture[board, :] = (96, 140, 110)
    track = (WIDTH - TRACK) if mirrored else TRACK
    picture[np.abs(yy - track) <= 3, :] = (40, 40, 44)
    return picture


def photograph(
    world: World, module: dict[str, Any], version: int, *, mirrored: bool = False, jpeg: bool
) -> uuid.UUID:
    pixels = synthetic(mirrored)
    owner = uuid.UUID(module["owner"]["id"])
    store = world.app.state.photos.store
    job = uuid.uuid4()
    w = pixels.shape[1]
    h = pixels.shape[0]
    small = cv2.resize(pixels, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    x0 = -MARGIN + 0.5 / PPM
    result: dict[str, Any] = {"grid": [x0, x0, PPM, w, h]}
    if mirrored:
        result["frame"] = MIRRORED
    with world.app.state.db.transaction() as conn:
        conn.execute(
            "INSERT INTO photo_job (id, module_id, owner_kind, owner_id, person_id, person_name, "
            "key, state, start, result, chain) VALUES (%s, %s, 'person', %s, %s, 'Provkonto A', "
            "%s, 'done', '{}', %s, 'prov')",
            (job, module["id"], owner, owner, "a" * 64, Jsonb(result)),
        )
        for kind, image in (("measure", pixels), ("display", small)):
            ending = ".jpg" if jpeg else ".png"
            data = cv2.imencode(ending, image)[1].tobytes()
            key = new_key(owner, ending[1:])
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
    return job


def placed_pair(world: World) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Two photographed modules: the first turned 30° where the owner put it, the second joined
    at its gable B, its photo read with Kant 1 on the other side."""
    first = approved(world, straight("Foto 1", length=LENGTH, width=WIDTH, a=[TRACK]))
    second = approved(world, straight("Foto 2", length=LENGTH, width=WIDTH, a=[TRACK]))
    photograph(world, first, 1, jpeg=True)
    photograph(world, second, 1, mirrored=True, jpeg=False)
    made = new(world)
    body = change(
        made,
        [{"module": first["id"], "at": [100, 50], "angle": 30}, {"module": second["id"]}],
        [{"a": end(first, "B"), "b": end(second, "A")}],
    )
    saved = world.as_(A.id).put(f"{ASSEMBLIES}/{made['id']}", json=body)
    assert saved.status_code == 200, saved.text
    return saved.json(), first, second


def through(m: Sequence[float], p: tuple[float, float]) -> tuple[float, float]:
    return matbilder.apply(m, p)


def to_segment(p: tuple[float, float], a: list[float], b: list[float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def track_in(data: bytes) -> list[tuple[float, float]]:
    """The dark track found in the image CAD sends: its centre in five columns, in the image's
    pixels with (0, 0) at its top left corner."""
    pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert pixels is not None
    w = pixels.shape[1]
    found = []
    for u in (w * k // 6 for k in range(1, 6)):
        dark = np.flatnonzero(pixels[:, u] < 60)
        assert dark.size, "the track is in the image"
        found.append((u + 0.5, float(dark.mean()) + 0.5))
    return found


def test_the_frame_turns_mirrors_and_places_the_image() -> None:
    frame = matbilder.frame_of([-9.75, -9.75, 2.0, 1240, 640], 620, 320, MIRRORED)
    assert frame.mm_per_px == (1.0, 1.0)
    # Read mirrored: the module's origin is at the image's bottom left, 10 px in from each edge.
    assert frame.origin == (10.0, 310.0)
    assert through(frame.matrix, (10, 310)) == pytest.approx((0, 0))
    assert through(frame.matrix, (610, 10)) == pytest.approx((LENGTH, WIDTH))
    placed = matbilder.compose(matbilder.pose((100, 50), 90), frame.matrix)
    # Turned 90° counterclockwise on the screen with y down: x along the module goes up.
    assert through(placed, (610, 310)) == pytest.approx((100, 50 - LENGTH))
    assert matbilder.compose(matbilder.invert(placed), placed) == pytest.approx(
        matbilder.IDENTITY, abs=1e-9
    )


def test_each_module_image_lies_on_the_track_graph_of_the_assembly(world: World) -> None:
    found, first, second = placed_pair(world)
    client = world.as_(A.id)
    url = f"{API}/studio/assembly/{found['id']}/images"
    listed = client.get(url)
    assert listed.status_code == 200, listed.text
    images = listed.json()
    assert images["revision"] == found["revision"] and images["missing"] == []
    assert images["gauge"] == 16.5, "H0"
    assert [(i["number"], i["version"]) for i in images["images"]] == [("M-001", 1), ("M-002", 1)]
    by_id = {i["module"]: i for i in images["images"]}
    assert by_id[first["id"]]["at"] == [100, 50] and by_id[first["id"]]["angle"] == 30
    assert by_id[first["id"]]["frame"]["origin"] == [10, 10]
    assert by_id[second["id"]]["frame"]["origin"] == [10, 310]
    pieces = found["graph"]["pieces"]
    worst = 0.0
    for image in images["images"]:
        # The board's corner at gable A and Kant 1 is the outline's first point.
        corner = through(image["to_source"], tuple(image["frame"]["origin"]))
        assert math.dist(corner, image["outline"][0]) < 0.2
        got = client.get(f"{url}/{image['module']}/{image['version']}")
        assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
        assert got.content[:3] == b"\xff\xd8\xff", "a PNG display copy is sent as JPEG"
        decoded = cv2.imdecode(np.frombuffer(got.content, np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None
        assert decoded.shape[:2] == (image["frame"]["height"], image["frame"]["width"])
        own = [p for p in pieces if p["id"].startswith(image["module"])]
        for p in track_in(got.content):
            there = through(image["to_source"], p)
            near = min(
                to_segment(there, s["start"], s["end"]) for piece in own for s in piece["segments"]
            )
            worst = max(worst, near)
    # The image's track lies on the graph's, which the station's real geometry is made from.
    assert worst < 1.0, worst


def test_only_studio_and_those_who_see_the_module_get_its_image(world: World) -> None:
    found, first, _ = placed_pair(world)
    url = f"{API}/studio/assembly/{found['id']}/images"
    image = f"{url}/{first['id']}/1"
    # B's own assembly with A's module, seen by everyone: B gets its image, until A hides it.
    owner = world.as_(A.id)
    owner.put(f"{API}/modules/{first['id']}/visibility", json={"visibility": "all"})
    other = world.as_(B.id)
    theirs_made = new(world, "B:s", person=B)
    used = other.put(
        f"{ASSEMBLIES}/{theirs_made['id']}",
        json=change(theirs_made, [{"module": first["id"]}], []),
    )
    assert used.status_code == 200, used.text
    their_url = f"{API}/studio/assembly/{theirs_made['id']}/images"
    assert [i["module"] for i in other.get(their_url).json()["images"]] == [first["id"]]
    assert other.get(f"{their_url}/{first['id']}/1").status_code == 200
    owner.put(f"{API}/modules/{first['id']}/visibility", json={"visibility": "me"})
    hidden = other.get(their_url).json()
    assert hidden["images"] == []
    assert [(m["title"], m["reason"]) for m in hidden["missing"]] == [
        ("En modul du inte ser", matbilder.UNSEEN)
    ]
    assert other.get(f"{their_url}/{first['id']}/1").status_code == 404
    # Studio through TKL, with the person's token; never another app's (last: it ends the app).
    browser = world.browser()
    with browser:
        mine = {"Authorization": f"Bearer {tkl_token(world, A.id)}"}
        assert browser.get(url, headers=mine).status_code == 200
        assert browser.get(image, headers=mine).status_code == 200
        for bad in (tkl_token(world, A.id, azp="cad"), "inte-en-token"):
            for path in (url, image):
                refused = browser.get(path, headers={"Authorization": f"Bearer {bad}"})
                assert refused.status_code == 401 and refused.json()["code"] == "login"
        assert browser.get(url).status_code == 401
        theirs = {"Authorization": f"Bearer {tkl_token(world, B.id)}"}
        assert browser.get(url, headers=theirs).status_code == 404
        assert browser.get(image, headers=theirs).status_code == 404
        # A version the assembly does not pin has no image here.
        assert browser.get(f"{url}/{first['id']}/2", headers=mine).status_code == 404


def test_a_module_without_a_photo_and_a_single_module(world: World) -> None:
    drawn = approved(world, straight("Ritad", length=LENGTH, width=WIDTH, a=[TRACK]))
    photographed = approved(world, straight("Fotad", length=LENGTH, width=WIDTH, a=[TRACK]))
    job = photograph(world, photographed, 1, jpeg=True)
    made = new(world)
    body = change(
        made,
        [{"module": drawn["id"]}, {"module": photographed["id"]}],
        [{"a": end(drawn, "B"), "b": end(photographed, "A")}],
    )
    assert world.as_(A.id).put(f"{ASSEMBLIES}/{made['id']}", json=body).status_code == 200
    client = world.as_(A.id)
    images = client.get(f"{API}/studio/assembly/{made['id']}/images").json()
    assert [i["name"] for i in images["images"]] == ["Fotad"]
    assert images["images"][0]["at"] == [LENGTH, 0]
    assert [(m["title"], m["reason"]) for m in images["missing"]] == [
        ("M-001 Ritad", matbilder.NO_PHOTO)
    ]
    # A single approved module of the person's own lies at the origin, as Studio's graph.
    single = client.get(f"{API}/studio/module/{photographed['id']}/images").json()
    one = single["images"][0]
    assert (single["kind"], single["revision"], one["at"], one["angle"]) == ("module", 1, [0, 0], 0)
    assert one["to_source"] == one["frame"]["matrix"]
    assert one["outline"] == [[0, 0], [LENGTH, 0], [LENGTH, WIDTH], [0, WIDTH]]
    got = client.get(f"{API}/studio/module/{photographed['id']}/images/{photographed['id']}/1")
    assert got.status_code == 200 and got.content[:3] == b"\xff\xd8\xff"
    none = client.get(f"{API}/studio/module/{drawn['id']}/images").json()
    assert none["images"] == [] and none["missing"][0]["reason"] == matbilder.NO_PHOTO
    # A measuring image that is gone from CAD's store.
    with world.app.state.db.transaction() as conn:
        conn.execute(
            "UPDATE photo_file SET removed_at = now() WHERE kind = 'display' AND job_id = %s",
            (job,),
        )
    gone = client.get(f"{API}/studio/module/{photographed['id']}/images").json()
    assert gone["images"] == [] and gone["missing"][0]["reason"] == matbilder.GONE
