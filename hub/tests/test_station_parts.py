"""En del av en station som egen driftplats (#87, PLAN-34, TRAFIK-35, TKL101): the station's
outside lists its parts that are staffed on their own. Coupled in Planering, each part becomes a
place of its own next to the station's, linked to the same station, or a place the plan already
has is linked and the planner is asked to confirm it. The version carries the link. A TKL for
the station asks for one place per part when it connects; Trafikledningen approves or refuses
each on its own, a refused part does not stop the station, and only the TKL that holds the
part's place may report for it."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from contracts import drift, planning, station
from contracts.meet import MeetPackage, PlaceKind
from hub.tests.test_planering import API, DRIFT, MEET, hub, planned
from hub.tests.test_stations import added, couple, outside

__all__ = ["hub", "planned"]

STATION = "/api/station/1"
LEKBY = "p4"
SKUGGEVIK = "p23"  # Skuggevik in Värnamo's plan, with Skuggvik havn (p24) beside it
HAVN = "p24"
YARD = {"id": "lokstall", "name": "Lekby lokstall", "code": "Lls"}


def with_parts(*parts: dict[str, Any]) -> dict[str, Any]:
    """Lekby as its owner drew it, with the parts that are their own driftplatser (TKL101)."""
    return {**outside(), "parts": list(parts)}


def skuggevik(*parts: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "trainmeet.station-outside/1",
        "station_id": "skuggevik-tkl",
        "name": "Skuggevik",
        "tracks": [{"id": str(n), "label": f"Spår {n}"} for n in range(1, 9)],
        "exits": [{"id": "v", "side": "left"}, {"id": "o", "side": "right"}],
        "parts": list(parts),
    }


def draft_of(client: TestClient) -> planning.Draft:
    return planning.Draft.model_validate(client.get(f"{API}/meets/{MEET}").json())


def places_of(found: planning.Draft) -> list[Any]:
    assert found.package is not None
    return list(found.package.places)


def save(client: TestClient, *changes: dict[str, Any]) -> Any:
    given = {"revision": draft_of(client).revision, "changes": list(changes)}
    return client.post(f"{API}/meets/{MEET}/changes", json=given)


# --- Planering (PLAN-34) ----------------------------------------------------------------------


def test_coupling_a_station_makes_its_part_a_place_next_to_it(planned: TestClient) -> None:
    added(planned, with_parts(YARD))
    coupled = couple(planned, "lekby-tkl")
    assert coupled.status_code == 200, coupled.text
    order = [p.id for p in places_of(planning.Draft.model_validate(coupled.json()))]
    assert order[order.index(LEKBY) + 1] == "lokstall", "the part stands right after its station"
    found = draft_of(planned)
    part = next(p for p in places_of(found) if p.id == "lokstall")
    assert (part.name, part.code, part.kind, part.part_of) == (
        "Lekby lokstall",
        "Lls",
        PlaceKind.MANNED,
        LEKBY,
    )
    assert part.station is not None
    assert (part.station.station_id, part.station.part) == ("lekby-tkl", "lokstall")
    home = next(p for p in places_of(found) if p.id == LEKBY)
    assert home.part_of is None and home.station is not None and home.station.part is None
    # Where it comes from: the station's outside among the sources.
    fact = next(f for f in found.facts if f.ref == "place:lokstall")
    assert fact.origins[0].at == "Delen lokstall"
    # No train leaves it in the plan: said, nothing moved (TKL108).
    check = planning.Check.model_validate(planned.get(f"{API}/meets/{MEET}/check").json())
    [said] = [f for f in check.findings if f.code == "part_without_trains"]
    assert "Inget tåg avgår från Lekby lokstall" in said.message and "Lekby" in said.message
    assert not [
        f
        for f in check.findings
        if f.code in ("unused_places", "no_section") and "lokstall" in f.refs
    ]
    assert check.blocking == [], "a part hangs together with its station"


def test_the_part_keeps_the_planners_changes_and_goes_with_the_station(
    planned: TestClient,
) -> None:
    added(planned, with_parts(YARD))
    assert couple(planned, "lekby-tkl").status_code == 200
    phone = save(planned, {"place": "lokstall", "phone": "455"})
    assert phone.status_code == 200, phone.text
    # Read again with a new outside: the part is made again, with its phone.
    newer = added(planned, with_parts({**YARD, "name": "Lokstallet"}))
    part = next(p for p in places_of(newer) if p.id == "lokstall")
    assert (part.name, part.phone) == ("Lokstallet", "455")
    assert part.station is not None and part.station.version == 2
    # A part follows its station: it is not coupled on its own.
    refused = save(planned, {"place": "lokstall", "station": "lekby-tkl"})
    assert refused.status_code == 409 and "följer stationens koppling" in refused.json()["detail"]
    # Koppla bort: the part's place goes with the coupling.
    gone = planning.Draft.model_validate(couple(planned, None).json())
    assert "lokstall" not in [p.id for p in places_of(gone)]
    assert not [f for f in gone.facts if f.ref.startswith("place:lokstall")]


def test_a_place_the_plan_has_is_linked_and_the_planner_confirms_it(planned: TestClient) -> None:
    """Skuggvik havn is in Värnamo's plan already: linked by its name, and asked about."""
    added(planned, skuggevik({"id": "havn", "name": "Skuggvik havn"}))
    coupled = save(planned, {"place": SKUGGEVIK, "station": "skuggevik-tkl"})
    assert coupled.status_code == 200, coupled.text
    found = planning.Draft.model_validate(coupled.json())
    havn = next(p for p in places_of(found) if p.id == HAVN)
    assert havn.part_of == SKUGGEVIK and havn.station is not None and havn.station.part == "havn"
    assert "havn" not in [p.id for p in places_of(found)]
    [asked] = [q for q in found.questions if q.cause == "station_part"]
    assert asked.message == (
        "Är driftplatsen Skuggvik havn i planen delen Skuggvik havn av stationen Skuggevik i "
        "Skuggevik?"
    )
    assert [a.value for a in asked.alternatives] == [HAVN, "new"]
    assert f"place:{HAVN}" in asked.refs
    # Nej: the part gets a place of its own, and Skuggvik havn is the plan's place again.
    answered = planned.post(
        f"{API}/meets/{MEET}/answers", json={"question": asked.id, "value": "new"}
    )
    assert answered.status_code == 200, answered.text
    found = planning.Draft.model_validate(answered.json())
    havn = next(p for p in places_of(found) if p.id == HAVN)
    assert havn.part_of is None and havn.station is None
    made = next(p for p in places_of(found) if p.id == "havn")
    assert made.part_of == SKUGGEVIK and made.code == "Skuggvik havn", "no code: the name"
    # Ja: linked, and the question is answered.
    again = planned.post(f"{API}/meets/{MEET}/answers", json={"question": asked.id, "value": HAVN})
    found = planning.Draft.model_validate(again.json())
    assert next(p for p in places_of(found) if p.id == HAVN).part_of == SKUGGEVIK
    assert "havn" not in [p.id for p in places_of(found)]
    [asked] = [q for q in found.questions if q.cause == "station_part"]
    assert asked.answer == HAVN


