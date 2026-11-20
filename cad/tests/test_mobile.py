"""CAD i mobilen (#90, CAD1, CADMOB-12): Fota med mobilen's QR code and the phone's own session.

The code is in the address's fragment, used once, for ten minutes, and kept only as its hash;
it is bound to the person and to the module from a module's page. The phone's session reaches
only the mobile flow's addresses and the modules within its reach, and the computer follows
the phone's progress. Too many codes or wrong tries are refused with 429."""

from __future__ import annotations

import base64
import hashlib
import json
from functools import cache
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from cad import mobile
from cad.bildkedjan import syntetisk
from cad.tests.conftest import API, PUBLIC, A, B, World, curve, straight

MOBILE = f"{API}/mobile"
PHOTOGRAPHED = straight("Rak modul", length=1200, width=480, a=[140, 197])
"""The synthetic straight module's measures (syntetisk.straight_scene)."""


@cache
def small_photo() -> bytes:
    """A small synthetic module, enough for the intake and the corners."""
    shot = syntetisk.Shot(size=(1600, 1200), shadow=False)
    return syntetisk.take(syntetisk.straight_scene(), shot).jpeg


def handoff(world: World, person: UUID = A.id, module: str | None = None) -> dict[str, Any]:
    made = world.as_(person).post(f"{MOBILE}/handoffs", json={"module": module})
    assert made.status_code == 201, made.text
    found: dict[str, Any] = made.json()
    return found


def code_of(made: dict[str, Any]) -> str:
    fragment = urlparse(str(made["url"])).fragment
    assert fragment.startswith("k=")
    return fragment[2:]


def phone(world: World, made: dict[str, Any]) -> TestClient:
    """A phone that scanned the QR code and gave its code."""
    client = world.browser()
    given = client.post(f"{MOBILE}/exchange", json={"code": code_of(made)})
    assert given.status_code == 200, given.text
    return client


def upload(client: TestClient, **data: Any) -> Any:
    start = {"name": "Mobilmodul", "scale": "H0", "kind": "straight", "width": 480, **data}
    files = [
        ("data", (None, json.dumps(start), "application/json")),
        ("images", ("foto.jpg", small_photo(), "image/jpeg")),
    ]
    return client.post(f"{API}/photos", files=files)


def test_the_qr_code_has_the_code_in_its_fragment_and_cad_keeps_only_its_hash(
    world: World,
) -> None:
    made = handoff(world)
    url = urlparse(made["url"])
    assert f"{url.scheme}://{url.netloc}" == PUBLIC and url.path == "/m" and not url.query
    code = code_of(made)
    assert len(code) >= 32
    assert made["qr"].startswith("data:image/svg+xml;base64,")
    assert base64.b64decode(made["qr"].split(",", 1)[1]).startswith(b"<svg")
    assert made["state"] == "waiting" and made["bound"] is None and made["step"] is None
    with world.app.state.db.transaction() as conn:
        row = conn.execute("SELECT * FROM mobile_handoff").fetchone()
    assert bytes(row["code_hash"]) == hashlib.sha256(code.encode()).digest()
    assert code not in json.dumps({k: str(v) for k, v in row.items()})
    # The address with the code is shown once: never in the computer's later answers.
    again = world.as_(A.id).get(f"{MOBILE}/handoffs/{made['id']}").json()
    assert again["url"] is None and again["qr"] is None and again["state"] == "waiting"


def test_the_code_is_used_once_and_gives_the_persons_phone_session(world: World) -> None:
    made = handoff(world)
    client = world.browser()
    given = client.post(f"{MOBILE}/exchange", json={"code": code_of(made)})
    assert given.status_code == 200
    flow = given.json()
    assert flow["handoff"] == made["id"] and flow["bound"] is None and flow["step"] == "start"
    cookie = given.headers["set-cookie"]
    assert cookie.startswith(f"{mobile.COOKIE}=")
    for part in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/cad/1"):
        assert part.lower() in cookie.lower()
    assert client.get(f"{API}/session").json()["account"]["name"] == "Provkonto A"
    # Once: the second phone, or the same one again, gets the same answer as a wrong code.
    second = world.browser().post(f"{MOBILE}/exchange", json={"code": code_of(made)})
    wrong = world.browser().post(f"{MOBILE}/exchange", json={"code": "x" * 32})
    assert second.status_code == wrong.status_code == 401
    assert second.json() == wrong.json() and second.json()["message"] == mobile.EXPIRED
    status = world.as_(A.id).get(f"{MOBILE}/handoffs/{made['id']}").json()
    assert status["state"] == "opened" and status["step"] == "start"


