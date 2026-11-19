"""TKL i molnet (#88): the station belongs to the account in TrainMeet ID, is opened from Hubbens
Synk, and connects to the meet through the cloud hub's relay (TKL5, TKLMOLN-01–TKLMOLN-11).

TKL in the cloud, the cloud hub, a pretend Pi and a pretend ID run in one process. TKL logs in
as the public client tkl; the hub takes the owner from TKL's token, and the meets the person may
join from ID's API (#78 del b). A made-up station; nothing here names a real one (RS13).
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import station
from contracts.sync import StationPackage
from contracts.tkl import (
    TklCloudStations,
    TklConnection,
    TklIdState,
    TklMeets,
    TklMode,
    TklSaved,
    TklState,
)
from hub import id_login as hub_id
from hub.app import create_app as create_hub
from hub.build_info import BuildInfo
from hub.tests.test_planering import API as PLANERING
from hub.tests.test_planering import DRIFT, MEET, PIN, upload
from hub.tests.test_relay import relaying
from hub.tests.test_synk import follower, link, wire
from hub.tests.test_tmbox_web import started
from tests.test_tkl_id import CLOUD, INTERNAL, ISSUER, PretendId
from tkl.app import create_app as create_tkl
from tkl.id_login import TklIdSettings

TKL_API = "/api/tkl/1"
TKL = "https://tkl.example.test"
ID_API = "http://id-api:8080"
OUR_MEET = uuid.uuid4()
NOT_OURS = uuid.uuid4()


@dataclass
class PretendIdWithApi(PretendId):
    """ID for TKL, the public client, and for the hub: its own token and the meets of the
    person's clubs (ID10). Each login names the person a test chooses."""

    names: dict[str, str] = field(default_factory=dict)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token") and b"client_credentials" in request.content:
            return httpx.Response(200, json={"access_token": "app-token", "expires_in": 300})
        if request.url.host == "id-api":
            assert request.headers["authorization"] == "Bearer app-token"
            if request.url.path == "/api/id/1/apps/meets":
                person = request.url.params["person"]
                return httpx.Response(200, json=[self.meet(person)])
            return httpx.Response(404)
        return super().handle(request)

    def meet(self, person: str) -> dict[str, Any]:
        """The person's club has one meet; the other meet in the hub is another club's."""
        return {
            "id": str(OUR_MEET),
            "club": str(uuid.UUID(int=1)),
            "club_name": "Exempelby MJK",
            "name": "Höstträffen",
            "starts_on": "2026-11-20",
            "ends_on": "2026-11-22",
            "roles": [],
            "club_admin": False,
        }

    def token(self) -> str:
        """TKL's access token for the person logged in now, as the hub sees it."""
        return self.sign({"azp": "tkl"})


@pytest.fixture
def pretend() -> PretendIdWithApi:
    return PretendIdWithApi()


@pytest.fixture
def cloud(tmp_path: Path, pretend: PretendIdWithApi) -> TestClient:
    """The cloud hub with TrainMeet ID and ID's API, and the meet planned there from ID's meet,
    published as version 1."""
    settings = hub_id.IdSettings(
        issuer=ISSUER,
        secret="hemlighet",
        public_url=CLOUD,
        internal=INTERNAL,
        client="hub",
        api=ID_API,
    )
    made = create_hub(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "moln" / "p.db",
        id_settings=settings,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
    )
    client = TestClient(made)
    assert client.post("/api/hub/setup", json={"name": "Molnet", "pin": PIN}).status_code == 201
    created = client.post(
        PLANERING + "/meets",
        json={
            "name": "Värnamo Moduldagar",
            "first_date": "2026-10-30",
            "last_date": "2026-11-01",
            "id_meet": str(OUR_MEET),
        },
    )
    assert created.status_code == 201, created.text
    source = upload(client).json()["source"]["id"]
    assert client.post(f"{PLANERING}/meets/{MEET}/sources/{source}/apply").status_code == 200
    assert client.post(f"{PLANERING}/meets/{MEET}/versions").status_code == 201
    return client


