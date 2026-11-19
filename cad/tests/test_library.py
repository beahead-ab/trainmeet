"""The module library through CAD's API (CAD-01, CAD-05, CAD-07, CAD-08, CAD-21, CAD-22):
versions and history, the rights, the visibility, and the gable profiles with their counts."""

from __future__ import annotations

from typing import Any

from cad.tests.conftest import API, CLUB, OTHER_CLUB, A, B, C, D, World, curve, straight


def make(world: World, body: dict[str, Any], person: Any = A) -> dict[str, Any]:
    answer = world.as_(person.id).post(f"{API}/modules", json=body)
    assert answer.status_code == 201, answer.text
    made: dict[str, Any] = answer.json()
    return made


def save(world: World, module: dict[str, Any], person: Any = A, **change: Any) -> Any:
    body = {
        "base": module["version"],
        "name": module["name"],
        "scale": module["scale"],
        "shape": module["shape"],
        "gables": [
            {"end": g["end"], "norm": g["norm"], "profile": g["profile"], "tracks": g["tracks"]}
            for g in module["gables"]
        ],
        **change,
    }
    return world.as_(person.id).put(f"{API}/modules/{module['id']}", json=body)


# --- A module from measures -----------------------------------------------------------------


def test_a_straight_module_from_measures_gets_its_number_gables_and_track_graph(
    world: World,
) -> None:
    made = make(
        world, straight(a=[140], profile_a="h0-mmm-enkelspar", profile_b="h0-mmm-enkelspar")
    )
    assert made["number"] == "M-001"
    assert made["owner"] == {"kind": "person", "id": str(A.id), "name": "Provkonto A"}
    assert made["status"] == "draft" and made["version"] == 1 and made["may_edit"]
    assert [g["label"] for g in made["gables"]] == ["MMM enkelspår", "MMM enkelspår"]
    assert [g["norm"] for g in made["gables"]] == ["mmm", "mmm"]  # from the norm's profile
    assert made["graph"]["complete"] and len(made["graph"]["pieces"]) == 1
    assert made["track_length"] == 1500
    second = make(world, straight("Linje 1000", length=1000))
    assert second["number"] == "M-002"
    assert [g["label"] for g in second["gables"]] == ["Egen gavel · 1 spår"] * 2


def test_a_curve_from_string_and_sagitta(world: World) -> None:
    made = make(world, curve())
    assert made["shape"]["radius"] == 2000 and made["shape"]["angle"] == 30
    assert [p["segments"][0]["kind"] for p in made["graph"]["pieces"]] == ["arc", "arc"]
    assert [g["label"] for g in made["gables"]] == ["Dubbelspår", "Dubbelspår"]


def test_measures_that_do_not_hang_together_are_refused_with_why(world: World) -> None:
    client = world.as_(A.id)
    outside = client.post(f"{API}/modules", json=straight(a=[550], width=500))
    assert outside.status_code == 422 and outside.json()["code"] == "invalid"
    assert "utanför modulen" in outside.json()["message"]
    wrong_mmm = client.post(f"{API}/modules", json=straight(a=[150], profile_a="h0-mmm-enkelspar"))
    assert "140 mm från Kant 1" in wrong_mmm.json()["message"]
    bad_curve = curve()
    bad_curve["shape"]["radius"] = 2500
    refused = client.post(f"{API}/modules", json=bad_curve)
    assert "snöret och pilhöjden" in refused.json()["message"]
    usms_in_0 = straight(a=[300])
    usms_in_0["scale"] = "0"
    usms_in_0["gables"][0]["norm"] = "usms"
    assert client.post(f"{API}/modules", json=usms_in_0).status_code == 422
    fremo_spur_0 = straight(a=[300], width=600, profile_a="0-fremo-spur-0-enkelspar")
    fremo_spur_0["scale"] = "0"
    in_0 = client.post(f"{API}/modules", json=fremo_spur_0)
    assert in_0.status_code == 201, in_0.text
    assert in_0.json()["gables"][0]["norm"] == "fremo_spur_0"


# --- Versions and history -------------------------------------------------------------------


def test_every_save_is_a_new_version_and_the_history_lists_them(world: World) -> None:
    made = make(world, straight())
    first_piece = made["graph"]["pieces"][0]["id"]
    saved = save(world, made, shape={"kind": "straight", "length": 1520, "width": 500})
    assert saved.status_code == 200, saved.text
    second = saved.json()
    assert second["version"] == 2 and second["latest"] == 2
    assert second["graph"]["pieces"][0]["id"] == first_piece  # CAD-20
    renamed = save(world, second, name="Linje 1520").json()
    client = world.as_(A.id)
    history = client.get(f"{API}/modules/{made['id']}/history").json()
    assert [(e["kind"], e["version"], e["text"]) for e in history] == [
        ("saved", 3, "Version 3: namnet ändrat"),
        ("saved", 2, "Version 2: formen och måtten ändrade"),
        ("created", 1, "Modulen skapad ur mått"),
    ]
    assert all(e["by"] == "Provkonto A" for e in history)
    old = client.get(f"{API}/modules/{made['id']}/versions/1").json()
    assert old["version"] == 1 and old["latest"] == 3 and old["shape"]["length"] == 1500
    assert renamed["name"] == "Linje 1520"


