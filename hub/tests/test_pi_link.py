"""Koppla Pi:n genom inloggning och val av träff (F16, SYNK-02, KONTO-22).

Two hubs in one process, as in hub/tests/test_synk.py: the Pi's calls go to the cloud's app. A
pretend ID answers the cloud's login and ID's API. The person on the Pi has the Pi's PIN; in the
cloud the person logs in with ID and chooses among the meets ID lets them plan.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts import planning, sync
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.pi_link import ATTEMPT_COOKIE
from hub.tests.test_id_login import PUBLIC
from hub.tests.test_id_roles import AUTUMN, PretendIdApi
from hub.tests.test_pi_ticket import SETTINGS
from hub.tests.test_planering import API, MEET, upload
from hub.tests.test_synk import SYNC, set_up, wire

PI = "http://pi.local"
CLOUD = "http://moln"
LINK = SYNC + "/link"


@pytest.fixture
def pretend() -> PretendIdApi:
    return PretendIdApi()


@pytest.fixture
def cloud(tmp_path: Path, pretend: PretendIdApi) -> TestClient:
    """The cloud hub, ID's client, with the meet linked to the meet in ID and published."""
    made = create_app(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "moln" / "p.db",
        id_settings=SETTINGS,
        id_http=httpx.Client(transport=httpx.MockTransport(pretend.handle)),
    )
    client = set_up(TestClient(made, base_url=PUBLIC, follow_redirects=False), "Molnet")
    meet = {"name": "Värnamo Moduldagar", "first_date": "2026-10-30", "id_meet": str(AUTUMN)}
    assert client.post(API + "/meets", json=meet).status_code == 201
    source = upload(client).json()["source"]["id"]
    assert client.post(f"{API}/meets/{MEET}/sources/{source}/apply").status_code == 200
    assert client.post(f"{API}/meets/{MEET}/versions").status_code == 201
    # The hub's own meet, not linked to ID: only the PIN plans it.
    assert client.post(API + "/meets", json={"name": "Hubbens egen"}).status_code == 201
    return client


@pytest.fixture
def pi(cloud: TestClient, tmp_path: Path) -> TestClient:
    """A new Pi, not linked, and its administrator logged in with the Pi's PIN."""
    made = create_app(
        BuildInfo(version="0.1.0"), preview_db=tmp_path / "pi" / "p.db", sync_call=wire(cloud)
    )
    return set_up(TestClient(made, base_url=PI, follow_redirects=False), "Pi:n i hallen")


def start(pi: TestClient) -> str:
    """Logga in och välj träff on the Pi: to the cloud, with the attempt. Its path there."""
    sent = pi.get("/api/hub/cloud/login", params={"address": CLOUD})
    assert sent.status_code == 303, sent.text
    to_cloud = urlparse(str(sent.headers["location"]))
    # The Pi reaches the cloud at its own address for it (as Låtsas-Pi reaches the test hub
    # inside the server); the browser goes to the address ID knows the cloud by.
    assert f"{to_cloud.scheme}://{to_cloud.netloc}" == PUBLIC
    assert to_cloud.path.startswith(LINK + "/attempts/") and to_cloud.path.endswith("/open")
    assert pi.cookies.get(ATTEMPT_COOKIE, path="/api/hub/cloud")
    return to_cloud.path


def log_in_in_the_cloud(cloud: TestClient, opened: str, pretend: PretendIdApi) -> TestClient:
    """The browser in the cloud: the attempt in a cookie, the login with ID, and the page."""
    browser = TestClient(cloud.app, base_url=PUBLIC, follow_redirects=False)
    to_login = browser.get(opened)
    assert to_login.status_code == 303
    assert to_login.headers["location"] == "/api/hub/id/login?next=%2Fplanering%3Fkoppla%3Dpi"
    at_id = browser.get(to_login.headers["location"])
    assert at_id.status_code == 303
    query = {k: v[0] for k, v in parse_qs(urlparse(at_id.headers["location"]).query).items()}
    pretend.nonce = query["nonce"]
    back = browser.get("/api/hub/id/callback", params={"code": "k", "state": query["state"]})
    assert (back.status_code, back.headers["location"]) == (303, "/planering?koppla=pi")
    return browser