def internet(cloud: TestClient, pretend: PretendIdWithApi) -> httpx.Client:
    """What TKL in the cloud reaches: ID, and the cloud hub under its public address."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("id.example.test", "id"):
            return pretend.handle(request)
        assert request.url.host == "moln.example.test", f"TKL reached {request.url.host}"
        answer = cloud.request(
            request.method,
            request.url.raw_path.decode(),
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            content=request.content,
        )
        return httpx.Response(answer.status_code, headers=answer.headers, content=answer.content)

    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture
def made(tmp_path: Path, cloud: TestClient, pretend: PretendIdWithApi) -> Any:
    settings = TklIdSettings(issuer=ISSUER, internal=INTERNAL, public_url=TKL, cloud=CLOUD)
    return create_tkl(
        tmp_path / "tkl",
        mode=TklMode.CLOUD,
        over_internet=[CLOUD],
        http=lambda: internet(cloud, pretend),
        discover=lambda: [],
        id_settings=settings,
    )


def browser(made: Any) -> TestClient:
    return TestClient(made, base_url=TKL, follow_redirects=False)


@pytest.fixture
def tkl(made: Any) -> TestClient:
    return browser(made)


def log_in(tkl: TestClient, pretend: PretendIdWithApi, person: str | None = None) -> None:
    """Logga in med TrainMeet ID: TKL's own link, ID, and back. No station or PIN first."""
    if person is not None:
        pretend.subject = person
    sent = tkl.get(TKL_API + "/id/login")
    assert sent.status_code == 303, sent.text
    query = {k: v[0] for k, v in parse_qs(urlparse(sent.headers["location"]).query).items()}
    pretend.challenge, pretend.nonce = query["code_challenge"], query["nonce"]
    back = tkl.get(TKL_API + "/id/callback", params={"code": "kod", "state": query["state"]})
    assert (back.status_code, back.headers["location"]) == (303, "/")


def state_of(tkl: TestClient) -> TklState:
    return TklState.model_validate(tkl.get(TKL_API + "/state").json())


def stations_of(tkl: TestClient) -> TklCloudStations:
    answer = tkl.get(TKL_API + "/konto/stationer")
    assert answer.status_code == 200, answer.text
    return TklCloudStations.model_validate(answer.json())


def new_station(tkl: TestClient, name: str = "Exempelby", station_id: str = "exb") -> TklState:
    made = tkl.post(TKL_API + "/konto/stationer", json={"name": name, "station_id": station_id})
    assert made.status_code == 201, made.text
    return TklState.model_validate(made.json())


def open_station(tkl: TestClient, station_id: str = "exb") -> TklState:
    opened = tkl.post(f"{TKL_API}/konto/stationer/{station_id}/oppna")
    assert opened.status_code == 200, opened.text
    return TklState.model_validate(opened.json())


def save(tkl: TestClient, on_top: int | None = None) -> TklSaved:
    body = {} if on_top is None else {"on_top": on_top}
    answer = tkl.post(TKL_API + "/id/save", json=body)
    assert answer.status_code == 200, answer.text
    return TklSaved.model_validate(answer.json())


def a_track_more(tkl: TestClient, label: str = "Spår 3") -> None:
    """An edit in Studio: one more track in the list."""
    draft = tkl.get(TKL_API + "/studio").json()["draft"]
    draft["tracks"].append({"id": str(len(draft["tracks"]) + 1), "label": label})
    assert tkl.put(TKL_API + "/studio", json=draft).status_code == 200


def in_synk(cloud: TestClient, pretend: PretendIdWithApi, station_id: str = "exb") -> list[int]:
    listed = cloud.get(
        f"/api/sync/1/stations/{station_id}/versions",
        headers={"Authorization": "Bearer " + pretend.token()},
    )
    assert listed.status_code == 200, listed.text
    return [v["version"] for v in listed.json()["versions"]]


def package_in_synk(
    cloud: TestClient, pretend: PretendIdWithApi, version: int, station_id: str = "exb"
) -> StationPackage:
    found = cloud.get(
        f"/api/sync/1/stations/{station_id}/versions/{version}",
        headers={"Authorization": "Bearer " + pretend.token()},
    )
    assert found.status_code == 200, found.text
    return StationPackage.model_validate(found.json())


# --- The station belongs to the account (TKL5, TKLMOLN-01, -02, -05, -07, -10) --------------