def test_a_save_on_an_old_version_is_refused(world: World) -> None:
    made = make(world, straight())
    assert save(world, made, name="Ny").status_code == 200
    stale = save(world, made, name="Gammal")
    assert stale.status_code == 409 and stale.json()["code"] == "changed"


def test_approve_makes_the_newest_version_approved_and_a_new_save_a_draft_again(
    world: World,
) -> None:
    made = make(world, straight())
    client = world.as_(A.id)
    approved = client.post(f"{API}/modules/{made['id']}/approve", json={"version": 1}).json()
    assert approved["status"] == "approved" and approved["approved_version"] == 1
    assert approved["approved_by"] == "Provkonto A" and approved["approved_at"]
    draft = save(world, approved, name="Ändrad").json()
    assert draft["status"] == "draft" and draft["approved_version"] == 1
    old = client.post(f"{API}/modules/{made['id']}/approve", json={"version": 1})
    assert old.status_code == 409
    history = client.get(f"{API}/modules/{made['id']}/history").json()
    assert ("approved", 1, "Version 1 godkänd") in [
        (e["kind"], e["version"], e["text"]) for e in history
    ]


def test_a_removed_module_is_gone_but_its_history_stays_in_the_database(world: World) -> None:
    made = make(world, straight())
    client = world.as_(A.id)
    assert client.delete(f"{API}/modules/{made['id']}").json() == {"id": made["id"]}
    assert client.get(f"{API}/modules/{made['id']}").status_code == 404
    assert client.get(f"{API}/modules").json()["modules"] == []
    with world.app.state.db.transaction() as conn:
        kinds = [r["kind"] for r in conn.execute("SELECT kind FROM module_event ORDER BY id")]
    assert kinds == ["created", "removed"]


# --- Rights (CAD-21) ------------------------------------------------------------------------


def test_only_the_owner_changes_a_persons_module_and_a_viewer_cannot(world: World) -> None:
    world.id.join(A.id, CLUB, "Västby MJK", "member")
    world.id.join(B.id, CLUB, "Västby MJK", "member")
    made = make(world, straight(visibility="club", club=str(CLUB)))
    seen = world.as_(B.id).get(f"{API}/modules/{made['id']}")
    assert seen.status_code == 200 and seen.json()["may_edit"] is False
    refused = save(world, made, B, name="B:s namn")
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    member_ops = world.as_(B.id)
    assert (
        member_ops.post(f"{API}/modules/{made['id']}/approve", json={"version": 1}).status_code
        == 403
    )
    assert member_ops.delete(f"{API}/modules/{made['id']}").status_code == 403
    assert (
        member_ops.put(
            f"{API}/modules/{made['id']}/visibility", json={"visibility": "all"}
        ).status_code
        == 403
    )


def test_the_role_redigera_from_id_changes_the_module(world: World) -> None:
    made = make(world, straight())
    assert world.as_(B.id).get(f"{API}/modules/{made['id']}").status_code == 404
    world.id.module_roles[(B.id, made["id"])] = ["editor"]
    page = world.as_(B.id).get(f"{API}/modules/{made['id']}").json()
    assert page["may_edit"] is True
    assert save(world, made, B, name="B redigerar").json()["version"] == 2
    history = world.as_(A.id).get(f"{API}/modules/{made['id']}/history").json()
    assert history[0]["by"] == "Provkonto B"


def test_a_clubs_module_is_changed_by_the_clubs_administrators(world: World) -> None:
    world.id.join(A.id, CLUB, "Västby MJK", "admin")
    world.id.join(B.id, CLUB, "Västby MJK", "member")
    world.id.join(C.id, CLUB, "Västby MJK", "admin")
    made = make(world, straight(owner=str(CLUB), visibility="club"))
    assert made["owner"] == {"kind": "club", "id": str(CLUB), "name": "Västby MJK"}
    assert made["club"] == str(CLUB)
    assert save(world, made, C, name="Klubbens linje").status_code == 200
    member = world.as_(B.id).get(f"{API}/modules/{made['id']}").json()
    assert member["may_edit"] is False
    assert save(world, member, B, name="Medlemmens").status_code == 403
    # Only the club's administrator adds the club's modules.
    refused = world.as_(B.id).post(f"{API}/modules", json=straight(owner=str(CLUB)))
    assert refused.status_code == 403
    stranger = world.as_(D.id).post(f"{API}/modules", json=straight(owner=str(CLUB)))
    assert stranger.status_code == 404