def test_the_pi_is_linked_by_logging_in_and_choosing_the_meet(
    pi: TestClient, cloud: TestClient, pretend: PretendIdApi
) -> None:
    pretend.roles = {str(AUTUMN): ["organizer"]}
    browser = log_in_in_the_cloud(cloud, start(pi), pretend)

    shown = sync.LinkAttempt.model_validate(browser.get(LINK + "/attempt").json())
    assert (shown.hub_name, shown.address, shown.chosen) == ("Pi:n i hallen", PI, None)
    assert [(m.meet, m.name) for m in shown.meets] == [(MEET, "Värnamo Moduldagar")], (
        "only the meets ID lets them plan, not the hub's own"
    )
    refused = browser.post(LINK + "/attempt", json={"meet": "hubbens-egen"})
    assert refused.status_code == 403, refused.text

    chosen = browser.post(LINK + "/attempt", json={"meet": MEET})
    assert chosen.status_code == 200, chosen.text
    to_pi = urlparse(sync.LinkChosen.model_validate(chosen.json()).back)
    assert (f"{to_pi.scheme}://{to_pi.netloc}", to_pi.path) == (PI, "/api/hub/cloud/linked")

    # Back on the Pi, in the browser that started: the Pi fetches its key and follows the meet.
    done = pi.get(to_pi.path + "?" + to_pi.query)
    assert (done.status_code, done.headers["location"]) == (
        303,
        "/installningar?molnet=kopplad#molnet",
    )
    [seen] = [sync.CloudLink.model_validate(c) for c in pi.get("/api/hub/cloud").json()]
    assert (seen.meet, seen.meet_name, seen.cloud_name, seen.versions) == (
        MEET,
        "Värnamo Moduldagar",
        "Molnet",
        1,
    )
    [summary] = [planning.MeetSummary.model_validate(m) for m in pi.get(API + "/meets").json()]
    assert summary.meet.id == MEET and summary.home == "Molnet"
    [follower] = [
        sync.Follower.model_validate(f) for f in cloud.get(f"{SYNC}/meets/{MEET}/followers").json()
    ]
    assert follower.hub_name == "Pi:n i hallen"

    # The attempt is used once: back again, the Pi says to start over.
    again = pi.get(to_pi.path + "?" + to_pi.query)
    assert again.headers["location"] == "/installningar?molnet=gick-ut#molnet"
    assert browser.get(LINK + "/attempt").status_code == 410


def test_without_a_role_to_plan_there_is_nothing_to_choose(
    pi: TestClient, cloud: TestClient, pretend: PretendIdApi
) -> None:
    pretend.roles = {str(AUTUMN): ["dispatcher"]}
    browser = log_in_in_the_cloud(cloud, start(pi), pretend)
    shown = sync.LinkAttempt.model_validate(browser.get(LINK + "/attempt").json())
    assert shown.meets == []
    assert browser.post(LINK + "/attempt", json={"meet": MEET}).status_code == 403


def test_the_cloud_holds_the_key_until_a_meet_is_chosen_and_only_for_the_pi(
    pi: TestClient, cloud: TestClient, pretend: PretendIdApi
) -> None:
    pretend.roles = {str(AUTUMN): ["admin"]}
    opened = start(pi)
    attempt = opened.split("/")[-2]
    back = f"/api/hub/cloud/linked?attempt={attempt}"
    # Back without a meet: the Pi says so, and the attempt is over.
    early = pi.get(back)
    assert early.headers["location"] == "/installningar?molnet=ingen-traff#molnet"

    opened = start(pi)
    attempt = opened.split("/")[-2]
    browser = log_in_in_the_cloud(cloud, opened, pretend)
    assert browser.post(LINK + "/attempt", json={"meet": MEET}).status_code == 200
    # Someone with the attempt and not the Pi's secret gets no key.
    stolen = cloud.post(f"{LINK}/attempts/{attempt}/redeem", json={"secret": "x" * 43})
    assert stolen.status_code == 403
    # Another browser on the Pi, without the attempt's cookie, links nothing.
    other = TestClient(pi.app, base_url=PI, follow_redirects=False)
    refused = other.get(f"/api/hub/cloud/linked?attempt={attempt}")
    assert refused.headers["location"] == "/installningar?molnet=gick-ut#molnet"
    # The browser that started does.
    done = pi.get(f"/api/hub/cloud/linked?attempt={attempt}")
    assert done.headers["location"] == "/installningar?molnet=kopplad#molnet"