def test_tkl_in_the_cloud_starts_with_the_login_and_no_first_start(
    tkl: TestClient, pretend: PretendIdWithApi
) -> None:
    """TKLMOLN-01, TKLMOLN-10: one login for everything, instead of the browser-bound first
    start and its PIN."""
    before = state_of(tkl)
    assert (before.mode, before.login, before.account, before.set_up) == (
        "cloud",
        True,
        None,
        False,
    )
    first = tkl.post(
        TKL_API + "/setup", json={"name": "Exempelby", "station_id": "exb", "pin": "4711"}
    )
    assert first.status_code == 409 and "Dina stationer" in first.json()["detail"]
    assert tkl.get(TKL_API + "/konto/stationer").status_code == 401
    log_in(tkl, pretend)
    after = state_of(tkl)
    assert after.account is not None and after.account.person == "Tomas Ek"
    assert (after.set_up, after.unlocked) == (False, False), "no station is open yet"
    assert stations_of(tkl).stations == []
    # A login another site starts never begins here.
    elsewhere = tkl.get(TKL_API + "/id/login", headers={"Sec-Fetch-Site": "cross-site"})
    assert (elsewhere.status_code, elsewhere.headers["location"]) == (303, "/")


def test_a_new_station_is_saved_in_synk_at_once_and_opened(
    tkl: TestClient, cloud: TestClient, pretend: PretendIdWithApi
) -> None:
    log_in(tkl, pretend)
    opened = new_station(tkl)
    assert opened.station is not None and opened.station.station_id == "exb"
    assert opened.unlocked and opened.account is not None
    assert (opened.account.base, opened.account.changed) == (1, False)
    # Nothing lives only in TKL: version 1 is the owner's in Synk (TKLMOLN-05).
    assert in_synk(cloud, pretend) == [1]
    assert package_in_synk(cloud, pretend, 1).outside.name == "Exempelby"
    [listed] = stations_of(tkl).stations
    assert (listed.station_id, listed.name, listed.version) == ("exb", "Exempelby", 1)
    assert stations_of(tkl).open == "exb"
    # The same short name again is the station the account already has.
    again = tkl.post(TKL_API + "/konto/stationer", json={"name": "Exempelby", "station_id": "exb"})
    assert again.status_code == 409 and "Dina stationer" in again.json()["detail"]
    # The cloud has no PIN: the login opens TKL.
    assert tkl.post(TKL_API + "/unlock", json={"pin": "4711"}).status_code == 409
    assert tkl.post(TKL_API + "/pin", json={"old": "4711", "new": "1234"}).status_code == 409


def test_dina_stationer_lists_the_account_s_packages_and_not_others(
    made: Any, cloud: TestClient, pretend: PretendIdWithApi
) -> None:
    mine, theirs = browser(made), browser(made)
    me, someone = str(uuid.uuid4()), str(uuid.uuid4())
    log_in(mine, pretend, me)
    new_station(mine, "Exempelby", "exb")
    new_station(mine, "Västby", "vby")
    log_in(theirs, pretend, someone)
    new_station(theirs, "Östby", "oby")
    assert sorted(s.station_id for s in stations_of(theirs).stations) == ["oby"]
    pretend.subject = me
    assert sorted(s.station_id for s in stations_of(mine).stations) == ["exb", "vby"]
    # Someone else's station is never opened, nor its short name taken.
    taken = theirs.post(TKL_API + "/konto/stationer", json={"name": "X", "station_id": "exb"})
    assert taken.status_code == 409 and "någon annans" in taken.json()["detail"]
    assert theirs.post(TKL_API + "/konto/stationer/exb/oppna").status_code == 403
    # The hub lists only with TKL's token from ID, and only the person's own (SYNK-30).
    assert cloud.get("/api/sync/1/stations").status_code == 401
    assert cloud.get("/api/sync/1/relay/meets").status_code == 401
    pretend.subject = someone
    listed = cloud.get(
        "/api/sync/1/stations", headers={"Authorization": "Bearer " + pretend.token()}
    ).json()
    assert [s["station_id"] for s in listed["stations"]] == ["oby"]


