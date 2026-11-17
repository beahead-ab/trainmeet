"""TKL ansluter (KLAR-02, KLAR-13, H23): på träffens nät utan kod, över internet med kod. Och
utfarterna (H26, PLAN-31, TRAFIK-05): Hubben gissar och frågar, och stationen i TKL eller
trafikledningen i Klienter svarar; det första svaret gäller och minns till nästa träff."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import station
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_tmbox_web import started

API = "/api/station/1"
PIN = "482915"
ON_THE_MEET = ("192.168.4.20", 50000)
OUTSIDE = ("203.0.113.7", 50000)

# Mellanå as TKL Studio writes it at level 0: double track to Åsen on the left, with an up and a
# down track, and Sjövik to the right. Åsen is coupled in advance in Provbanan; Mellanå is not.
MELLANA = {
    "station_id": "mellana",
    "name": "Mellanå",
    "tracks": [{"id": "1", "label": "Spår 1"}, {"id": "2", "label": "Spår 2"}],
    "exits": [
        {"id": "AU", "side": "left", "name": "Åsen uppspår"},
        {"id": "AN", "side": "left", "name": "Åsen nedspår"},
        {"id": "S", "side": "right", "name": "Mot Sjövik"},
    ],
}


def connect(hub: TestClient, **given: Any) -> Any:
    body = {"kind": "tkl", "name": "TKL Mellanå", "software": "TKL 0.1.0", **given}
    body.setdefault("outside", MELLANA)
    return hub.post(API + "/connect", json=body)


@pytest.fixture
def made(tmp_path: Path) -> Any:
    return create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "p.db")


@pytest.fixture
def meet(made: Any) -> TestClient:
    """The hub's own meet, started, as on the Pi."""
    admin = TestClient(made, client=ON_THE_MEET)
    assert admin.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    assert admin.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    return admin


def test_on_the_meets_network_a_tkl_needs_no_code(made: Any, meet: TestClient) -> None:
    """KLAR-13: the hub announces itself and the TKL connects without a code. Over the internet,
    or through a proxy, a code from the dispatcher is needed (S2, H23)."""
    joined = connect(TestClient(made, client=ON_THE_MEET))
    assert joined.status_code == 201, joined.text
    client_id = joined.json()["client_id"]
    listed = {c["client_id"]: c for c in meet.get("/api/drift/1/clients").json()}
    assert listed[client_id]["status"] == "waiting"
    assert listed[client_id]["places"] == ["mla"], "Klienter suggests the place named Mellanå"
    assert listed[client_id]["station_id"] == "mellana"
    for outside in (
        TestClient(made, client=OUTSIDE),
        TestClient(made, client=ON_THE_MEET, headers={"X-Forwarded-For": "203.0.113.7"}),
    ):
        refused = connect(outside)
        assert refused.status_code == 401
        assert refused.json()["detail"] == "Över internet behövs en kod från trafikledningen."


def test_no_meet_no_connection(made: Any) -> None:
    admin = TestClient(made, client=ON_THE_MEET)
    assert admin.post("/api/hub/setup", json={"name": "Pi:n", "pin": PIN}).status_code == 201
    refused = connect(admin)
    assert (refused.status_code, refused.json()["detail"]) == (
        404,
        "Ingen träff är startad på hubben.",
    )


class Tkl:
    def __init__(self, hub: TestClient, code: str) -> None:
        response = connect(hub, code=code)
        assert response.status_code == 201, response.text
        self.hub, self.client_id = hub, response.json()["client_id"]
        self.headers: dict[str, str] = {}

    def key(self) -> None:
        reply = self.hub.get(f"{API}/connect/{self.client_id}").json()
        self.headers = {"Authorization": "Bearer " + reply["key"]}

    def snapshot(self) -> station.Snapshot:
        response = self.hub.get(f"{API}/places/mla", headers=self.headers)
        assert response.status_code == 200, response.text
        return station.Snapshot.model_validate(response.json())

    def answer(self, section: str, exit_id: str) -> Any:
        return self.hub.post(
            f"{API}/places/mla/exits",
            json={"section": section, "exit": exit_id},
            headers=self.headers,
        )


def approved(hub: TestClient) -> Tkl:
    tkl = Tkl(hub, started(hub))
    answer = hub.post(
        "/api/provbanan/clients/approve", json={"client_id": tkl.client_id, "places": ["mla"]}
    )
    assert answer.status_code == 200, answer.text
    tkl.key()
    return tkl


