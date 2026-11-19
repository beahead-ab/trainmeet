"""Ritningen and Lås mått through CAD's API (CAD-03, CAD-20, CAD-21, CAD-24): the change set on
the newest version, saving with 409, Att kolla, utjämning, Lås mått's preview and use, and
Godkänn spårplanen, with the rights of part a."""

from __future__ import annotations

from typing import Any

from cad.tests.conftest import API, CLUB, A, B, World, straight


def make(world: World, body: dict[str, Any], person: Any = A) -> dict[str, Any]:
    answer = world.as_(person.id).post(f"{API}/modules", json=body)
    assert answer.status_code == 201, answer.text
    made: dict[str, Any] = answer.json()
    return made


def trapezoid() -> dict[str, Any]:
    """MMM's trapezoid with Kant 1 slanting 131,5 mm, as the photo test's: the track at 140 mm
    in both gables runs across the module until Lås mått bends it."""
    return {
        "name": "Trapets 480/280",
        "scale": "H0",
        "shape": {
            "kind": "trapezoid",
            "length": 685,
            "width_a": 480,
            "width_b": 280,
            "offset": 131.5,
        },
        "gables": [
            {"end": "A", "profile": "h0-mmm-enkelspar", "tracks": [140]},
            {"end": "B", "profile": "h0-mmm-enkelspar", "tracks": [140]},
        ],
    }


def a_switch(piece: str) -> dict[str, Any]:
    return {
        "op": "switch",
        "piece": piece,
        "from_a": 400,
        "radius": 830,
        "angle": 11.4,
        "side": "right",
    }


def test_the_drawing_is_the_change_set_on_the_newest_version_and_saves_as_a_new_one(
    world: World,
) -> None:
    made = make(world, straight(width=700))
    client = world.as_(A.id)
    piece = made["graph"]["pieces"][0]["id"]
    ops = [a_switch(piece)]
    view = client.post(f"{API}/modules/{made['id']}/drawing", json={"base": 1, "operations": ops})
    assert view.status_code == 200, view.text
    shown = view.json()
    assert shown["changed"] and shown["stats"]["switches"] == 1
    assert shown["switches"][0]["leaves"] == "spår från A1 mot änden"
    assert shown["switches"][0]["from_a"] == 400
    assert [c["kind"] for c in shown["checks"]] == ["open_end"]
    assert shown["designs"][0]["name"] == "Okänd" and shown["limits"]["min_radius"] == 400
    # Nothing is saved until Spara.
    assert client.get(f"{API}/modules/{made['id']}").json()["version"] == 1
    saved = client.post(
        f"{API}/modules/{made['id']}/drawing/save", json={"base": 1, "operations": ops}
    )
    assert saved.status_code == 200, saved.text
    module = saved.json()
    assert module["version"] == 2 and module["status"] == "draft"
    assert module["drawing"]["source"] == "drawn"
    assert module["drawing"]["ids"] == [
        {
            "old": [piece],
            "new": [piece, module["graph"]["switches"][0]["straight"]],
            "why": "switch",
        }
    ]
    assert [c["kind"] for c in module["checks"]] == ["open_end"]
    history = client.get(f"{API}/modules/{made['id']}/history").json()
    assert history[0]["text"] == "Version 2: ritningen sparad (en växel lagd)"
    # The ids stay when the module is saved again, and a re-save from the old base is refused.
    again = client.post(
        f"{API}/modules/{made['id']}/drawing/save",
        json={"base": 2, "operations": [{"op": "move_switch", "switch": "v8", "from_a": 600}]},
    ).json()
    assert {p["id"] for p in again["graph"]["pieces"]} == {
        p["id"] for p in module["graph"]["pieces"]
    }
    assert again["drawing"]["ids"] == []
    stale = client.post(
        f"{API}/modules/{made['id']}/drawing/save", json={"base": 2, "operations": ops}
    )
    assert stale.status_code == 409 and stale.json()["code"] == "changed"
    assert (
        client.post(
            f"{API}/modules/{made['id']}/drawing", json={"base": 2, "operations": []}
        ).status_code
        == 409
    )