def test_open_edit_and_save_gives_a_new_version(
    tkl: TestClient, cloud: TestClient, pretend: PretendIdWithApi
) -> None:
    """TKLMOLN-02: open one's station from Synk, change it, and Spara i molnet writes the next
    version. The model goes in the inside, and comes back when the station is opened again."""
    log_in(tkl, pretend)
    new_station(tkl)
    a_track_more(tkl)
    assert state_of(tkl).account.changed is True  # type: ignore[union-attr]
    # Ny version av utsidan in Studio is the working copy's own: still not saved in the cloud.
    assert tkl.post(TKL_API + "/studio/version").status_code == 200
    assert state_of(tkl).account.changed is True  # type: ignore[union-attr]
    assert save(tkl).version == 2
    assert state_of(tkl).account.changed is False  # type: ignore[union-attr]
    assert [t.label for t in package_in_synk(cloud, pretend, 2).outside.tracks][-1] == "Spår 3"
    # Level 1–2: a reference station as one's own, its model saved in the inside.
    reference = tkl.get(TKL_API + "/referens").json()[0]["id"]
    assert tkl.post(f"{TKL_API}/referens/{reference}/use").status_code == 200
    assert save(tkl).version == 3
    inside = package_in_synk(cloud, pretend, 3).inside
    assert inside["station_model"]["station_id"] == "exb"  # type: ignore[index]
    # Opened again, in a new browser: the latest version, outside and inside.
    other = browser(tkl.app)
    log_in(other, pretend)
    opened = open_station(other)
    assert opened.station is not None and opened.station.level >= 1
    assert opened.account is not None and (opened.account.base, opened.account.changed) == (
        3,
        False,
    )
    model = other.get(TKL_API + "/studio/model")
    assert model.status_code == 200 and model.json()["summary"]["station_id"] == "exb"


def test_a_save_on_an_old_version_gives_409_and_the_choice(
    made: Any, cloud: TestClient, pretend: PretendIdWithApi
) -> None:
    """TKLMOLN-09, H71: the same station open on two devices. The version rule protects it: the
    second save is refused, and the owner chooses Läs in den nya or Spara ändå ovanpå."""
    laptop, tablet = browser(made), browser(made)
    log_in(laptop, pretend)
    new_station(laptop)
    log_in(tablet, pretend)
    open_station(tablet)
    a_track_more(laptop, "Spår 3 från datorn")
    assert save(laptop).version == 2
    a_track_more(tablet, "Spår 3 från plattan")
    told = save(tablet)
    assert (told.version, told.behind) == (None, 2)
    assert "Läs in den nya" in (told.message or "") and "spara ändå ovanpå" in (told.message or "")
    assert in_synk(cloud, pretend) == [1, 2], "nothing was written over"
    assert state_of(tablet).account.changed is True, "the refused change is still not saved"  # type: ignore[union-attr]
    # Saving again without choosing is still refused: the choice is the owner's.
    assert save(tablet).behind == 2
    # Läs in den nya: the tablet gets version 2, and its own change is gone.
    read = open_station(tablet)
    assert read.account is not None and (read.account.base, read.account.changed) == (2, False)
    labels = [t["label"] for t in tablet.get(TKL_API + "/studio").json()["draft"]["tracks"]]
    assert labels[-1] == "Spår 3 från datorn"
    # Spara ändå ovanpå: the laptop's next change, on top of a newer one it chose to overwrite.
    a_track_more(tablet, "Spår 4 från plattan")
    assert save(tablet).version == 3
    a_track_more(laptop, "Spår 4 från datorn")
    behind = save(laptop)
    assert behind.behind == 3
    assert save(laptop, on_top=behind.behind).version == 4
    assert in_synk(cloud, pretend) == [1, 2, 3, 4]


def test_two_sessions_on_the_same_station_each_have_a_working_copy(
    made: Any, pretend: PretendIdWithApi
) -> None:
    """The working copy is the session's own: an edit on one device is not on the other until
    it is saved and read in there."""
    one, two = browser(made), browser(made)
    log_in(one, pretend)
    new_station(one)
    log_in(two, pretend)
    open_station(two)
    a_track_more(one)
    assert len(one.get(TKL_API + "/studio").json()["draft"]["tracks"]) == 3
    assert len(two.get(TKL_API + "/studio").json()["draft"]["tracks"]) == 2
    assert state_of(two).account.changed is False  # type: ignore[union-attr]
    # Lås locks this working copy; the login opens it again, never a PIN (TKLMOLN-10).
    locked = TklState.model_validate(two.post(TKL_API + "/lock").json())
    assert (locked.set_up, locked.unlocked, locked.locked) == (True, False, True)
    assert two.get(TKL_API + "/studio").status_code == 401
    assert two.post(TKL_API + "/konto/stationer/exb/oppna").status_code == 401
    log_in(two, pretend)
    assert state_of(two).unlocked is True
    assert one.get(TKL_API + "/studio").status_code == 200, "the other device was not locked"