def test_the_visibility_jag_klubben_alla(world: World) -> None:
    world.id.join(A.id, CLUB, "Västby MJK", "member")
    world.id.join(B.id, CLUB, "Västby MJK", "member")
    world.id.join(C.id, OTHER_CLUB, "Östby MJ", "member")
    made = make(world, straight())
    assert made["visibility"] == "me"
    for person in (B, C):
        assert world.as_(person.id).get(f"{API}/modules/{made['id']}").status_code == 404
    owner = world.as_(A.id)
    to_club = owner.put(f"{API}/modules/{made['id']}/visibility", json={"visibility": "club"})
    assert to_club.json()["club_name"] == "Västby MJK"  # the only club, chosen by itself
    assert world.as_(B.id).get(f"{API}/modules/{made['id']}").status_code == 200
    assert world.as_(C.id).get(f"{API}/modules/{made['id']}").status_code == 404
    not_mine = owner.put(
        f"{API}/modules/{made['id']}/visibility",
        json={"visibility": "club", "club": str(OTHER_CLUB)},
    )
    assert not_mine.status_code == 422
    owner.put(f"{API}/modules/{made['id']}/visibility", json={"visibility": "all"})
    assert world.as_(C.id).get(f"{API}/modules/{made['id']}").status_code == 200
    history = owner.get(f"{API}/modules/{made['id']}/history").json()
    assert [e["text"] for e in history[:2]] == [
        "Vem ser modulen: Alla i TrainMeet",
        "Vem ser modulen: Min klubb · Västby MJK",
    ]


def test_the_libraries_mine_my_clubs_and_everything_i_see_with_search(world: World) -> None:
    world.id.join(A.id, CLUB, "Västby MJK", "admin")
    world.id.join(B.id, CLUB, "Västby MJK", "member")
    make(world, straight("Exempelstation"))
    make(world, straight("Klubbens kurva", owner=str(CLUB), visibility="club"))
    make(world, straight("B:s delade", visibility="club", club=str(CLUB)), B)
    make(world, straight("B:s egen"), B)
    make(world, straight("D för alla", visibility="all"), D)
    client = world.as_(A.id)
    names = {
        library: [
            m["name"]
            for m in client.get(f"{API}/modules", params={"library": library}).json()["modules"]
        ]
        for library in ("mine", f"club:{CLUB}", "all")
    }
    assert names == {
        "mine": ["Exempelstation"],
        f"club:{CLUB}": ["B:s delade", "Klubbens kurva"],
        "all": ["Exempelstation", "B:s delade", "D för alla", "Klubbens kurva"],
    }
    libraries = client.get(f"{API}/libraries").json()
    assert [(lib["id"], lib["name"], lib["may_add"]) for lib in libraries] == [
        ("mine", "Mitt modulbibliotek", True),
        (f"club:{CLUB}", "Västby MJK", True),
        ("all", "Alla moduler jag ser", False),
    ]
    found = client.get(f"{API}/modules", params={"library": "all", "q": "delade"}).json()
    assert [m["name"] for m in found["modules"]] == ["B:s delade"]
    by_number = client.get(f"{API}/modules", params={"q": "m-001"}).json()["modules"]
    assert [m["name"] for m in by_number] == ["Exempelstation"]
    assert client.get(f"{API}/modules", params={"library": f"club:{OTHER_CLUB}"}).status_code == 404


def test_without_an_answer_from_id_the_own_modules_still_work(world: World) -> None:
    made = make(world, straight())
    world.id.down = True
    client = world.as_(A.id)
    assert client.get(f"{API}/modules").json()["modules"][0]["id"] == made["id"]
    assert client.get(f"{API}/modules/{made['id']}").status_code == 200
    assert client.get(f"{API}/modules", params={"library": "all"}).status_code == 503


# --- Gable profiles -------------------------------------------------------------------------