def test_the_version_carries_the_part_with_its_link(planned: TestClient) -> None:
    added(planned, with_parts(YARD))
    assert couple(planned, "lekby-tkl").status_code == 200
    assert planned.post(f"{API}/meets/{MEET}/versions").status_code == 201
    package = MeetPackage.model_validate(planned.get(f"{API}/meets/{MEET}/versions/1").json())
    ids = [p.id for p in package.places]
    assert ids[ids.index(LEKBY) + 1] == "lokstall"
    part = next(p for p in package.places if p.id == "lokstall")
    assert part.part_of == LEKBY and part.station is not None
    assert (part.station.station_id, part.station.part) == ("lekby-tkl", "lokstall")
    assert [p.id for p in part.station.outside.parts] == ["lokstall"]


# --- Drift and Trafikledningen (TRAFIK-35) -----------------------------------------------------


@pytest.fixture
def meet(planned: TestClient) -> TestClient:
    """Värnamo with Lekby and its yard coupled in advance, published and started."""
    added(planned, with_parts(YARD))
    assert couple(planned, "lekby-tkl").status_code == 200
    assert planned.post(f"{API}/meets/{MEET}/versions").status_code == 201
    started = planned.post(DRIFT + "/start", json={"meet": MEET, "version": 1})
    assert started.status_code == 201, started.text
    return planned