def test_a_refused_operation_and_nothing_to_save_are_422(world: World) -> None:
    made = make(world, straight())
    client = world.as_(A.id)
    bad = client.post(
        f"{API}/modules/{made['id']}/drawing",
        json={"base": 1, "operations": [{"op": "delete", "target": "s99"}]},
    )
    assert bad.status_code == 422
    assert bad.json()["message"] == "Ändring 1 går inte: Det finns inget sådant att ta bort."
    empty = client.post(
        f"{API}/modules/{made['id']}/drawing/save", json={"base": 1, "operations": []}
    )
    assert empty.status_code == 422 and empty.json()["message"] == "Det finns inget att spara."


def test_only_those_who_may_change_the_module_draw_on_it(world: World) -> None:
    world.id.join(A.id, CLUB, "Västby MJK", "admin")
    world.id.join(B.id, CLUB, "Västby MJK")
    made = make(world, straight(visibility="club", club=str(CLUB)))
    seen = world.as_(B.id)
    edit = {"base": 1, "operations": []}
    for path in ("drawing", "drawing/save", "drawing/approve"):
        refused = seen.post(f"{API}/modules/{made['id']}/{path}", json=edit)
        assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    lock = seen.post(f"{API}/modules/{made['id']}/drawing/lock", json={**edit, "lock": {}})
    assert lock.status_code == 403
    assert seen.get(f"{API}/modules/{made['id']}/checks").status_code == 200
    world.id.module_roles[(B.id, made["id"])] = ["editor"]
    assert seen.post(f"{API}/modules/{made['id']}/drawing", json=edit).status_code == 200
    stranger = world.as_(world_c_id())
    assert stranger.post(f"{API}/modules/{made['id']}/drawing", json=edit).status_code == 404
    assert world.browser().post(f"{API}/modules/{made['id']}/drawing", json=edit).status_code == 401


def world_c_id() -> Any:
    from cad.tests.conftest import C

    return C.id


def test_att_kolla_answers_stay_with_the_version_and_open_items_stop_the_approval(
    world: World,
) -> None:
    made = make(world, straight(a=[400], width=700))
    client = world.as_(A.id)
    through = made["graph"]["pieces"][0]["id"]
    ops: list[dict[str, Any]] = [
        {"op": "delete", "target": through},
        {"op": "line", "start": [51, 400], "end": [1500, 400]},
    ]
    shown = client.post(
        f"{API}/modules/{made['id']}/drawing", json={"base": 1, "operations": ops}
    ).json()
    assert sorted(c["kind"] for c in shown["checks"]) == ["open_end", "short_rail"]
    short = next(c for c in shown["checks"] if c["kind"] == "short_rail")
    assert short["title"] == "Rälsen slutar 51 mm före gavel A"
    refused = client.post(
        f"{API}/modules/{made['id']}/drawing/approve", json={"base": 1, "operations": ops}
    )
    assert refused.status_code == 422
    assert refused.json()["message"] == (
        "Spårplanen har 2 saker att kolla. Svara på dem i Ritningen först."
    )
    line = next(p["id"] for p in shown["graph"]["pieces"])
    ops += [
        {"op": "answer", "key": short["key"], "answer": "passbit"},
        {"op": "switch", "piece": line, "from_a": 700, "radius": 705, "angle": 10, "side": "right"},
    ]
    shown = client.post(
        f"{API}/modules/{made['id']}/drawing", json={"base": 1, "operations": ops}
    ).json()
    assert [c["answer"] for c in shown["checks"]] == [None, None]
    ops += [
        {"op": "answer", "key": c["key"], "answer": c["choices"][-1]["id"]} for c in shown["checks"]
    ]
    approved = client.post(
        f"{API}/modules/{made['id']}/drawing/approve", json={"base": 1, "operations": ops}
    )
    assert approved.status_code == 200, approved.text
    module = approved.json()
    assert module["status"] == "approved" and module["version"] == 2
    assert module["drawing"]["plan_approved"]
    assert all(p["origin"]["certainty"] == "confirmed" for p in module["graph"]["pieces"])
    assert sorted(a["answer"] for a in module["drawing"]["answers"]) == [
        "radien-stammer",
        "slutar",
    ]
    assert all(c["answer"] for c in module["checks"])
    texts = [e["text"] for e in client.get(f"{API}/modules/{made['id']}/history").json()]
    assert texts[:2] == [
        "Version 2: spårplanen godkänd",
        "Version 2: ritningen sparad (ett spår ritat, en växel lagd, 3 svar i Att kolla)",
    ]
    # Part a's Godkänn is held to the same rule.
    drawn = make(world, straight("Öppen", a=[], width=700))
    client.post(
        f"{API}/modules/{drawn['id']}/drawing/save",
        json={"base": 1, "operations": [{"op": "line", "start": [100, 300], "end": [900, 300]}]},
    )
    open_ = client.post(f"{API}/modules/{drawn['id']}/approve", json={"version": 2})
    assert open_.status_code == 422 and "saker att kolla" in open_.json()["message"]