def test_only_the_pis_administrator_starts_and_the_way_back_is_the_pis(
    pi: TestClient, cloud: TestClient
) -> None:
    stranger = TestClient(pi.app, base_url=PI, follow_redirects=False)
    sent = stranger.get("/api/hub/cloud/login", params={"address": CLOUD})
    assert sent.headers["location"] == "/installningar?molnet=pin#molnet"
    wrong = pi.get("/api/hub/cloud/login", params={"address": "http://moln.example.com"})
    assert wrong.headers["location"] == "/installningar?molnet=adress#molnet"

    hello = {"hub_id": "hub-abc", "hub_name": "Någon", "software": "0.1.0"}
    for back in (
        "https://elsewhere.example/planering",
        "http://pi.local/api/hub/cloud/linked?attempt=x",
        "javascript:alert(1)",
    ):
        asked = cloud.post(LINK + "/attempts", json={"hello": hello, "back": back})
        assert asked.status_code == 422, back


def test_a_cloud_without_it_says_to_use_the_code(pi: TestClient, cloud: TestClient) -> None:
    def old_cloud(
        method: str, url: str, headers: object, body: object, timeout: float
    ) -> tuple[int, bytes]:
        return 404, b'{"detail": "Not Found"}'

    pi.app.state.follower.call = old_cloud  # type: ignore[attr-defined]
    sent = pi.get("/api/hub/cloud/login", params={"address": CLOUD})
    assert sent.headers["location"] == "/installningar?molnet=gammal#molnet"


def test_someone_who_plans_the_meet_with_id_gives_the_code_too(
    cloud: TestClient, pretend: PretendIdApi
) -> None:
    """The code is the reserve (F16): Arrangör in ID asks for it, as the PIN does."""
    browser = TestClient(cloud.app, base_url=PUBLIC, follow_redirects=False)
    at_id = browser.get("/api/hub/id/login", params={"next": "/planering"})
    query = {k: v[0] for k, v in parse_qs(urlparse(at_id.headers["location"]).query).items()}
    pretend.nonce = query["nonce"]
    assert (
        browser.get(
            "/api/hub/id/callback", params={"code": "k", "state": query["state"]}
        ).status_code
        == 303
    )
    pretend.roles = {str(AUTUMN): ["dispatcher"]}
    assert browser.post(f"{SYNC}/meets/{MEET}/code").status_code == 403
    pretend.roles = {str(AUTUMN): ["organizer"]}
    given = browser.post(f"{SYNC}/meets/{MEET}/code")
    assert given.status_code == 201, given.text
    assert browser.post(f"{SYNC}/meets/hubbens-egen/code").status_code == 403


def test_a_cloud_without_id_is_opened_at_the_address_the_pi_was_given(
    cloud: TestClient, tmp_path: Path
) -> None:
    """A cloud with only its PIN: the browser goes where the Pi goes, and the PIN chooses."""
    plain = set_up(
        TestClient(
            create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "enkel" / "p.db"),
            base_url=CLOUD,
            follow_redirects=False,
        ),
        "Molnet",
    )
    assert plain.post(API + "/meets", json={"name": "Värnamo Moduldagar"}).status_code == 201
    made = create_app(
        BuildInfo(version="0.1.0"), preview_db=tmp_path / "pi2" / "p.db", sync_call=wire(plain)
    )
    pi = set_up(TestClient(made, base_url=PI, follow_redirects=False), "Pi:n")
    sent = pi.get("/api/hub/cloud/login", params={"address": CLOUD})
    opened = urlparse(str(sent.headers["location"]))
    assert f"{opened.scheme}://{opened.netloc}" == CLOUD
    at_page = plain.get(opened.path)
    assert at_page.headers["location"] == "/planering?koppla=pi", "no ID here: straight to the page"
    shown = sync.LinkAttempt.model_validate(plain.get(LINK + "/attempt").json())
    assert [m.meet for m in shown.meets] == [MEET]
    back = urlparse(plain.post(LINK + "/attempt", json={"meet": MEET}).json()["back"])
    done = pi.get(back.path + "?" + back.query)
    assert done.headers["location"] == "/installningar?molnet=kopplad#molnet"
