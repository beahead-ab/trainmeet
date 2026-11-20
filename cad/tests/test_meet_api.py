"""The meet's assembly to the Hub (part d3, CAD-11, CAD-12, K4): the cloud hub's Planering lists
the planner's assemblies and fetches one with the planner's access token from ID for the client
hub, and nothing else's; the assembly comes with its modules at the versions it pins, without
their owners."""

from __future__ import annotations

from cad.tests.conftest import API, A, B, World
from cad.tests.test_assemblies_api import tkl_token, two_joined
from contracts.cad import MeetAssembly

MEET = f"{API}/meet/assemblies"


def test_the_hub_fetches_the_assembly_with_the_planners_token_and_nothing_else(
    world: World,
) -> None:
    found, first, second = two_joined(world)
    browser = world.browser()
    with browser:
        tkl = {"Authorization": f"Bearer {tkl_token(world, A.id)}"}
        # A station in TKL took the first module into use (Används i, CAD-15).
        used = browser.put(
            f"{API}/studio/module/{first['id']}/station",
            headers=tkl,
            json={"station_id": "exb", "name": "Exempelby", "revision": 1},
        )
        assert used.status_code == 200, used.text
        hub = {"Authorization": f"Bearer {tkl_token(world, A.id, azp='hub')}"}
        listed = browser.get(MEET, headers=hub)
        assert listed.status_code == 200, listed.text
        assert [a["name"] for a in listed.json()] == ["Anläggning 1"]
        answer = browser.get(f"{MEET}/{found['id']}", headers=hub)
        assert answer.status_code == 200, answer.text
        assembly = MeetAssembly.model_validate(answer.json())
        assert assembly.format == "trainmeet.cad-assembly/1"
        assert assembly.revision == found["revision"]
        assert assembly.graph.model_dump(mode="json") == found["graph"]
        assert [(m.number, m.version) for m in assembly.modules] == [
            (first["number"], 1),
            (second["number"], 1),
        ]
        assert [(s.station_id, s.name) for s in assembly.modules[0].stations] == [
            ("exb", "Exempelby")
        ]
        assert assembly.modules[1].stations == []
        assert "owner" not in answer.text and A.name not in answer.text
        # The same assembly twice gives the same bytes, so the Hub's checksum stays.
        assert browser.get(f"{MEET}/{found['id']}", headers=hub).content == answer.content
        # Only the hub's token: TKL's, another app's, none or a broken one are refused.
        for bad in (tkl, {"Authorization": "Bearer inte-en-token"}, {}):
            refused = browser.get(MEET, headers=bad)
            assert refused.status_code == 401 and refused.json()["code"] == "login"
        # The hub's token does not open Studio's addresses.
        assert browser.get(f"{API}/studio", headers=hub).status_code == 401
        # Another person sees neither the assembly nor its modules.
        theirs = {"Authorization": f"Bearer {tkl_token(world, B.id, azp='hub')}"}
        assert browser.get(MEET, headers=theirs).json() == []
        assert browser.get(f"{MEET}/{found['id']}", headers=theirs).status_code == 404