def test_nothing_lives_only_in_tkls_store(
    made: Any, tmp_path: Path, cloud: TestClient, pretend: PretendIdWithApi
) -> None:
    """TKLMOLN-05, TKLMOLN-07: TKL's own file keeps the login, the sessions and the working
    copy as a cache. Throw it all away and the station is still the owner's, in Synk; logging
    out takes the working copy with it."""
    tkl = browser(made)
    log_in(tkl, pretend)
    new_station(tkl)
    a_track_more(tkl)
    assert save(tkl).version == 2
    # Logga ut: the working copy and the login go from TKL's store.
    out = TklIdState.model_validate(tkl.post(TKL_API + "/id/logout").json())
    assert (out.person, out.bound) == (None, True)
    with sqlite3.connect(tmp_path / "tkl" / "tkl.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM station").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM cloud_account").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM outside_version").fetchone() == (0,)
    # A new TKL, with an empty store: the station is there, as it was saved.
    fresh = create_tkl(
        tmp_path / "en-ny-tkl",
        mode=TklMode.CLOUD,
        over_internet=[CLOUD],
        http=lambda: internet(cloud, pretend),
        discover=lambda: [],
        id_settings=TklIdSettings(issuer=ISSUER, internal=INTERNAL, public_url=TKL, cloud=CLOUD),
    )
    elsewhere = browser(fresh)
    log_in(elsewhere, pretend)
    [listed] = stations_of(elsewhere).stations
    assert (listed.station_id, listed.version) == ("exb", 2)
    open_station(elsewhere)
    labels = [t["label"] for t in elsewhere.get(TKL_API + "/studio").json()["draft"]["tracks"]]
    assert labels == ["Spår 1", "Spår 2", "Spår 3"]


def test_another_person_in_the_same_browser_starts_over(
    tkl: TestClient, pretend: PretendIdWithApi
) -> None:
    log_in(tkl, pretend, str(uuid.uuid4()))
    new_station(tkl)
    log_in(tkl, pretend, str(uuid.uuid4()))
    after = state_of(tkl)
    assert (after.set_up, after.station) == (False, None), "never another person's copy"
    assert stations_of(tkl).stations == []


def test_local_tkl_is_unchanged(
    tmp_path: Path, cloud: TestClient, pretend: PretendIdWithApi
) -> None:
    """TKLMOLN-04: a local TKL keeps its own store, first start and PIN, and Spara i molnet as
    before, beside TKL in the cloud."""
    settings = TklIdSettings(issuer=ISSUER, internal=INTERNAL, public_url=TKL, cloud=CLOUD)
    local = browser(
        create_tkl(
            tmp_path / "lokal",
            mode=TklMode.LOCAL,
            http=lambda: internet(cloud, pretend),
            discover=lambda: [],
            id_settings=settings,
        )
    )
    shown = state_of(local)
    assert (shown.mode, shown.login, shown.account) == ("local", False, None)
    first = local.post(
        TKL_API + "/setup", json={"name": "Exempelby", "station_id": "exb", "pin": "4711"}
    )
    assert first.status_code == 201
    assert local.post(TKL_API + "/studio/version").status_code == 200
    assert local.get(TKL_API + "/konto/stationer").status_code == 404
    assert local.post(TKL_API + "/lock").status_code == 200
    assert local.post(TKL_API + "/unlock", json={"pin": "4711"}).status_code == 200
    sent = local.get(TKL_API + "/id/login")
    query = {k: v[0] for k, v in parse_qs(urlparse(sent.headers["location"]).query).items()}
    pretend.challenge, pretend.nonce = query["code_challenge"], query["nonce"]
    assert (
        local.get(
            TKL_API + "/id/callback", params={"code": "k", "state": query["state"]}
        ).status_code
        == 303
    )
    assert save(local).version == 1
    assert save(local).version == 2, "a local save goes on top of the one it knows"
    assert TklIdState.model_validate(local.get(TKL_API + "/id").json()).bound is False


def test_without_id_tkl_in_the_cloud_keeps_a_station_per_browser(tmp_path: Path) -> None:
    """The image's own check runs TKL in the cloud without TrainMeet ID: first start as before."""
    made = create_tkl(tmp_path, mode=TklMode.CLOUD, over_internet=["https://hub.invalid"])
    client = TestClient(made)
    assert state_of(client).login is False
    first = client.post(
        TKL_API + "/setup", json={"name": "Exempelby", "station_id": "exb", "pin": "4711"}
    )
    assert first.status_code == 201 and first.json()["unlocked"] is True


