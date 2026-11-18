"""The browser test's pretend TrainMeet ID and AI (catalog/prov_webblasare.py, CAT-154): each photo
gets its own answer by its colour, also after Catalog has made it anew as a JPEG, and the tokens
run out as a balance does. No database and no real AI."""

from __future__ import annotations

import base64
import io
import json
from typing import Any

import httpx
from PIL import Image

from catalog.prov_webblasare import PERSON_A, PretendId, answer_for
from catalog.reading import understand


def photo(colour: tuple[int, int, int]) -> bytes:
    """As apps/catalog/e2e/omgang.mjs draws it, with dark wheels, and sent on as a JPEG."""
    image = Image.new("RGB", (360, 240), colour)
    image.paste((40, 40, 40), (0, 198, 360, 240))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


def test_each_photo_gets_its_own_answer_by_its_colour() -> None:
    colours = [(200, 40, 40), (40, 150, 60), (40, 80, 200), (130, 60, 160)]
    read = [understand(answer_for(photo(colour))).suggestions for colour in colours]
    assert [(found["litt"].value, found["number"].value) for found in read] == [
        ("Gbs", "3087"),
        ("Hbis", "2253"),
        ("Sgns", "1209"),
        ("Rc4", "1145"),
    ]
    assert understand(answer_for(photo((40, 150, 60)))).warnings == ["Kontrollera numret."]


def test_the_tokens_run_out_after_the_balance_and_go_back_when_not_drawn() -> None:
    pretend = PretendId(balances={PERSON_A: 24})
    client = httpx.Client(transport=httpx.MockTransport(pretend.handle), base_url="http://id")
    headers = {"Authorization": "Bearer prov"}
    owner = {"kind": "person", "id": str(PERSON_A)}

    def reserve() -> httpx.Response:
        body: dict[str, Any] = {"person": str(PERSON_A), "owner": owner, "amount": 12}
        body.update(key="k", what="Avläsning av 1 bild i en omgång i Catalog")
        return client.post("/api/id/1/apps/tokens/reservations", json=body, headers=headers)

    first, second = reserve(), reserve()
    assert (first.status_code, second.status_code, reserve().status_code) == (201, 201, 402)
    image = {"media_type": "image/jpeg", "data": base64.b64encode(photo((200, 40, 40))).decode()}
    read = client.post(
        "/api/id/1/apps/meter",
        json={"reservation": first.json()["id"], "images": [image], "hold": True},
        headers=headers,
    )
    assert read.json()["cost"] == 12 and "Gbs" in read.json()["text"]
    drawn = client.post(
        f"/api/id/1/apps/tokens/reservations/{first.json()['id']}/draw",
        json={"amount": 12},
        headers=headers,
    )
    assert drawn.json()["state"] == "drawn"
    back = client.post(
        f"/api/id/1/apps/tokens/reservations/{second.json()['id']}/return", headers=headers
    )
    assert back.json()["state"] == "returned"
    balance = client.get(
        "/api/id/1/apps/tokens",
        params={"person": str(PERSON_A), "owner": f"person:{PERSON_A}"},
        headers=headers,
    )
    assert json.loads(balance.content)["available"] == 12
    assert client.get("/api/id/1/apps/fleets", headers={}).status_code == 401
