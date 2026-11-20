"""Mätbilden under i Foto through TKL's server (#89 del d4, CAD-13, CAD-33, STV-18): Gör förslaget
fetches the modules' measuring images from a pretend TrainMeet CAD with the person's access token
from ID and keeps them with the station; Läs in igen fetches only what changed; the size limits
hold; and the station's choice to draw them is off by default and grey with the reason when the
station has nothing to show. Nothing here names a station (RS13).

The pretend CAD lays each module's image over the module as the example graph has it
(contracts/examples/exempel.studio-graph.json), at 10 mm per pixel, the track 140 mm from Kant 1
on pixel row 14; the station's real geometry, made from the same graph, lies on it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.tkl import TklCadImport, TklImageUnder
from tkl import matbilder
from tkl.store import LOCAL
from tkl.tests.test_app import API
from tkl.tests.test_app_fran_cad import F, PretendStudio, confirm_and_use, propose
from tkl.tests.test_app_ritning import ACCESS, studio
from tkl.tests.test_studio_fran_cad import after

M = API + "/matbilden"
MM_PER_PX = 10.0
WIDTH = 500.0


def jpeg(text: str, size: int = 0) -> bytes:
    """Not a picture TKL looks into: it keeps and serves CAD's JPEG as it is."""
    return b"\xff\xd8\xff\xe0" + text.encode() + b"\0" * size