# --- Connecting through the cloud hub's relay (TKLMOLN-03, TKLMOLN-06) -----------------------


@pytest.fixture
def pi(tmp_path: Path, cloud: TestClient) -> Iterator[TestClient]:
    """A pretend Pi at the meet: linked to the cloud hub with a code, leading the meet (SYNK-14),
    and fetching the relay's calls on its own connection (SYNK-13)."""
    made = create_hub(
        BuildInfo(version="0.1.0"), preview_db=tmp_path / "pi" / "p.db", sync_call=wire(cloud)
    )
    client = TestClient(made)
    assert client.post("/api/hub/setup", json={"name": "Pi:n hemma", "pin": PIN}).status_code == 201
    assert link(client, cloud).status_code == 200
    assert client.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 201
    yield client


@dataclass
class Phone:
    """A phone on the meet's Pi, approved for every manned place: the neighbours' side."""

    pi: TestClient
    client_id: str
    headers: dict[str, str]

    def seen(self, place: str) -> station.Snapshot:
        answer = self.pi.get(f"/api/station/1/places/{place}", headers=self.headers)
        assert answer.status_code == 200, answer.text
        return station.Snapshot.model_validate(answer.json())

    def send(self, place: str, action: station.Action, **payload: Any) -> station.Reply:
        body = {
            "message_id": uuid4().hex,
            "client_id": self.client_id,
            "place": place,
            "context": self.seen(place).context.model_dump(mode="json"),
            "action": action.value,
            "payload": payload,
        }
        answer = self.pi.post("/api/station/1/commands", json=body, headers=self.headers)
        assert answer.status_code == 200, answer.text
        return station.Reply.model_validate(answer.json())


def phone_on(pi: TestClient, code: str) -> tuple[Phone, list[str]]:
    package = pi.get(DRIFT + "/package").json()
    manned = [p["id"] for p in package["places"] if p["kind"] == "manned"]
    body = {"kind": "tmbox_app", "name": "Telefonen", "software": "prov", "code": code}
    client_id = pi.post("/api/station/1/connect", json={**body, "wants": manned}).json()[
        "client_id"
    ]
    approved = pi.post(DRIFT + "/clients/approve", json={"client_id": client_id, "places": manned})
    assert approved.status_code == 200, approved.text
    key = pi.get(f"/api/station/1/connect/{client_id}").json()["key"]
    return Phone(pi, client_id, {"Authorization": "Bearer " + key}), manned


def a_train_to_clear(phone: Phone, manned: list[str]) -> tuple[str, station.CallHere, str]:
    """A train that may ask for clearance from one manned place to another, as the plan has it
    (the meet's own data, no names of real stations here): the place, the call, the section."""
    for place in manned:
        seen = phone.seen(place)
        for call in seen.calls:
            if station.Action.CLEARANCE_REQUEST in call.allowed_actions and call.to_place in manned:
                section = next(s.section for s in seen.sections if s.other_place == call.to_place)
                return place, call, section
    raise AssertionError("Planen har inget tåg som kan begära klarering.")


def tkl_sends(tkl: TestClient, place: str, action: station.Action, **payload: Any) -> station.Reply:
    view = tkl.get(f"{TKL_API}/places/{place}")
    assert view.status_code == 200, view.text
    assert view.json()["stale"] is False
    seen = station.Snapshot.model_validate(view.json()["snapshot"])
    body = {
        "message_id": uuid4().hex,
        "place": place,
        "context": seen.context.model_dump(mode="json"),
        "action": action.value,
        "payload": payload,
    }
    answer = tkl.post(TKL_API + "/commands", json=body)
    assert answer.status_code == 200, answer.text
    return station.Reply.model_validate(answer.json())


