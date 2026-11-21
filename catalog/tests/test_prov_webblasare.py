"""The browser test's pretend TrainMeet ID and AI (catalog/prov_webblasare.py, CAT-154): each photo
gets its own answer by its colour, also after Catalog has made it anew as a JPEG, and the tokens
run out as a balance does. Its pretend web search (#53 del b) gives made-up sources, some of
which Catalog's own rules must take away, and gives the tokens back once. No database, no real
AI and no real search."""

from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from PIL import Image

from catalog.evidence import check
from catalog.prototype_search import wanted
from catalog.prov_webblasare import (
    MUSEUM,
    PAGE,
    PERSON_A,
    PERSON_B,
    PERSON_C,
    PretendId,
    answer_for,
)
from catalog.publishers import PUBLISHERS
from catalog.reading import understand
from contracts.catalog import DroppedReason, FieldProfile, PublisherKind
from contracts.tokens import MeterSearchAnswer


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


def test_the_pretend_search_gives_sources_that_catalogs_own_rules_sift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pretend meter searches for 24 tokens and answers for the litt Hbis with made-up
    pages: Catalog's rules keep the values whose source was found and holds them, and take away
    the invented source, the ordering year and the value without a source. The tokens come back
    once, and Provkonto C is the reviewer."""
    monkeypatch.setitem(PUBLISHERS, "museum.example.org", PublisherKind.MUSEUM)
    pretend = PretendId(balances={PERSON_B: 30})
    client = httpx.Client(transport=httpx.MockTransport(pretend.handle), base_url="http://id")
    headers = {"Authorization": "Bearer prov"}
    api = "/api/id/1/apps"
    body: dict[str, Any] = {
        "person": str(PERSON_B),
        "owner": {"kind": "person", "id": str(PERSON_B)},
        "amount": 24,
        "key": "sok",
        "what": "Webbsökning i Catalog: Hbis",
    }
    held = client.post(f"{api}/tokens/reservations", json=body, headers=headers).json()["id"]
    state = client.get(f"{api}/meter/search", headers=headers).json()
    assert (state["available"], state["price"]) == (True, 24)
    marking = {"reservation": held, "litt": "Hbis", "operator": "", "kind": None, "profile": "SE"}
    searched = client.post(
        f"{api}/meter/search", json={**marking, "fields": [], "hold": True}, headers=headers
    )
    answer = MeterSearchAnswer.model_validate(searched.json())
    assert (answer.cost, answer.reservation.state.value) == (24, "held")
    checked = check(
        FieldProfile.SE,
        wanted(FieldProfile.SE),
        answer.values,
        answer.results,
        datetime(2026, 11, 21, tzinfo=UTC),
    )
    assert checked.fields == {"length_over_buffers": "14020", "max_speed": "100", "axles": "2"}
    assert [e["url"] for e in checked.evidence["max_speed"]] == [MUSEUM, PAGE], "the museum first"
    assert {d.key: d.reason for d in checked.dropped} == {
        "weight": DroppedReason.INVENTED_SOURCE,
        "built": DroppedReason.UNSUPPORTED,
        "brake": DroppedReason.NO_SOURCE,
    }
    assert (
        client.post(f"{api}/tokens/reservations/{held}/refund", headers=headers).status_code == 409
    )
    client.post(f"{api}/tokens/reservations/{held}/draw", json={"amount": 24}, headers=headers)
    for _ in range(2):
        back = client.post(f"{api}/tokens/reservations/{held}/refund", headers=headers)
        assert (back.json()["state"], back.json()["balance"]["available"]) == ("returned", 30)
    assert (pretend.searches, pretend.refunds) == (1, 1)

    def roles(person: object) -> list[str]:
        params = {"person": str(person), "resource": "catalog:prototypes"}
        found: list[str] = client.get(f"{api}/access", params=params, headers=headers).json()[
            "roles"
        ]
        return found

    assert (roles(PERSON_C), roles(PERSON_A)) == (["reviewer"], [])
    # Without the key: the meter says so, searches nothing and gives the reservation back.
    pretend.search_connected = False
    assert client.get(f"{api}/meter/search", headers=headers).json()["available"] is False
    again = client.post(
        f"{api}/tokens/reservations", json={**body, "key": "sok-2"}, headers=headers
    )
    off = client.post(
        f"{api}/meter/search",
        json={**marking, "reservation": again.json()["id"], "fields": [], "hold": True},
        headers=headers,
    )
    assert off.status_code == 503 and pretend.balances[PERSON_B] == 30 and pretend.searches == 1
    fleet = {"person": str(PERSON_C), "resource": f"fleet:{PERSON_A}"}
    assert client.get(f"{api}/access", params=fleet, headers=headers).json()["roles"] == []