class Tkl:
    """A station client that connects with the meet's code."""

    def __init__(self, hub: TestClient, given: dict[str, Any], kind: str = "tkl") -> None:
        code = hub.get(DRIFT + "/connect").json()["code"]
        body = {"kind": kind, "name": f"TKL {given.get('name', 'app')}", "software": "TKL 0.1.0"}
        response = hub.post(STATION + "/connect", json={**body, **given, "code": code})
        assert response.status_code == 201, response.text
        self.hub, self.client_id = hub, response.json()["client_id"]
        self.headers: dict[str, str] = {}

    def poll(self) -> station.ConnectReply:
        reply = station.ConnectReply.model_validate(
            self.hub.get(f"{STATION}/connect/{self.client_id}").json()
        )
        if reply.key:
            self.headers = {"Authorization": "Bearer " + reply.key}
        return reply

    def listed(self) -> drift.Client:
        found = next(
            c for c in self.hub.get(DRIFT + "/clients").json() if c["client_id"] == self.client_id
        )
        return drift.Client.model_validate(found)

    def answer(self, action: str, *places: str) -> drift.Client:
        response = self.hub.post(
            f"{DRIFT}/clients/{action}", json={"client_id": self.client_id, "places": list(places)}
        )
        assert response.status_code == 200, response.text
        return drift.Client.model_validate(response.json())

    def report(self, place: str, context: station.MeetContext) -> Any:
        body = {
            "message_id": uuid4().hex,
            "client_id": self.client_id,
            "place": place,
            "context": context.model_dump(mode="json"),
            "action": station.Action.TRAIN_LOOKUP.value,
            "payload": {"train_number": "1"},
        }
        return self.hub.post(STATION + "/commands", json=body, headers=self.headers)

    def snapshot(self, place: str) -> Any:
        return self.hub.get(f"{STATION}/places/{place}", headers=self.headers)


def said(client: drift.Client) -> list[tuple[str, str, str | None]]:
    return [(w.place, w.status.value, w.part_of) for w in client.wanted]


def test_a_station_with_a_part_asks_for_both_and_each_is_answered_alone(meet: TestClient) -> None:
    tkl = Tkl(meet, {"outside": with_parts(YARD)})
    first = tkl.listed()
    assert first.status == station.ApprovalStatus.WAITING
    assert first.places == [LEKBY, "lokstall"], "wants: the station's place and one per part"
    assert said(first) == [(LEKBY, "waiting", None), ("lokstall", "waiting", LEKBY)]
    assert [w.part for w in first.wanted] == [None, "lokstall"]
    # Approve the station: the part still waits, so the TKL stays under Väntar.
    approved = tkl.answer("approve", LEKBY)
    assert approved.status == station.ApprovalStatus.APPROVED
    assert said(approved) == [(LEKBY, "approved", None), ("lokstall", "waiting", LEKBY)]
    listed = meet.get(DRIFT + "/clients").json()
    assert listed[0]["client_id"] == tkl.client_id, "a client with a place waiting comes first"
    reply = tkl.poll()
    assert (reply.status, reply.places) == (station.ApprovalStatus.APPROVED, [LEKBY])
    key = dict(tkl.headers)
    # Refuse the part: the station goes on.
    refused = tkl.answer("refuse", "lokstall")
    assert refused.status == station.ApprovalStatus.APPROVED
    assert said(refused) == [(LEKBY, "approved", None), ("lokstall", "refused", LEKBY)]
    assert tkl.poll().places == [LEKBY]
    assert tkl.snapshot(LEKBY).status_code == 200
    context = station.Snapshot.model_validate(tkl.snapshot(LEKBY).json()).context
    assert tkl.report(LEKBY, context).status_code == 200
    assert tkl.report("lokstall", context).status_code == 403, "a refused part is not its"
    # Approved after all: the same key, now for the part too.
    again = tkl.answer("approve", "lokstall")
    assert said(again) == [(LEKBY, "approved", None), ("lokstall", "approved", LEKBY)]
    reply = tkl.poll()
    assert (reply.places, reply.key) == ([LEKBY, "lokstall"], None)
    assert tkl.headers == key
    assert tkl.snapshot("lokstall").status_code == 200
    assert tkl.report("lokstall", context).status_code == 200