@dataclass
class PretendImages(PretendStudio):
    """CAD's Mätbilden i Foto, pretended: each module of the graph photographed, but those in
    unphotographed, its image laid where the graph has the module."""

    jobs_of: dict[UUID, UUID] = field(default_factory=dict)
    unphotographed: set[str] = field(default_factory=set)
    sizes: dict[str, int] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)
    images_down: bool = False

    def placed(self) -> list[dict[str, Any]]:
        found = []
        for m in self.graph.source.modules:
            xs = [
                x
                for p in self.graph.graph.pieces
                if p.id.startswith(str(m.id))
                for s in p.segments
                for x in (s.start[0], s.end[0])
            ]
            at, length = min(xs), max(xs) - min(xs)
            job = self.jobs_of.setdefault(m.id, uuid.uuid4())
            found.append({"module": m, "at": at, "length": length, "job": job})
        return found

    def listing(self) -> dict[str, Any]:
        images, missing = [], []
        for p in self.placed():
            m = p["module"]
            if m.name in self.unphotographed:
                missing.append(
                    {
                        "module": str(m.id),
                        "version": m.version,
                        "title": f"{m.number} {m.name}",
                        "reason": "Modulen är inte fotad i TrainMeet CAD.",
                    }
                )
                continue
            at, length = p["at"], p["length"]
            frame = [MM_PER_PX, 0, 0, MM_PER_PX, 0, 0]
            images.append(
                {
                    "module": str(m.id),
                    "version": m.version,
                    "number": m.number,
                    "name": m.name,
                    "job": str(p["job"]),
                    "at": [at, 0],
                    "angle": 0,
                    "frame": {
                        "width": round(length / MM_PER_PX),
                        "height": round(WIDTH / MM_PER_PX),
                        "mm_per_px": [MM_PER_PX, MM_PER_PX],
                        "origin": [0, 0],
                        "matrix": frame,
                    },
                    "to_source": [MM_PER_PX, 0, 0, MM_PER_PX, at, 0],
                    "outline": [[at, 0], [at + length, 0], [at + length, WIDTH], [at, WIDTH]],
                }
            )
        return {
            "kind": "assembly",
            "source": str(self.graph.source.id),
            "revision": self.graph.source.revision,
            "gauge": 16.5,
            "images": images,
            "missing": missing,
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        where = f"/api/cad/1/studio/assembly/{self.graph.source.id}/images"
        path = request.url.path
        if not path.startswith(where):
            return super().handle(request)
        self.tokens.append(request.headers.get("authorization", ""))
        if request.headers.get("authorization") != f"Bearer {ACCESS}":
            return httpx.Response(401, json={"code": "login", "message": "Logga in först."})
        if self.images_down:
            return httpx.Response(503, json={"code": "unavailable", "message": "Inte nu."})
        if path == where:
            return httpx.Response(200, json=self.listing())
        module, _, version = path.removeprefix(where + "/").partition("/")
        found = next((p for p in self.placed() if str(p["module"].id) == module), None)
        if found is None or str(found["module"].version) != version:
            return httpx.Response(404, json={"code": "not_found", "message": "Finns inte."})
        self.fetched.append(found["module"].name)
        data = jpeg(f"{module}:{found['job']}", self.sizes.get(found["module"].name, 0))
        return httpx.Response(200, content=data, headers={"content-type": "image/jpeg"})


@pytest.fixture
def cad() -> PretendImages:
    return PretendImages()


def under(client: TestClient) -> TklImageUnder:
    answer = client.get(M)
    assert answer.status_code == 200, answer.text
    return TklImageUnder.model_validate(answer.json())


def test_the_images_follow_the_proposal_and_are_kept_with_the_station(
    tmp_path: Path, cad: PretendImages
) -> None:
    client = studio(tmp_path, cad)
    # Not from CAD yet: grey with the reason, and on is refused.
    grey = under(client)
    assert not grey.available and grey.reason == matbilder.NOT_FROM_CAD and not grey.on
    refused = client.put(M, json={"on": True})
    assert refused.status_code == 409 and refused.json()["detail"] == matbilder.NOT_FROM_CAD
    made = propose(client, cad)
    assert [i.title for i in made.link.images] == ["M-001 Infart", "M-002 Linje"]
    assert cad.fetched == ["Infart", "Linje"] and set(cad.tokens) == {f"Bearer {ACCESS}"}
    # The draft is not the station's yet: Foto has nothing until Använd ritningen.
    assert not under(client).available
    confirm_and_use(client, made.rita)
    shown = under(client)
    assert shown.available and shown.reason is None and not shown.on, "off by default"
    assert shown.gauge == 16.5, "the rails over the images at the source's gauge"
    assert shown.bytes == sum(i.bytes for i in shown.images) and shown.limit == 32 * 2**20
    on = TklImageUnder.model_validate(client.put(M, json={"on": True}).json())
    assert on.on and under(client).on
    # Each image is served from the station, as CAD sent it, without asking CAD again.
    asked = len(cad.asked)
    for image in on.images:
        assert image.url and image.url.endswith(f"?bild={image.job}")
        got = client.get(image.url)
        assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
        assert got.content == jpeg(f"{image.module}:{image.job}")
    assert len(cad.asked) == asked
    assert client.get(f"{M}/{uuid.uuid4()}/1").status_code == 404
    # Foto's real geometry (the panel's, from the station's model) is the graph's, in the same
    # mm: the line's track lies on the image's row 14 (140 mm from Kant 1), within its columns.
    panel = client.get(API + "/studio/model").json()["panel"]
    line = next(i for i in on.images if i.title == "M-002 Linje")
    a, _, _, d, e, f = line.matrix
    real = next(k["real"] for k in panel["lines"] if k["piece"].startswith(str(line.module)))
    assert len(real) >= 2
    for x, y in real:
        assert (y - f) / d == pytest.approx(14.0, abs=0.01)
        assert -0.01 <= (x - e) / a <= line.width + 0.01


def test_read_again_fetches_only_what_changed(tmp_path: Path, cad: PretendImages) -> None:
    client = studio(tmp_path, cad)
    confirm_and_use(client, propose(client, cad).rita)
    client.put(M, json={"on": True})
    cad.fetched.clear()
    # The same source again, nothing changed in CAD: nothing is fetched, nothing to use.
    same = propose(client, cad)
    assert same.rita.state == "in_use" and cad.fetched == []
    # A new photo of a module, the track plan the same: its image follows at once.
    infart = cad.graph.source.modules[0].id
    cad.jobs_of[infart] = uuid.uuid4()
    again = propose(client, cad)
    assert again.rita.state == "in_use" and cad.fetched == ["Infart"]
    shown = under(client)
    assert {i.job for i in shown.images if i.module == infart} == {cad.jobs_of[infart]}
    assert shown.on
    # CAD does not give the images now: the station keeps those it has.
    cad.images_down = True
    propose(client, cad)
    assert under(client).images == shown.images
    assert client.get(shown.images[0].url or "").status_code == 200
    cad.images_down = False
    # The assembly in CAD changes: the line at its next version and a third module, which is
    # not photographed. The draft's images wait for Använd ritningen; Foto keeps the old.
    changed_graph = after(cad.graph)
    modules = [
        m.model_copy(update={"version": 2}) if m.name == "Linje" else m
        for m in changed_graph.source.modules
    ]
    cad.graph = changed_graph.model_copy(
        update={"source": changed_graph.source.model_copy(update={"modules": modules})}
    )
    cad.unphotographed = {"Linje bortom"}
    cad.fetched.clear()
    changed = propose(client, cad)
    assert cad.fetched == ["Linje"], "only the new version"
    assert changed.link.missing == ["M-003 Linje bortom: Modulen är inte fotad i TrainMeet CAD."]
    assert [(i.title, i.version) for i in under(client).images] == [
        ("M-001 Infart", 1),
        ("M-002 Linje", 1),
    ]
    confirm_and_use(client, changed.rita)
    shown = under(client)
    assert [(i.title, i.version) for i in shown.images] == [
        ("M-001 Infart", 1),
        ("M-002 Linje", 2),
    ]
    assert shown.missing == changed.link.missing and shown.on
    # The old version's image went with the link that showed it.
    line = cad.graph.source.modules[1].id
    assert client.get(f"{M}/{line}/1").status_code == 404
    assert client.get(f"{M}/{line}/2").status_code == 200


def test_the_size_limits_and_a_cad_that_does_not_answer(
    tmp_path: Path, cad: PretendImages, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = studio(tmp_path, cad)
    # Too large for one image, and then no room left for the station's.
    monkeypatch.setattr(matbilder, "IMAGE_LIMIT", 2000)
    monkeypatch.setattr(matbilder, "STATION_LIMIT", 2500)
    cad.sizes = {"Infart": 2001, "Linje": 1000}
    made = propose(client, cad)
    assert [i.title for i in made.link.images] == ["M-002 Linje"]
    assert made.link.missing == [f"M-001 Infart: {matbilder.TOO_LARGE}"]
    cad.sizes = {"Infart": 1600, "Linje": 1000}
    made = propose(client, cad)
    assert [i.title for i in made.link.images] == ["M-001 Infart"]
    assert made.link.missing == [f"M-002 Linje: {matbilder.NO_ROOM}"]
    # CAD does not answer for the images: the proposal comes all the same, without them.
    cad.images_down = True
    made = propose(client, cad)
    assert made.link.images == []
    assert made.link.missing == [f"{matbilder.FAILED}: Inte nu."]
    confirm_and_use(client, made.rita)
    grey = under(client)
    assert (
        not grey.available and grey.reason == f"{matbilder.FAILED}: Inte nu. {matbilder.READ_AGAIN}"
    )
    # And no module photographed: grey, with the modules drawn as vectors.
    cad.images_down = False
    cad.unphotographed = {"Infart", "Linje"}
    client.post(f"{F}/assembly/{cad.graph.source.id}/forslag")
    none = under(client)
    assert not none.available and none.reason == matbilder.NO_IMAGES and len(none.missing) == 2
    # Without a model from CAD the images go with it.
    assert client.delete(API + "/studio/model").status_code == 200
    assert under(client).reason == matbilder.NOT_FROM_CAD


def test_an_import_from_before_has_no_images_until_read_again(
    tmp_path: Path, cad: PretendImages
) -> None:
    client = studio(tmp_path, cad)
    made: TklCadImport = propose(client, cad)
    confirm_and_use(client, made.rita)
    store = client.app.state.store  # type: ignore[attr-defined]
    in_use, _ = store.cad_links(LOCAL)
    store.save_cad_links(LOCAL, in_use.model_copy(update={"images": [], "missing": []}), None)
    assert under(client).reason == matbilder.NOT_FETCHED
    propose(client, cad)
    assert under(client).available