def test_an_old_code_holds_no_more_and_the_computer_sees_it_expired(world: World) -> None:
    made = handoff(world)
    with world.app.state.db.transaction() as conn:
        conn.execute("UPDATE mobile_handoff SET code_expires_at = now() - interval '1 second'")
    late = world.browser().post(f"{MOBILE}/exchange", json={"code": code_of(made)})
    assert late.status_code == 401 and late.json()["code"] == "login"
    assert world.as_(A.id).get(f"{MOBILE}/handoffs/{made['id']}").json()["state"] == "expired"


def test_the_phones_session_ends_after_two_hours(world: World) -> None:
    client = phone(world, handoff(world))
    with world.app.state.db.transaction() as conn:
        conn.execute("UPDATE mobile_handoff SET session_expires_at = now() - interval '1 second'")
    assert client.get(f"{API}/session").json()["account"] is None
    assert client.get(f"{MOBILE}/flow").status_code == 401


def test_a_code_from_a_modules_page_reaches_only_that_module(world: World) -> None:
    computer = world.as_(A.id)
    mine = computer.post(f"{API}/modules", json=PHOTOGRAPHED).json()
    other = computer.post(f"{API}/modules", json=curve()).json()
    made = handoff(world, module=mine["id"])
    assert made["bound"] == mine["id"] and made["module"] == mine["id"]
    client = phone(world, made)
    flow = client.get(f"{MOBILE}/flow").json()
    assert flow["bound"] == mine["id"] and flow["step"] == "fota"
    assert client.get(f"{API}/modules/{mine['id']}").status_code == 200
    assert client.get(f"{API}/photos/consent?module={mine['id']}").status_code == 200
    for refused in (
        client.get(f"{API}/modules/{other['id']}"),
        client.get(f"{API}/photos/consent?module={other['id']}"),
        client.post(f"{API}/modules", json=straight("Ny")),
        upload(client),
        upload(client, module=other["id"]),
    ):
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "forbidden"
    taken = upload(client, module=mine["id"])
    assert taken.status_code == 201, taken.text
    assert taken.json()["module"] == mine["id"]


def test_the_phone_reaches_only_the_mobile_flow(world: World) -> None:
    computer = world.as_(A.id)
    before = computer.post(f"{API}/modules", json=PHOTOGRAPHED).json()
    earlier = upload(computer, module=before["id"]).json()
    client = phone(world, handoff(world))
    for method, path in (
        ("get", f"{API}/libraries"),
        ("get", f"{API}/modules"),
        ("get", f"{API}/modules/{before['id']}"),
        ("delete", f"{API}/modules/{before['id']}"),
        ("get", f"{API}/assemblies"),
        ("post", f"{MOBILE}/handoffs"),
        ("put", f"{API}/modules/{before['id']}/visibility"),
        ("get", f"{API}/photos/{earlier['id']}"),
        ("post", f"{API}/photos/{earlier['id']}/answers"),
    ):
        answer = client.request(method, path, json={})
        assert answer.status_code == 403, (method, path, answer.text)
        assert answer.json()["message"] == mobile.OUTSIDE
    # A new module from the phone is within reach; the one from before is not.
    made = client.post(f"{API}/modules", json=straight("Från mobilen"))
    assert made.status_code == 201
    new = made.json()
    assert client.get(f"{API}/modules/{new['id']}").json()["name"] == "Från mobilen"
    assert client.get(f"{API}/profiles?scale=H0").status_code == 200
    change = {k: new[k] for k in ("name", "scale", "shape")}
    change["gables"] = [{"end": g["end"], "tracks": g["tracks"]} for g in new["gables"]]
    saved = client.put(f"{API}/modules/{new['id']}", json={**change, "base": new["latest"]})
    assert saved.status_code == 200, saved.text
    # A photo for a new module, and its job within reach.
    taken = upload(client)
    assert taken.status_code == 201, taken.text
    job = taken.json()
    assert client.get(f"{API}/photos/{job['id']}").status_code == 200
    assert upload(client, module=before["id"]).status_code == 403


def test_someone_else_sees_no_code_and_gets_none_for_a_module_they_cannot_change(
    world: World,
) -> None:
    computer = world.as_(A.id)
    mine = computer.post(f"{API}/modules", json=straight(visibility="all")).json()
    made = handoff(world)
    other = world.as_(B.id)
    assert other.get(f"{MOBILE}/handoffs/{made['id']}").status_code == 404
    assert other.delete(f"{MOBILE}/handoffs/{made['id']}").status_code == 404
    refused = other.post(f"{MOBILE}/handoffs", json={"module": mine["id"]})
    assert refused.status_code == 403
    assert world.browser().post(f"{MOBILE}/handoffs", json={}).status_code == 401
    # B's phone, from B's code, is B's and reaches none of A's modules.
    client = phone(world, handoff(world, B.id))
    assert client.get(f"{API}/session").json()["account"]["name"] == "Provkonto B"
    assert client.get(f"{API}/modules/{mine['id']}").status_code == 403