def test_a_report_for_the_part_comes_only_from_the_tkl_that_holds_it(meet: TestClient) -> None:
    tkl = Tkl(meet, {"outside": with_parts(YARD)})
    tkl.answer("approve", LEKBY, "lokstall")
    tkl.poll()
    app = Tkl(meet, {"name": "Lekby", "wants": [LEKBY]}, kind="tmbox_app")
    assert app.listed().places == [LEKBY], "an app without an outside asks for what it named"
    app.answer("approve", LEKBY)
    app.poll()
    context = station.Snapshot.model_validate(app.snapshot(LEKBY).json()).context
    assert app.report(LEKBY, context).status_code == 200
    assert app.report("lokstall", context).status_code == 403
    assert app.snapshot("lokstall").status_code == 403
    assert tkl.report("lokstall", context).status_code == 200
    # Refusing the station leaves the TKL its part: a part stands on its own.
    left = tkl.answer("refuse", LEKBY)
    assert left.status == station.ApprovalStatus.APPROVED and left.places == ["lokstall"]
    assert tkl.report(LEKBY, context).status_code == 403
    assert tkl.report("lokstall", context).status_code == 200
    # Nothing left: the key stops working, and the TKL is refused.
    none = tkl.answer("refuse", "lokstall")
    assert none.status == station.ApprovalStatus.REFUSED
    assert said(none) == [(LEKBY, "refused", None), ("lokstall", "refused", LEKBY)]
    assert tkl.report("lokstall", context).status_code == 401
    assert tkl.poll().status == station.ApprovalStatus.REFUSED


def test_a_part_not_coupled_in_advance_is_found_by_its_name(meet: TestClient) -> None:
    """Skuggevik is not coupled in the version: its place by the station's name, and the part's
    by the part's name (TRAFIK-35)."""
    tkl = Tkl(meet, {"outside": skuggevik({"id": "havn", "name": "Skuggvik havn"})})
    assert said(tkl.listed()) == [(SKUGGEVIK, "waiting", None), (HAVN, "waiting", SKUGGEVIK)]
    # Without the part in its outside, the owner runs it: Hubben never sees it (TKL101).
    alone = Tkl(meet, {"outside": skuggevik()})
    assert alone.listed().places == [SKUGGEVIK]
    # A TKL that names its places keeps them, and gets its parts besides.
    named = Tkl(meet, {"outside": with_parts(YARD), "wants": [LEKBY]})
    assert named.listed().places == [LEKBY, "lokstall"]


def test_nu_shows_the_part_with_its_station(meet: TestClient) -> None:
    now = drift.Now.model_validate(meet.get(DRIFT + "/now").json())
    places = {p.place: p for p in now.places}
    assert places["lokstall"].part_of == LEKBY
    assert places[LEKBY].part_of is None
    automation = drift.AutomationStatus.model_validate(meet.get(DRIFT + "/automation").json())
    assert "lokstall" in [p.place for p in automation.places]