def test_the_norms_per_scale_and_their_profiles(world: World) -> None:
    client = world.as_(A.id)
    h0 = client.get(f"{API}/profiles", params={"scale": "H0"}).json()
    assert [n["name"] for n in h0["norms"]] == ["FREMO", "MMM", "USMS", "Klubbens egen"]
    by_id = {p["id"]: p for p in h0["profiles"]}
    assert by_id["h0-mmm-enkelspar"]["first"] == 140
    assert by_id["h0-mmm-dubbelspar"]["spacings"] == [57]
    assert by_id["h0-mmm-fyrspar"]["spacings"] == [57, 86, 57]
    fremo = by_id["h0-fremo-dubbelspar"]
    assert fremo["read"] is False and fremo["first"] is None and fremo["spacings"] == [None]
    assert by_id["h0-dubbelspar"]["kind"] == "general"
    zero = client.get(f"{API}/profiles", params={"scale": "0"}).json()
    assert [n["name"] for n in zero["norms"]] == ["FREMO Spur 0"]
    n = client.get(f"{API}/profiles", params={"scale": "N"}).json()
    assert n["norms"] == [] and {p["kind"] for p in n["profiles"]} == {"general"}


def test_profiles_count_the_gables_that_use_them(world: World) -> None:
    make(world, straight(a=[140], profile_a="h0-mmm-enkelspar", profile_b="h0-mmm-enkelspar"))
    make(world, straight(a=[140], profile_a="h0-mmm-enkelspar"))
    make(world, curve())
    uses = {
        p["id"]: p["uses"]
        for p in world.as_(A.id).get(f"{API}/profiles", params={"scale": "H0"}).json()["profiles"]
    }
    assert uses["h0-mmm-enkelspar"] == 3
    assert uses["h0-dubbelspar"] == 2
    assert uses["h0-fremo-enkelspar"] == 0
    listed = world.as_(A.id).get(f"{API}/modules").json()
    assert listed["gables"][:2] == [
        {"label": "MMM enkelspår", "profile": "h0-mmm-enkelspar", "count": 3},
        {"label": "Dubbelspår", "profile": "h0-dubbelspar", "count": 2},
    ]
    # Only the person's own modules count: B sees none of them.
    b_uses = world.as_(B.id).get(f"{API}/profiles", params={"scale": "H0"}).json()["profiles"]
    assert all(p["uses"] == 0 for p in b_uses)


def test_an_own_profile_and_the_clubs_own_norm(world: World) -> None:
    world.id.join(A.id, CLUB, "Västby MJK", "admin")
    world.id.join(B.id, CLUB, "Västby MJK", "member")
    client = world.as_(A.id)
    own = client.post(
        f"{API}/profiles",
        json={"name": "Egen · 6 spår", "scale": "H0", "tracks": [53, 134, 184, 236, 580, 631]},
    )
    assert own.status_code == 201, own.text
    profile = own.json()
    assert profile["kind"] == "own" and profile["first"] == 53
    assert profile["spacings"] == [81, 50, 52, 344, 51]
    made = make(
        world,
        straight(
            "Modul 1213 × 680",
            length=1213,
            width=680,
            a=[53, 134, 184, 236, 580, 631],
            b=[53, 526, 578, 631],
            profile_a=profile["id"],
        ),
    )
    assert made["gables"][0]["label"] == "Egen · 6 spår"
    assert made["graph"]["complete"] is False
    club_norm = client.post(
        f"{API}/profiles",
        json={
            "name": "Västbys gavel",
            "scale": "H0",
            "norm": "club",
            "owner": str(CLUB),
            "tracks": [200],
        },
    )
    assert club_norm.status_code == 201 and club_norm.json()["owner"]["kind"] == "club"
    mine_as_club_norm = client.post(
        f"{API}/profiles", json={"name": "Min norm", "scale": "H0", "norm": "club", "tracks": [200]}
    )
    assert mine_as_club_norm.status_code == 422
    member = world.as_(B.id)
    refused = member.post(
        f"{API}/profiles",
        json={"name": "Medlemmens", "scale": "H0", "owner": str(CLUB), "tracks": [200]},
    )
    assert refused.status_code == 403
    seen = [p["id"] for p in member.get(f"{API}/profiles").json()["profiles"]]
    assert club_norm.json()["id"] in seen and profile["id"] not in seen
    # Someone else's own profile cannot be used on one's own module.
    other = member.post(f"{API}/modules", json=straight(a=[53], profile_a=profile["id"]))
    assert other.status_code == 422


def test_an_editor_keeps_the_owners_own_gable_profile(world: World) -> None:
    """CAD-21: someone with the role redigera changes a module whose gable is the owner's own
    profile, which they do not see among their own."""
    own = world.as_(A.id).post(
        f"{API}/profiles", json={"name": "Min gavel", "scale": "H0", "tracks": [120, 170]}
    )
    made = make(
        world, straight(a=[120, 170], profile_a=own.json()["id"], profile_b=own.json()["id"])
    )
    world.id.module_roles[(B.id, made["id"])] = ["editor"]
    saved = save(world, made, B, name="B:s ändring")
    assert saved.status_code == 200, saved.text
    assert saved.json()["gables"][0]["label"] == "Min gavel"
