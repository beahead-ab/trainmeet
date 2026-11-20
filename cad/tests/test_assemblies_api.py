"""Anläggningar and Till TKL Studio through CAD's API (CAD-06, CAD-10, CAD-15, CAD-21, CAD9):
placing approved modules, the pinned versions and the newer one offered, the rights, Studio's
list and graph with the person's access token from ID, and Används i."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import jwt

from cad import dxf
from cad.tests.conftest import API, CLUB, ISSUER, A, B, World, straight

ASSEMBLIES = f"{API}/assemblies"


def approved(world: World, body: dict[str, Any], person: Any = A) -> dict[str, Any]:
    client = world.as_(person.id)
    made = client.post(f"{API}/modules", json=body)
    assert made.status_code == 201, made.text
    done = client.post(f"{API}/modules/{made.json()['id']}/approve", json={"version": 1})
    assert done.status_code == 200, done.text
    found: dict[str, Any] = done.json()
    return found


def new(world: World, name: str = "Anläggning 1", person: Any = A, **extra: Any) -> dict[str, Any]:
    made = world.as_(person.id).post(ASSEMBLIES, json={"name": name, "scale": "H0", **extra})
    assert made.status_code == 201, made.text
    found: dict[str, Any] = made.json()
    return found


def change(
    assembly: dict[str, Any], modules: list[dict[str, Any]], joints: list[Any]
) -> dict[str, Any]:
    return {
        "base": assembly["revision"],
        "name": assembly["name"],
        "modules": modules,
        "joints": joints,
    }


def end(module: dict[str, Any], gable: str) -> dict[str, str]:
    return {"module": module["id"], "gable": gable}


def tkl_token(world: World, person: UUID, azp: str = "tkl") -> str:
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": str(person), "azp": azp, "iat": now, "exp": now + 300}
    return jwt.encode(claims, world.id.key, algorithm="RS256", headers={"kid": world.id.kid})


def two_joined(world: World) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    first = approved(world, straight("Linje 1", a=[140], profile_a="h0-mmm-enkelspar"))
    second = approved(world, straight("Linje 2", a=[140], profile_a="h0-mmm-enkelspar"))
    made = new(world)
    body = change(
        made,
        [{"module": first["id"]}, {"module": second["id"]}],
        [{"a": end(first, "B"), "b": end(second, "A")}],
    )
    saved = world.as_(A.id).put(f"{ASSEMBLIES}/{made['id']}", json=body)
    assert saved.status_code == 200, saved.text
    return saved.json(), first, second


def test_two_approved_modules_join_and_the_assembly_goes_to_studio(world: World) -> None:
    found, first, second = two_joined(world)
    assert found["revision"] == 2 and found["may_edit"] and found["problems"] == []
    assert [m["version"] for m in found["modules"]] == [1, 1]
    assert found["modules"][1]["at"] == [1500, 0] and found["modules"][1]["angle"] == 0
    assert found["checks"] == [
        {"joint": 0, "fits": True, "problems": [], "gap": 0, "turn": 0, "closing": False}
    ]
    assert [p["placed"] for p in found["parts"]] == ["first", "joint"]
    assert found["parts"][0]["gables"][1]["joined"] and not found["parts"][0]["gables"][0]["joined"]
    assert found["parts"][0]["gables"][0]["label"] == "MMM enkelspår"
    graph = found["graph"]
    assert len(graph["pieces"]) == 2 and len(graph["nodes"]) == 3
    assert {p["id"].split(":")[0] for p in graph["pieces"]} == {first["id"], second["id"]}
    listed = world.as_(A.id).get(ASSEMBLIES).json()
    assert [(a["name"], a["modules"], a["problems"]) for a in listed] == [("Anläggning 1", 2, 0)]
    # Till TKL Studio in CAD's own page: the same graph, with the session.
    studio = world.as_(A.id).get(f"{API}/studio/assembly/{found['id']}")
    assert studio.status_code == 200, studio.text
    assert studio.json()["graph"] == graph and studio.json()["source"]["ready"]
    assert [m["number"] for m in studio.json()["source"]["modules"]] == ["M-001", "M-002"]


def test_the_assembly_as_dxf_draws_each_module_where_the_joints_put_it(world: World) -> None:
    """Anläggningen som DXF (CAD-06): Exportera's writer, each module at its pinned version and
    where the joints put it, free for whoever sees the assembly."""
    found, _, _ = two_joined(world)
    answer = world.as_(A.id).get(f"{ASSEMBLIES}/{found['id']}/dxf")
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("application/dxf")
    assert "attachment" in answer.headers["content-disposition"]
    drawn = dxf.read(answer.content)
    assert drawn.version == "AC1009"
    centres = drawn.of("LINE", "SPARMITT")
    assert len(centres) == 2
    xs = sorted(round(x) for line in centres for x in (line.point(10)[0], line.point(11)[0]))
    # The first module from 0 to 1500, the second from 1500 on: one drawing in the assembly's mm.
    assert xs[0] == 0 and 1500 in xs and xs[-1] > 1500
    assert len(drawn.of("POLYLINE", "MODUL")) + len(drawn.of("LINE", "MODUL")) >= 2
    # Another person who sees neither the assembly nor the modules gets nothing.
    assert world.as_(B.id).get(f"{ASSEMBLIES}/{found['id']}/dxf").status_code in (403, 404)


def test_the_assembly_pins_versions_and_offers_a_newer_approved_one(world: World) -> None:
    found, first, _ = two_joined(world)
    client = world.as_(A.id)
    # A new version of the first module, approved: the assembly keeps version 1 and offers 2.
    saved = client.put(
        f"{API}/modules/{first['id']}",
        json={**straight("Linje 1", length=1200, a=[140]), "base": 1},
    )
    assert saved.status_code == 200, saved.text
    assert client.post(f"{API}/modules/{first['id']}/approve", json={"version": 2}).is_success
    again = client.get(f"{ASSEMBLIES}/{found['id']}").json()
    assert again["modules"][0]["version"] == 1 and again["parts"][0]["newer"] == 2
    assert again["modules"][1]["at"] == [1500, 0]
    # Taken on the owner's word: null is the newest approved version.
    kept = [{"module": m["module"], "version": m["version"]} for m in again["modules"]]
    kept[0] = {"module": first["id"], "version": None}
    taken = client.put(f"{ASSEMBLIES}/{found['id']}", json=change(again, kept, again["joints"]))
    assert taken.status_code == 200, taken.text
    assert taken.json()["modules"][0]["version"] == 2 and taken.json()["parts"][0]["newer"] is None
    assert taken.json()["modules"][1]["at"] == [1200, 0]
    # A stale revision is refused.
    stale = client.put(f"{ASSEMBLIES}/{found['id']}", json=change(again, kept, again["joints"]))
    assert stale.status_code == 409 and stale.json()["code"] == "changed"


def test_drafts_other_scales_and_gables_that_do_not_fit(world: World) -> None:
    client = world.as_(A.id)
    draft = client.post(f"{API}/modules", json=straight("Utkast")).json()
    made = new(world)
    refused = client.put(
        f"{ASSEMBLIES}/{made['id']}", json=change(made, [{"module": draft["id"]}], [])
    )
    assert refused.status_code == 422 and "ingen godkänd version" in refused.json()["message"]
    small = approved(world, {**straight("N-modul", width=300, a=[100]), "scale": "N"})
    other = client.put(
        f"{ASSEMBLIES}/{made['id']}", json=change(made, [{"module": small["id"]}], [])
    )
    assert other.status_code == 422 and "skala N" in other.json()["message"]
    first = approved(world, straight("Linje 1", a=[140]))
    double = approved(world, straight("Dubbel", a=[140, 197]))
    body = change(
        made,
        [{"module": first["id"]}, {"module": double["id"]}],
        [{"a": end(first, "B"), "b": end(double, "A")}],
    )
    saved = client.put(f"{ASSEMBLIES}/{made['id']}", json=body).json()
    assert not saved["checks"][0]["fits"]
    assert saved["problems"] == [
        "Skarven M-003 Linje 1 gavel B – M-004 Dubbel gavel A: Gavel B på M-003 Linje 1 har ett "
        "spår och gavel A på M-004 Dubbel har 2 spår."
    ]
    studio = client.get(f"{API}/studio/assembly/{made['id']}").json()
    assert not studio["source"]["ready"] and studio["source"]["problems"] == saved["problems"]


def test_only_those_who_see_a_module_use_it_and_only_the_owner_changes_it(world: World) -> None:
    found, first, _ = two_joined(world)
    other = world.as_(B.id)
    assert other.get(f"{ASSEMBLIES}/{found['id']}").status_code == 404
    assert other.get(ASSEMBLIES).json() == []
    mine = new(world, "B:s", person=B)
    used = other.put(f"{ASSEMBLIES}/{mine['id']}", json=change(mine, [{"module": first["id"]}], []))
    assert used.status_code == 404
    # Seen by everyone, it may be used.
    client = world.as_(A.id)
    client.put(f"{API}/modules/{first['id']}/visibility", json={"visibility": "all"})
    used = other.put(f"{ASSEMBLIES}/{mine['id']}", json=change(mine, [{"module": first["id"]}], []))
    assert used.status_code == 200, used.text
    # Hidden again: an outline, and the assembly cannot go to Studio.
    client.put(f"{API}/modules/{first['id']}/visibility", json={"visibility": "me"})
    hidden = other.get(f"{ASSEMBLIES}/{mine['id']}").json()
    assert hidden["parts"][0]["seen"] is False and hidden["parts"][0]["name"] is None
    assert "syns inte för dig längre" in hidden["problems"][0] and hidden["graph"]["pieces"] == []
    # A club's assembly: its members see it, its administrators change it.
    world.id.join(A.id, CLUB, "Provklubben", "admin")
    world.id.join(B.id, CLUB, "Provklubben")
    club = new(world, "Klubbens", owner=str(CLUB))
    assert club["owner"]["kind"] == "club" and club["may_edit"]
    seen = other.get(f"{ASSEMBLIES}/{club['id']}")
    assert seen.status_code == 200 and not seen.json()["may_edit"]
    refused = other.put(f"{ASSEMBLIES}/{club['id']}", json=change(club, [], []))
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    assert other.delete(f"{ASSEMBLIES}/{club['id']}").status_code == 403
    assert client.delete(f"{ASSEMBLIES}/{club['id']}").status_code == 200
    assert other.get(f"{ASSEMBLIES}/{club['id']}").status_code == 404


def test_studio_asks_with_the_persons_token_and_tells_cad_which_station_uses_it(
    world: World,
) -> None:
    found, first, _ = two_joined(world)
    browser = world.browser()
    with browser:
        headers = {"Authorization": f"Bearer {tkl_token(world, A.id)}"}
        listed = browser.get(f"{API}/studio", headers=headers)
        assert listed.status_code == 200, listed.text
        sources = listed.json()["sources"]
        assert [(s["kind"], s["name"]) for s in sources] == [
            ("assembly", "Anläggning 1"),
            ("module", "Linje 2"),
            ("module", "Linje 1"),
        ]
        graph = browser.get(f"{API}/studio/assembly/{found['id']}", headers=headers)
        assert graph.status_code == 200 and graph.json()["graph"] == found["graph"]
        single = browser.get(f"{API}/studio/module/{first['id']}", headers=headers).json()
        assert {p["id"] for p in single["graph"]["pieces"]} == {
            f"{first['id']}:{p['id']}" for p in first["graph"]["pieces"]
        }
        for bad in (tkl_token(world, A.id, azp="cad"), "inte-en-token"):
            refused = browser.get(f"{API}/studio", headers={"Authorization": f"Bearer {bad}"})
            assert refused.status_code == 401 and refused.json()["code"] == "login"
        assert browser.get(f"{API}/studio").status_code == 401
        # Another person's token sees neither.
        theirs = {"Authorization": f"Bearer {tkl_token(world, B.id)}"}
        assert browser.get(f"{API}/studio", headers=theirs).json()["sources"] == []
        assert (
            browser.get(f"{API}/studio/assembly/{found['id']}", headers=theirs).status_code == 404
        )
        # The owner took it into use in Studio: Används i.
        used = browser.put(
            f"{API}/studio/assembly/{found['id']}/station",
            headers=headers,
            json={"station_id": "exb", "name": "Exempelby", "revision": found["revision"]},
        )
        assert used.status_code == 200, used.text
        assert [s["name"] for s in used.json()["stations"]] == ["Exempelby"]
        stations = world.as_(A.id).get(f"{ASSEMBLIES}/{found['id']}").json()["stations"]
        assert [s["station_id"] for s in stations] == ["exb"]
        module = world.as_(A.id).get(f"{API}/modules/{first['id']}").json()
        assert [(u["kind"], u["name"], u.get("station")) for u in module["used_in"]] == [
            ("assembly", "Anläggning 1", None),
            ("station", "Exempelby", "exb"),
        ]