def test_tkl_in_the_cloud_clears_through_the_relay_to_the_pi_that_leads(
    tkl: TestClient, cloud: TestClient, pi: TestClient, pretend: PretendIdWithApi
) -> None:
    """TKLMOLN-03, TKLMOLN-06, TKLMOLN-16: the meet the account may join from ID's roles is led
    by a Pi; TKL in the cloud connects through the cloud hub's relay, on the connection the Pi
    already has open, and a clearance goes there and back."""
    log_in(tkl, pretend)
    new_station(tkl)
    hub = follower(pi).links.hub_id()
    # The Pi has not fetched its calls yet: the meet is not reachable now.
    [waiting, _] = TklMeets.model_validate(tkl.get(TKL_API + "/konto/traffar").json()).meets
    assert (waiting.name, waiting.way, waiting.address) == ("Värnamo Moduldagar", "none", None)
    with relaying(pi, cloud):
        meets = TklMeets.model_validate(tkl.get(TKL_API + "/konto/traffar").json())
        [ours, provbanan] = meets.meets
        assert (ours.meet, ours.club_name, ours.way, ours.hub_name) == (
            MEET,
            "Exempelby MJK",
            "relay",
            "Pi:n hemma",
        )
        assert ours.address == f"{CLOUD}/relay/{hub}", "the cloud hub's relay, never the Pi"
        assert (provbanan.name, provbanan.way, provbanan.address) == (
            "Provbanan",
            "preview",
            CLOUD,
        )
        code = pi.get(DRIFT + "/connect").json()["code"]
        connected = tkl.post(TKL_API + "/connection", json={"address": ours.address, "code": code})
        assert connected.status_code == 200, connected.text
        shown = TklConnection.model_validate(connected.json())
        assert (shown.status, shown.relayed, shown.preview) == ("waiting", True, False)
        assert shown.hub_name == "Träffens hubb genom Molnet"
        # The dispatcher approves TKL on the Pi, under Klienter, for a place with a train.
        phone, manned = phone_on(pi, code)
        place, call, section = a_train_to_clear(phone, manned)
        [mine] = [c for c in pi.get(DRIFT + "/clients").json() if c["kind"] == "tkl"]
        assert mine["name"] == "TKL Exempelby"
        approve = {"client_id": mine["client_id"], "places": [place]}
        assert pi.post(DRIFT + "/clients/approve", json=approve).status_code == 200
        approved = TklConnection.model_validate(tkl.get(TKL_API + "/connection").json())
        assert (approved.status, approved.places, approved.place) == ("approved", [place], place)
        # TKL asks for clearance through the relay; the neighbour gives it on the Pi; TKL sees
        # it through the relay, and the train leaves.
        asked = tkl_sends(
            tkl,
            place,
            station.Action.CLEARANCE_REQUEST,
            call=call.call,
            section=section,
            clearance_id="c-moln-1",
        )
        assert asked.status == station.ReplyStatus.ACCEPTED, asked.message
        neighbour = call.to_place
        assert neighbour is not None
        [request] = [c for c in phone.seen(neighbour).clearances if c.clearance_id == "c-moln-1"]
        assert request.status == station.ClearanceStatus.WAITING
        given = phone.send(
            neighbour,
            station.Action.CLEARANCE_RESPONSE,
            clearance_id="c-moln-1",
            approved=True,
        )
        assert given.status == station.ReplyStatus.ACCEPTED, given.message
        view = tkl.get(f"{TKL_API}/places/{place}").json()
        [cleared] = [c for c in view["snapshot"]["clearances"] if c["clearance_id"] == "c-moln-1"]
        assert cleared["status"] == "approved"
        left = tkl_sends(tkl, place, station.Action.TRAIN_DEPARTED, call=call.call)
        assert left.status == station.ReplyStatus.ACCEPTED, left.message
        assert call.train_number in [t.train_number for t in phone.seen(neighbour).on_the_way]
        # A preview run on the Pi, through the same relay (TKLMOLN-16): its own run, PROV.
        preview = started(pi)
        tried = tkl.post(TKL_API + "/connection", json={"address": ours.address, "code": preview})
        assert tried.status_code == 200, tried.text
        shown = TklConnection.model_validate(tried.json())
        assert (shown.relayed, shown.preview, shown.status) == (True, True, "waiting")