def test_the_computer_follows_the_phone_and_can_end_it(world: World) -> None:
    made = handoff(world)
    client = phone(world, made)
    module = client.post(f"{API}/modules", json={**PHOTOGRAPHED, "name": "Följd"}).json()
    job = upload(client, module=module["id"]).json()
    step = {"step": "kontroll", "module": module["id"], "job": job["id"]}
    assert client.put(f"{MOBILE}/flow", json=step).json()["job"] == job["id"]
    status = world.as_(A.id).get(f"{MOBILE}/handoffs/{made['id']}").json()
    followed = (status["step"], status["module"], status["job"])
    assert followed == ("kontroll", module["id"], job["id"])
    # Only within reach: another person's module, or a job of another module, is refused.
    theirs = world.as_(B.id).post(f"{API}/modules", json=straight()).json()
    elsewhere = {"step": "fota", "module": theirs["id"]}
    assert client.put(f"{MOBILE}/flow", json=elsewhere).status_code == 404
    second = client.post(f"{API}/modules", json=straight("Andra")).json()
    wrong = {"step": "kontroll", "module": second["id"], "job": job["id"]}
    assert client.put(f"{MOBILE}/flow", json=wrong).status_code == 404
    # Another module starts without the first one's job.
    moved = client.put(f"{MOBILE}/flow", json={"step": "matt", "module": second["id"]}).json()
    assert moved["module"] == second["id"] and moved["job"] is None
    ended = world.as_(A.id).delete(f"{MOBILE}/handoffs/{made['id']}").json()
    assert ended["state"] == "ended"
    assert client.get(f"{MOBILE}/flow").status_code == 401
    assert client.get(f"{API}/modules/{module['id']}").status_code == 401


def test_the_phone_ends_its_own_session(world: World) -> None:
    made = handoff(world)
    client = phone(world, made)
    client.put(f"{MOBILE}/flow", json={"step": "klar"})
    done = client.delete(f"{MOBILE}/flow")
    assert done.status_code == 200 and done.json()["ended"] is True
    assert f"{mobile.COOKIE}=" in done.headers["set-cookie"]
    assert client.get(f"{API}/session").json()["account"] is None
    status = world.as_(A.id).get(f"{MOBILE}/handoffs/{made['id']}").json()
    assert (status["state"], status["step"]) == ("ended", "klar")


def test_a_phone_with_both_sessions_acts_as_the_qr_code_says_in_the_flow(world: World) -> None:
    client = world.as_(B.id)
    given = client.post(f"{MOBILE}/exchange", json={"code": code_of(handoff(world))})
    assert given.status_code == 200
    assert client.get(f"{API}/session").json()["account"]["name"] == "Provkonto A"
    # Outside the flow the phone's own full login holds.
    assert client.get(f"{API}/libraries").status_code == 200


def test_too_many_codes_or_wrong_tries_are_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    for _ in range(mobile.MAX_HANDOFFS):
        handoff(world)
    refused = world.as_(A.id).post(f"{MOBILE}/handoffs", json={})
    assert refused.status_code == 429 and refused.json()["code"] == "too_many"
    made = handoff(world, B.id)
    client = world.browser()
    for _ in range(mobile.MAX_FAILED):
        assert client.post(f"{MOBILE}/exchange", json={"code": "f" * 32}).status_code == 401
    # Blocked: even the right code waits, so guessing gains nothing.
    blocked = client.post(f"{MOBILE}/exchange", json={"code": code_of(made)})
    assert blocked.status_code == 429 and blocked.json()["code"] == "too_many"
    form = {"content-type": "application/x-www-form-urlencoded"}
    assert client.post(f"{MOBILE}/exchange", content="code=abc", headers=form).status_code == 422


def test_the_attempts_are_forgotten_after_the_window() -> None:
    clock = [1000.0]
    attempts = mobile.Attempts(most=2, window=60)
    monkey = pytest.MonkeyPatch()
    monkey.setattr("cad.mobile.time.monotonic", lambda: clock[0])
    try:
        attempts.failed("a")
        attempts.failed("a")
        assert attempts.blocked("a") and not attempts.blocked("b")
        clock[0] += 61
        assert not attempts.blocked("a")
    finally:
        monkey.undo()