def test_hubben_guesses_the_exits_and_asks_about_the_double_track(made: Any) -> None:
    """Sjövik: the exit named Mot Sjövik. Åsen: two exits on the left side, both named after
    Åsen, so Hubben asks; TKL answers, and the first answer stands."""
    hub = TestClient(made)
    tkl = approved(hub)
    seen = tkl.snapshot()
    exits = {s.section: s.exit for s in seen.sections}
    assert exits == {"s-asn-mla": None, "s-mla-sjv": "S"}
    [question] = seen.questions
    assert (question.section, question.other_name, question.side) == ("s-asn-mla", "Åsen", "left")
    assert [a.exit for a in question.alternatives] == ["AU", "AN"]
    # The dispatcher sees the same question in Klienter.
    listed = hub.get("/api/provbanan/clients").json()["clients"]
    [client] = [c for c in listed if c["client_id"] == tkl.client_id]
    assert [q["section"] for q in client["questions"]] == ["s-asn-mla"]
    # TKL answers first.
    answered = tkl.answer("s-asn-mla", "AU")
    assert answered.status_code == 200, answered.text
    after = station.Snapshot.model_validate(answered.json())
    assert {s.section: s.exit for s in after.sections}["s-asn-mla"] == "AU"
    assert after.questions == []
    assert tkl.answer("s-asn-mla", "AU").status_code == 200, "the same answer again is fine"
    # Klienter answers too late, or wrong.
    late = hub.post(
        "/api/provbanan/clients/exit",
        json={"client_id": tkl.client_id, "section": "s-asn-mla", "exit": "AN"},
    )
    assert (late.status_code, late.json()["detail"]) == (
        409,
        "Frågan är redan besvarad: utfart AU.",
    )
    assert tkl.answer("s-mla-sjv", "X9").status_code == 404
    assert tkl.answer("s-nby-asn", "AU").status_code == 404, "not a section at Mellanå"
    assert {s.section: s.exit for s in tkl.snapshot().sections}["s-asn-mla"] == "AU"


def test_a_station_coupled_in_advance_brings_its_table(made: Any) -> None:
    """KLAR-12: Åsen is coupled in advance in Provbanan, with its outside pinned in the version
    and the planner's table. That is what counts, not what the TKL brings."""
    hub = TestClient(made)
    code = started(hub)
    other = {**MELLANA, "station_id": "asen", "name": "Åsen"}
    client_id = connect(hub, code=code, outside=other).json()["client_id"]
    listed = hub.get("/api/provbanan/clients").json()["clients"]
    assert [c["places"] for c in listed if c["client_id"] == client_id] == [["asn"]]
    hub.post("/api/provbanan/clients/approve", json={"client_id": client_id, "places": ["asn"]})
    key = hub.get(f"{API}/connect/{client_id}").json()["key"]
    seen = hub.get(f"{API}/places/asn", headers={"Authorization": "Bearer " + key}).json()
    assert {s["section"]: s["exit"] for s in seen["sections"]} == {
        "s-nby-asn": "v",
        "s-asn-mla": "o",
    }
    assert seen["questions"] == []


def test_klienter_answers_and_the_next_meet_remembers(made: Any, meet: TestClient) -> None:
    """TRAFIK-05 in the hub's own meet, then a new meet: the same station and neighbour need no
    question (H26, förra träffens svar)."""
    near = TestClient(made, client=ON_THE_MEET)
    client_id = connect(near).json()["client_id"]
    approval = meet.post(
        "/api/drift/1/clients/approve", json={"client_id": client_id, "places": ["mla"]}
    )
    assert [q["section"] for q in approval.json()["questions"]] == ["s-asn-mla"]
    answered = meet.post(
        "/api/drift/1/clients/exit",
        json={"client_id": client_id, "section": "s-asn-mla", "exit": "AN"},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["questions"] == []
    # Byt träff: a new run of the meet. The TKL connects again and is approved again (B14).
    assert meet.post("/api/drift/1/start", json={"version": 1}).status_code == 201
    again = connect(near).json()["client_id"]
    listed = meet.post(
        "/api/drift/1/clients/approve", json={"client_id": again, "places": ["mla"]}
    ).json()
    assert listed["questions"] == [], "last meet's answer for Åsen is remembered"
    key = near.get(f"{API}/connect/{again}").json()["key"]
    seen = near.get(f"{API}/places/mla", headers={"Authorization": "Bearer " + key}).json()
    assert {s["section"]: s["exit"] for s in seen["sections"]} == {
        "s-asn-mla": "AN",
        "s-mla-sjv": "S",
    }