def test_a_meet_the_cloud_hub_runs_itself_is_joined_directly(
    tkl: TestClient, cloud: TestClient, pretend: PretendIdWithApi
) -> None:
    """The test hub runs meets directly: TKL connects to it as before, not through a relay."""
    assert cloud.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 201
    log_in(tkl, pretend)
    new_station(tkl)
    [ours, _] = TklMeets.model_validate(tkl.get(TKL_API + "/konto/traffar").json()).meets
    assert (ours.way, ours.hub_name, ours.address) == ("here", "Molnet", CLOUD)
    code = cloud.get(DRIFT + "/connect").json()["code"]
    connected = tkl.post(TKL_API + "/connection", json={"address": ours.address, "code": code})
    shown = TklConnection.model_validate(connected.json())
    assert (shown.status, shown.relayed, shown.preview, shown.hub_name) == (
        "waiting",
        False,
        False,
        "Molnet",
    )
    # Only the cloud hub and its relays: never another address, nor a relay elsewhere.
    for address in ("http://169.254.169.254", "http://169.254.169.254/relay/hub-1"):
        refused = tkl.post(TKL_API + "/connection", json={"address": address, "code": code})
        assert refused.status_code == 422


# --- A preview run is separate and marked PROV (TKLMOLN-11) -------------------------------------


def test_a_preview_run_in_the_cloud_is_apart_from_the_meet_and_marked(
    tkl: TestClient, cloud: TestClient, pretend: PretendIdWithApi
) -> None:
    """F17: Provbanan on the cloud hub with its code is a run of its own, never the meet, and
    TKL says it is a preview (PROV in the header and in Ställverket)."""
    assert cloud.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 201
    code = started(cloud)
    log_in(tkl, pretend)
    new_station(tkl)
    [_, provbanan] = TklMeets.model_validate(tkl.get(TKL_API + "/konto/traffar").json()).meets
    connected = tkl.post(TKL_API + "/connection", json={"address": provbanan.address, "code": code})
    shown = TklConnection.model_validate(connected.json())
    assert (shown.preview, shown.relayed) == (True, False)
    # The meet's own clients do not have it: the preview run is its own.
    names = [c["name"] for c in cloud.get(DRIFT + "/clients").json()]
    assert "TKL Exempelby" not in names
    previewing = [c["name"] for c in cloud.get("/api/provbanan/clients").json()["clients"]]
    assert "TKL Exempelby" in previewing
    # The meet's code joins the meet, not a preview.
    real = cloud.get(DRIFT + "/connect").json()["code"]
    again = tkl.post(TKL_API + "/connection", json={"address": provbanan.address, "code": real})
    assert TklConnection.model_validate(again.json()).preview is False


def test_a_remote_interlocking_in_the_cloud_is_opened_by_the_login(
    tkl: TestClient, pretend: PretendIdWithApi
) -> None:
    """Fjärrställverk (FR1, #36 del c) in TKL in the cloud: no PIN, the login locks and opens,
    and it gives way to a station opened from Dina stationer."""
    remote = {"name": "Fjärr Väster", "area": None, "places": ["vby", "exb"]}
    assert tkl.post(TKL_API + "/fjarr/setup", json=remote).status_code == 401
    log_in(tkl, pretend)
    made = tkl.post(TKL_API + "/fjarr/setup", json=remote)
    assert made.status_code == 201, made.text
    shown = TklState.model_validate(made.json())
    assert shown.unlocked and shown.remote is not None and shown.remote.name == "Fjärr Väster"
    assert tkl.post(TKL_API + "/id/save", json={}).status_code == 409, "no station package"
    opened = new_station(tkl)
    assert opened.remote is None and opened.station is not None
    assert opened.station.station_id == "exb"


@pytest.mark.parametrize(("konto", "login"), [(None, False), ("on", True)])
def test_the_account_bound_station_is_turned_on_with_tkl_konto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, konto: str | None, login: bool
) -> None:
    """TKL_KONTO turns on the station per account in the cloud (#88). Without it, a cloud TKL
    with ID keeps the station per browser, so that a test environment whose ID cannot be reached
    yet still lets everyone in, and Spara i molnet works as before."""
    from tkl.app import from_environment

    monkeypatch.setenv("TKL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TKL_MODE", "cloud")
    monkeypatch.setenv("TKL_HUBBAR", "http://hubb.invalid")
    monkeypatch.setenv("TKL_ID_ISSUER", "http://id.invalid/realms/trainmeet")
    if konto is None:
        monkeypatch.delenv("TKL_KONTO", raising=False)
    else:
        monkeypatch.setenv("TKL_KONTO", konto)
    with TestClient(from_environment()) as tkl:
        shown = TklState.model_validate(tkl.get("/api/tkl/1/state").json())
    assert shown.login is login
