"""Synk, steg 5 del 2 (SYNK-02, SYNK-10, SYNK-13): a Pi is linked to a meet in the cloud with a
six-digit code and follows its versions. Two hubs run here in one process: the Pi's calls go
to the cloud's app, as they would over the internet."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts import drift, planning, sync
from hub.app import create_app
from hub.build_info import BuildInfo
from hub.tests.test_forarna import PDF
from hub.tests.test_planering import API, DRIFT, MEET, PIN, upload
from synk.follower import Call, Follower, check_address
from synk.link import LinkError

SYNC = "/api/sync/1"


def wire(cloud: TestClient, spoil: bool = False) -> Call:
    """The internet between the Pi and the cloud: the cloud's own app, without its login."""
    other = TestClient(cloud.app)

    def call(
        method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        path = url.split("://", 1)[1]
        response = other.request(
            method, path[path.index("/") :], headers=dict(headers), content=body
        )
        data = response.content
        if spoil and "/versions/" in path:
            data = data.replace(b'"101"', b'"102"', 1)
        return response.status_code, data

    return call


def set_up(client: TestClient, name: str) -> TestClient:
    assert client.post("/api/hub/setup", json={"name": name, "pin": PIN}).status_code == 201
    return client


@pytest.fixture
def cloud(tmp_path: Path) -> TestClient:
    client = set_up(
        TestClient(create_app(BuildInfo(version="0.1.0"), preview_db=tmp_path / "moln" / "p.db")),
        "Molnet",
    )
    created = client.post(
        API + "/meets",
        json={"name": "Värnamo Moduldagar", "first_date": "2026-10-30", "last_date": "2026-11-01"},
    )
    assert created.status_code == 201
    source = upload(client).json()["source"]["id"]
    assert client.post(f"{API}/meets/{MEET}/sources/{source}/apply").status_code == 200
    assert client.post(f"{API}/meets/{MEET}/versions").status_code == 201
    return client


def pi_for(cloud: TestClient, tmp_path: Path, spoil: bool = False) -> TestClient:
    app = create_app(
        BuildInfo(version="0.1.0"),
        preview_db=tmp_path / "pi" / "p.db",
        sync_call=wire(cloud, spoil),
    )
    return set_up(TestClient(app), "Pi:n hemma")


def code(cloud: TestClient) -> str:
    given = cloud.post(f"{SYNC}/meets/{MEET}/code")
    assert given.status_code == 201, given.text
    return sync.LinkCode.model_validate(given.json()).code


def link(pi: TestClient, cloud: TestClient) -> Any:
    return pi.post("/api/hub/cloud", json={"address": "http://moln", "code": code(cloud)})


def follower(pi: TestClient) -> Follower:
    found: Follower = pi.app.state.follower  # type: ignore[attr-defined]
    return found


def follow(pi: TestClient) -> bool:
    [reach] = follower(pi).links.reaches()
    return follower(pi).follow(reach, wait=0)


def test_a_pi_linked_with_a_code_follows_the_meets_versions(
    cloud: TestClient, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    pi = pi_for(cloud, tmp_path)
    linked = link(pi, cloud)
    assert linked.status_code == 200, linked.text
    [seen] = [sync.CloudLink.model_validate(c) for c in linked.json()]
    assert (seen.meet, seen.meet_name, seen.cloud_name, seen.versions) == (
        MEET,
        "Värnamo Moduldagar",
        "Molnet",
        1,
    )
    assert seen.problem is None and seen.heard is not None
    # The version is the same, byte for byte: the checksum says so (SYNK-10).
    up = planning.Version.model_validate(cloud.get(f"{API}/meets/{MEET}/versions").json()[0])
    down = planning.Version.model_validate(pi.get(f"{API}/meets/{MEET}/versions").json()[0])
    assert down.checksum == up.checksum and down.number == 1
    # The meet is in the Pi's list, planned in the cloud, and the Pi runs it.
    [summary] = [planning.MeetSummary.model_validate(m) for m in pi.get(API + "/meets").json()]
    assert (summary.meet.id, summary.home, [v.number for v in summary.versions]) == (
        MEET,
        "Molnet",
        [1],
    )
    started = pi.post(DRIFT + "/start", json={"meet": MEET, "version": 1})
    assert started.status_code == 201, started.text
    now = drift.Now.model_validate(pi.get(DRIFT + "/now").json())
    assert (now.meet_id, now.name, now.version) == (MEET, "Värnamo Moduldagar", 1)
    # The key never shows: not in the Pi's answer, not in a log.
    [reach] = follower(pi).links.reaches()
    assert reach.key not in linked.text and reach.key not in caplog.text
    assert reach.key not in pi.get("/api/hub/cloud").text


def test_a_new_version_and_a_withdrawal_follow(cloud: TestClient, tmp_path: Path) -> None:
    pi = pi_for(cloud, tmp_path)
    assert link(pi, cloud).status_code == 200
    assert not follow(pi), "nothing new"
    draft = planning.Draft.model_validate(cloud.get(f"{API}/meets/{MEET}").json())
    assert draft.package is not None
    place = draft.package.places[0].id
    changed = cloud.post(
        f"{API}/meets/{MEET}/changes",
        json={
            "revision": draft.revision,
            "changes": [{"kind": "place", "place": place, "phone": "777"}],
        },
    )
    assert changed.status_code == 200, changed.text
    assert cloud.post(f"{API}/meets/{MEET}/versions").status_code == 201
    assert follow(pi)
    assert [v["number"] for v in pi.get(f"{API}/meets/{MEET}/versions").json()] == [1, 2]
    assert cloud.post(f"{API}/meets/{MEET}/versions/1/withdraw").status_code == 200
    assert follow(pi)
    [first, _] = pi.get(f"{API}/meets/{MEET}/versions").json()
    assert first["withdrawn"] is not None
    assert pi.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 409


def test_a_code_works_once_and_wrong_codes_make_the_cloud_wait(
    cloud: TestClient, tmp_path: Path
) -> None:
    pi = pi_for(cloud, tmp_path)
    given = code(cloud)
    assert (
        pi.post("/api/hub/cloud", json={"address": "http://moln", "code": given}).status_code == 200
    )
    again = pi.post("/api/hub/cloud", json={"address": "http://moln", "code": given})
    assert again.status_code == 403 and "gäller inte" in again.json()["detail"]
    hello = {"hub_id": "hub-annan", "hub_name": "En annan", "software": "0.1.0"}
    for _ in range(9):
        wrong = cloud.post(f"{SYNC}/link", json={"code": "000000", "hello": hello})
        assert wrong.status_code == 403
    assert cloud.post(f"{SYNC}/link", json={"code": "000000", "hello": hello}).status_code == 429
    # Codes can only be given by the administrator.
    assert TestClient(cloud.app).post(f"{SYNC}/meets/{MEET}/code").status_code == 401


def test_a_revoked_pi_is_told_to_link_again(cloud: TestClient, tmp_path: Path) -> None:
    pi = pi_for(cloud, tmp_path)
    assert link(pi, cloud).status_code == 200
    [shown] = [
        sync.Follower.model_validate(f) for f in cloud.get(f"{SYNC}/meets/{MEET}/followers").json()
    ]
    assert shown.hub_name == "Pi:n hemma"
    assert cloud.post(f"{SYNC}/meets/{MEET}/followers/{shown.hub_id}/revoke").status_code == 204
    assert not follow(pi)
    [seen] = pi.get("/api/hub/cloud").json()
    assert "Koppla om" in seen["problem"]
    # The Pi lets go of the meet; the versions it has stay, frozen.
    assert pi.post(f"/api/hub/cloud/{MEET}/disconnect").json() == []
    assert [v["number"] for v in pi.get(f"{API}/meets/{MEET}/versions").json()] == [1]


def test_a_version_that_does_not_come_whole_is_not_kept(cloud: TestClient, tmp_path: Path) -> None:
    pi = pi_for(cloud, tmp_path, spoil=True)
    assert link(pi, cloud).status_code == 200
    [seen] = pi.get("/api/hub/cloud").json()
    assert "kom inte hel" in seen["problem"] and seen["versions"] == 0


def _in_use(read: Callable[[], object], stop: Event) -> None:
    """A thread that uses Planering's file while the hub runs, as Synk's do: the push loop asks
    for the links every second (Follower.push and pull), and the versions are read. Here without
    a pause, so that the file is nearly always in use."""
    while not stop.is_set():
        read()


def test_the_pi_links_while_synk_uses_the_shared_file(cloud: TestClient, tmp_path: Path) -> None:
    """Planering's file is shared with Synk's stores (SYNK-20), and Synk's threads use it while the
    Pi links. The link once answered 500 now and then ("database is locked"): Planering was first
    used in it, for the version's attachment, and only then turned the file to write-ahead
    logging, which SQLite refuses at once while another connection writes. Now every store's
    file is ready before any thread runs. Three Pis link, each while its file is in use."""
    sent = cloud.post(f"{API}/meets/{MEET}/instructions.pdf?name=Allmänt.pdf", content=PDF)
    assert sent.status_code == 200, sent.text
    assert cloud.post(f"{API}/meets/{MEET}/versions").status_code == 201
    for n in range(3):
        app = create_app(
            BuildInfo(version="0.1.0"),
            preview_db=tmp_path / f"pi-{n}" / "p.db",
            sync_call=wire(cloud),
        )
        pi = set_up(TestClient(app), f"Pi:n {n}")
        stop = Event()
        users = [
            Thread(target=_in_use, args=(read, stop))
            for read in (follower(pi).links.reaches, follower(pi).versions.meets)
        ]
        for user in users:
            user.start()
        try:
            linked = link(pi, cloud)
        finally:
            stop.set()
            for user in users:
                user.join()
        assert linked.status_code == 200, linked.text
        [seen] = [sync.CloudLink.model_validate(c) for c in linked.json()]
        assert (seen.versions, seen.problem) == (2, None)
        [pdf] = pi.get(f"{API}/meets/{MEET}/versions/2").json()["attachments"]
        kept = pi.get(f"{API}/meets/{MEET}/versions/2/attachments/{pdf['id']}")
        assert (kept.status_code, kept.content) == (200, PDF)


def test_the_protocol_is_said_and_a_newer_one_refused(cloud: TestClient) -> None:
    hello = {
        "hub_id": "hub-ny",
        "hub_name": "Ny",
        "software": "9.0.0",
        "protocols": ["trainmeet.sync/2"],
    }
    refused = cloud.post(f"{SYNC}/link", json={"code": code(cloud), "hello": hello})
    assert refused.status_code == 426 and "trainmeet.sync/1" in refused.json()["detail"]
    other = cloud.get(
        f"{SYNC}/meets/{MEET}/versions",
        headers={"Authorization": "Bearer " + "x" * 40, sync.HEADER: "trainmeet.sync/2"},
    )
    assert other.status_code == 426
    assert cloud.get(f"{SYNC}/meets/{MEET}/versions").status_code == 401


def test_the_cloud_holds_the_question_until_something_changes(
    cloud: TestClient, tmp_path: Path
) -> None:
    """Long-poll: with the mark it has, the Pi waits; a version published answers at once."""
    pi = pi_for(cloud, tmp_path)
    assert link(pi, cloud).status_code == 200
    [reach] = follower(pi).links.reaches()
    headers = {"Authorization": f"Bearer {reach.key}", sync.HEADER: sync.PROTOCOL}
    first = sync.VersionList.model_validate(
        cloud.get(f"{SYNC}/meets/{MEET}/versions", headers=headers).json()
    )
    began = time.monotonic()
    same = cloud.get(
        f"{SYNC}/meets/{MEET}/versions", params={"known": first.mark, "wait": 1}, headers=headers
    )
    assert time.monotonic() - began >= 0.9 and same.json()["mark"] == first.mark


def test_the_address_is_https_except_nearby() -> None:
    assert check_address("https://test.hub.trainmeet.app/") == "https://test.hub.trainmeet.app"
    assert check_address("http://hub:8080") == "http://hub:8080"
    assert check_address("http://192.168.1.20") == "http://192.168.1.20"
    with pytest.raises(LinkError, match="https"):
        check_address("http://test.hub.trainmeet.app")
    with pytest.raises(LinkError, match="adress"):
        check_address("ftp://moln")


def started(pi: TestClient, cloud: TestClient) -> TestClient:
    """The Pi linked, running the meet: it leads (SYNK-14)."""
    assert link(pi, cloud).status_code == 200
    assert pi.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 201
    return pi


def count(client: TestClient) -> int:
    running = client.app.state.running  # type: ignore[attr-defined]
    store = running.mirror(MEET, 1)
    return len(store.events_after(store.current(), 0))


def test_the_cloud_follows_the_pis_run_live(cloud: TestClient, tmp_path: Path) -> None:
    """Under träffen (SYNK-04, SYNK-14, DRIFT-12): the Pi leads and sends its drift events; the
    cloud keeps them as they came, shows the same Nu, decides nothing and never ticks."""
    pi = started(pi_for(cloud, tmp_path), cloud)
    assert pi.post(DRIFT + "/clock", json={"action": "jump", "time": "08:00"}).status_code == 200
    ack = follower(pi).push()
    assert ack == count(pi) > 1
    # Byt träff in the cloud follows the run the Pi leads; it starts no run of its own.
    assert cloud.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 201
    up = drift.Now.model_validate(cloud.get(DRIFT + "/now").json())
    down = drift.Now.model_validate(pi.get(DRIFT + "/now").json())
    assert (up.clock.time, up.legs, up.version) == (down.clock.time, down.legs, down.version)
    assert up.leader is not None and up.leader.hub_name == "Pi:n hemma" and down.leader is None
    refused = cloud.post(DRIFT + "/clock", json={"action": "start"})
    assert refused.status_code == 409 and "leder träffen" in refused.json()["detail"]
    from hub.app import tick_once

    tick_once(cloud.app.state.running)  # type: ignore[attr-defined]
    assert count(cloud) == ack, "the cloud's automation writes nothing into the Pi's run"


def test_a_driftandring_on_the_pi_is_a_proposal_in_the_cloud(
    cloud: TestClient, tmp_path: Path
) -> None:
    """4.4 over Synk: the change goes up as a proposal, and Ta med comes back down."""
    pi = started(pi_for(cloud, tmp_path), cloud)
    package = pi.get(DRIFT + "/package").json()
    train = package["trains"][0]["id"]
    made = pi.post(DRIFT + "/changes", json={"change": {"kind": "cancel", "train": train}})
    assert made.status_code == 200, made.text
    follower(pi).push()
    [proposal] = cloud.get(f"{API}/meets/{MEET}/proposals").json()
    assert proposal["status"] == "waiting"
    assert cloud.post(f"{API}/meets/{MEET}/proposals/{proposal['id']}/take").status_code == 200
    follower(pi).push()
    [change] = drift.Now.model_validate(pi.get(DRIFT + "/now").json()).changes
    assert change.proposal == drift.ProposalStatus.TAKEN


def test_after_a_break_the_pi_goes_on_from_the_clouds_acknowledgement(
    cloud: TestClient, tmp_path: Path
) -> None:
    """A Pi that starts again knows nothing of what the cloud has: it asks, and sends the rest,
    with no gap and nothing twice."""
    pi = started(pi_for(cloud, tmp_path), cloud)
    follower(pi).push()
    for time_of_day in ("07:00", "08:00", "09:00"):
        assert (
            pi.post(DRIFT + "/clock", json={"action": "jump", "time": time_of_day}).status_code
            == 200
        )
    again = Follower(
        follower(pi).links,
        follower(pi).versions,
        follower(pi).hello,
        follower(pi).call,
        runs=follower(pi).runs,
    )
    assert again.push() == count(pi) == count(cloud)
    mirror = cloud.app.state.running.mirror(MEET, 1)  # type: ignore[attr-defined]
    up = [e.seq for e in mirror.events_after(mirror.current(), 0)]
    assert up == list(range(1, len(up) + 1))


def test_the_meets_home_moves_to_the_pi_and_back(cloud: TestClient, tmp_path: Path) -> None:
    """Träffens hem (H35, SYNK-03, SYNK-16): the Pi takes the home with one button and the
    cloud only looks; the Pi publishes and the cloud follows; after the meet the home goes back
    with what was changed, and the Pi follows again. Never two version 2."""
    pi = pi_for(cloud, tmp_path)
    assert link(pi, cloud).status_code == 200
    taken = pi.post(f"/api/hub/cloud/{MEET}/take")
    assert taken.status_code == 200, taken.text
    [seen] = taken.json()
    assert seen["home_here"] is True
    # The draft came along, and the cloud only looks now.
    down = planning.Draft.model_validate(pi.get(f"{API}/meets/{MEET}").json())
    up = planning.Draft.model_validate(cloud.get(f"{API}/meets/{MEET}").json())
    assert down.package == up.package and down.sources == up.sources
    refused = cloud.post(f"{API}/meets/{MEET}/versions")
    assert refused.status_code == 409 and "Träffens hem är Pi:n hemma" in refused.json()["detail"]
    home = sync.Home.model_validate(cloud.get(f"{SYNC}/meets/{MEET}/home").json())
    assert (home.hub_name, home.here, home.generation) == ("Pi:n hemma", False, 1)
    assert cloud.post(f"{SYNC}/meets/{MEET}/code").status_code == 409, "codes only at the home"
    # The Pi changes and publishes version 2; the cloud follows it, byte for byte.
    place = down.package.places[0].id if down.package else ""
    changed = pi.post(
        f"{API}/meets/{MEET}/changes",
        json={
            "revision": down.revision,
            "changes": [{"kind": "place", "place": place, "phone": "555"}],
        },
    )
    assert changed.status_code == 200, changed.text
    assert pi.post(f"{API}/meets/{MEET}/versions").status_code == 201
    follow(pi)
    up_versions = cloud.get(f"{API}/meets/{MEET}/versions").json()
    down_versions = pi.get(f"{API}/meets/{MEET}/versions").json()
    assert [v["checksum"] for v in up_versions] == [v["checksum"] for v in down_versions]
    assert len(up_versions) == 2
    # Lämna tillbaka: the cloud has what the Pi changed, and is the home again.
    back = pi.post(f"/api/hub/cloud/{MEET}/back")
    assert back.status_code == 200, back.text
    assert back.json()[0]["home_here"] is False
    after = planning.Draft.model_validate(cloud.get(f"{API}/meets/{MEET}").json())
    assert after.package is not None
    assert next(p.phone for p in after.package.places if p.id == place) == "555"
    assert pi.post(f"{API}/meets/{MEET}/versions").status_code == 409, "the Pi only looks now"
    [summary] = [s for s in pi.get(API + "/meets").json() if s["meet"]["id"] == MEET]
    assert summary["home"] == "Molnet"
    changed = cloud.post(
        f"{API}/meets/{MEET}/changes",
        json={
            "revision": after.revision,
            "changes": [{"kind": "place", "place": place, "phone": "556"}],
        },
    )
    assert changed.status_code == 200
    assert cloud.post(f"{API}/meets/{MEET}/versions").status_code == 201
    follow(pi)
    assert [v["number"] for v in pi.get(f"{API}/meets/{MEET}/versions").json()] == [1, 2, 3]


def test_the_cloud_takes_the_home_back_from_a_silent_pi(cloud: TestClient, tmp_path: Path) -> None:
    """Ta tillbaka hem hit: when the Pi with the home is gone, the cloud takes it back with a
    new generation; what the Pi sends from the old one is refused, and it learns the new home."""
    pi = pi_for(cloud, tmp_path)
    assert link(pi, cloud).status_code == 200
    assert pi.post(f"/api/hub/cloud/{MEET}/take").status_code == 200
    taken = cloud.post(f"{SYNC}/meets/{MEET}/home/reclaim")
    assert taken.status_code == 200 and taken.json()["here"] is True
    assert taken.json()["generation"] == 2
    assert pi.post(f"/api/hub/cloud/{MEET}/back").status_code == 409
    follow(pi)
    [seen] = pi.get("/api/hub/cloud").json()
    assert seen["home_here"] is False
    assert pi.post(f"{API}/meets/{MEET}/versions").status_code == 409
    assert cloud.post(f"{API}/meets/{MEET}/versions").status_code in (201, 409)


def test_while_the_pi_is_home_its_driftandringar_are_proposals_there(
    cloud: TestClient, tmp_path: Path
) -> None:
    """4.4 at the meet's home: the Pi's own Planering gets the proposal, the cloud's does not."""
    pi = pi_for(cloud, tmp_path)
    assert link(pi, cloud).status_code == 200
    assert pi.post(f"/api/hub/cloud/{MEET}/take").status_code == 200
    assert pi.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 201
    train = pi.get(DRIFT + "/package").json()["trains"][0]["id"]
    assert (
        pi.post(DRIFT + "/changes", json={"change": {"kind": "cancel", "train": train}}).status_code
        == 200
    )
    follower(pi).push()
    assert [p["status"] for p in pi.get(f"{API}/meets/{MEET}/proposals").json()] == ["waiting"]
    assert cloud.get(f"{API}/meets/{MEET}/proposals").json() == []


def test_ta_over_i_molnet_and_the_pi_follows_when_it_comes_back(
    cloud: TestClient, tmp_path: Path
) -> None:
    """Ta över i molnet (TRAFIK-08, H8, H9, SYNK-14): only by hand, with the meet's name; the
    cloud leads with a higher epoch and the clock stopped. The Pi that comes back follows, and
    what it did meanwhile is set aside, never applied."""
    pi = started(pi_for(cloud, tmp_path), cloud)
    assert pi.post(DRIFT + "/clock", json={"action": "jump", "time": "08:00"}).status_code == 200
    follower(pi).push()
    assert cloud.post(DRIFT + "/start", json={"meet": MEET, "version": 1}).status_code == 201
    wrong = cloud.post(DRIFT + "/takeover", json={"confirm": "Fel träff"})
    assert wrong.status_code == 422 and "Värnamo Moduldagar" in wrong.json()["detail"]
    taken = drift.DriftEvent.model_validate(
        cloud.post(DRIFT + "/takeover", json={"confirm": "värnamo moduldagar"}).json()
    )
    assert (taken.kind, taken.epoch, taken.data["hub_name"]) == ("leader.taken", 1, "Molnet")
    led = drift.Now.model_validate(cloud.get(DRIFT + "/now").json())
    assert led.leader is None and not led.clock.running and led.clock.time == "08:00"
    assert (
        cloud.post(DRIFT + "/takeover", json={"confirm": "Värnamo Moduldagar"}).status_code == 409
    )
    # The Pi was cut off and went on deciding; when it calls again, the cloud has taken over.
    assert pi.post(DRIFT + "/clock", json={"action": "jump", "time": "09:00"}).status_code == 200
    follower(pi).push()
    after = drift.Now.model_validate(pi.get(DRIFT + "/now").json())
    assert after.leader is not None and after.leader.hub_name == "Molnet"
    assert after.clock.time == "08:00", "the cloud's word, not the Pi's own"
    refused = pi.post(DRIFT + "/clock", json={"action": "start"})
    assert refused.status_code == 409 and "leder träffen" in refused.json()["detail"]
    store = pi.app.state.running.store  # type: ignore[attr-defined]
    assert store.set_aside(store.current()) >= 1
    [seen] = pi.get("/api/hub/cloud").json()
    assert "Molnet tog över träffen." in seen["problem"]
    # From here the Pi follows the cloud.
    assert cloud.post(DRIFT + "/clock", json={"action": "jump", "time": "10:00"}).status_code == 200
    follower(pi).pull()
    up = drift.Now.model_validate(cloud.get(DRIFT + "/now").json())
    down = drift.Now.model_validate(pi.get(DRIFT + "/now").json())
    assert (down.clock.time, down.legs) == (up.clock.time, up.legs) and up.clock.time == "10:00"
    last = cloud.app.state.running.store  # type: ignore[attr-defined]
    assert last.events_after(last.current(), 0)[-1].epoch == 1