def test_lock_measures_preview_and_use(world: World) -> None:
    made = make(world, trapezoid())
    client = world.as_(A.id)
    old = made["graph"]["pieces"][0]["id"]
    ask = {"base": 1, "operations": [], "lock": {"radii": "same"}}
    preview = client.post(f"{API}/modules/{made['id']}/drawing/lock", json=ask)
    assert preview.status_code == 200, preview.text
    proposal = preview.json()
    assert proposal["solved"] and len(proposal["parts"]) == 5
    assert [g["value"] for g in proposal["gables"]] == [140, 140]
    assert proposal["deviation"]["max"] > 0 and len(proposal["tangents"]) == 4
    assert client.get(f"{API}/modules/{made['id']}").json()["version"] == 1
    used = client.post(
        f"{API}/modules/{made['id']}/drawing/save",
        json={"base": 1, "operations": [{"op": "lock", "radii": "same"}]},
    ).json()
    assert used["version"] == 2 and 3 <= len(used["graph"]["pieces"]) <= 5
    split = used["drawing"]["ids"][0]
    assert split["why"] == "lock" and split["old"] == [old] and split["new"][0] == old
    assert [x["value"] for x in used["drawing"]["locks"]] == [140, 140]
    assert used["track_length"] > 685
    texts = [e["text"] for e in client.get(f"{API}/modules/{made['id']}/history").json()]
    assert texts[0] == "Version 2: ritningen sparad (Lås mått)"
    # The measures saved again keep the drawn graph and its ids.
    body = {
        "base": 2,
        "name": "Trapets 480/280 · MMM",
        "scale": "H0",
        "shape": used["shape"],
        "gables": [
            {"end": g["end"], "norm": g["norm"], "profile": g["profile"], "tracks": g["tracks"]}
            for g in used["gables"]
        ],
    }
    renamed = client.put(f"{API}/modules/{made['id']}", json=body).json()
    assert [p["id"] for p in renamed["graph"]["pieces"]] == split["new"]
    off_norm = client.post(
        f"{API}/modules/{made['id']}/drawing/lock",
        json={"base": 3, "operations": [], "lock": {"a": 150}},
    ).json()
    assert not off_norm["solved"] and off_norm["parts"] == []
    assert off_norm["why"] == "Gavel A: spår 1 ligger 140 mm från Kant 1 i MMM enkelspår."
    refused = client.post(
        f"{API}/modules/{made['id']}/drawing/save",
        json={"base": 3, "operations": [{"op": "lock", "a": 150}]},
    )
    assert refused.status_code == 422 and "MMM enkelspår" in refused.json()["message"]


def test_utjamning_of_a_line(world: World) -> None:
    client = world.as_(A.id)
    points = [[x, 300 + (2 if x % 20 else -2)] for x in range(0, 1001, 10)]
    answer = client.post(f"{API}/smooth", json={"points": points, "level": "normal"})
    assert answer.status_code == 200, answer.text
    found = answer.json()
    assert len(found["segments"]) == 1 and found["segments"][0]["kind"] == "line"
    assert found["deviation"]["max"] <= 9 and found["deviation"]["count"] == len(points)
    off = client.post(f"{API}/smooth", json={"points": points, "level": "off"}).json()
    assert len(off["segments"]) == len(points) - 1
    assert world.browser().post(f"{API}/smooth", json={"points": points}).status_code == 401
