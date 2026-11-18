"""Tellurian Dispatch i skugga (IMPORT-34), ported from the old Server's test_tellurian_contract,
test_tellurian_simulator and test_tellurian_settings: the read path and the comparison only.

Everything here is SIMULATED (TellurianSimulator on 127.0.0.1). It checks TrainMeet's side of
the contract, not Tellurian's server. Integrationer may not import Drift, tests included
(tests/test_boundaries.py), so Now is built from the contract the way drift.now builds it:
no halts among the places, and only open clearances.
"""

from __future__ import annotations

import http.client
import socket
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any

import pytest

from contracts.common import Weekday
from contracts.drift import Now, NowPlace, TellurianContact, TellurianShadow, TellurianState
from contracts.meet import MeetPackage, PlaceKind
from contracts.station import Clearance, ClearanceStatus, Clock
from integrationer.tellurian import (
    PROBLEMS,
    AddressRejected,
    DispatcherView,
    Endpoint,
    HttpTransport,
    TellurianClient,
    TellurianError,
    check_address,
    parse_dispatcher_view,
    parse_dispatchers,
    parse_train_label,
    problem_text,
    safe_href,
    shadow,
)
from integrationer.tellurian_sim import SimSection, TellurianSimulator

PACKAGE = MeetPackage.model_validate_json(
    files("contracts").joinpath("examples/provbanan.meet.json").read_bytes()
)
PLACES = [
    NowPlace(place=p.id, code=p.code, name=p.name)
    for p in PACKAGE.places
    if p.kind != PlaceKind.HALT
]
LOCAL = check_address("192.168.1.20:5000")
HEARD = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
APPROVED, WAITING = ClearanceStatus.APPROVED, ClearanceStatus.WAITING


class Direct:
    """The client's injectable transport, asking the simulator without HTTP."""

    simulated = True

    def __init__(self, sim: TellurianSimulator) -> None:
        self.sim = sim

    def get(self, path: str) -> object:
        if path == "/api/v1/dispatchers":
            return self.sim.dispatcher_list()
        return self.sim.dispatcher_view(int(path.rsplit("/", 1)[-1]))


def read(sim: TellurianSimulator) -> list[DispatcherView]:
    return TellurianClient(LOCAL, transport=Direct(sim)).views()


def drift_now(*clearances: Clearance, places: list[NowPlace] | None = None) -> Now:
    return Now(
        meet_id=PACKAGE.meet.id,
        name=PACKAGE.meet.name,
        traffic_day=Weekday.MON,
        game_day=1,
        clock=Clock(time="06:00", seconds=21600, running=True, speed=1.0, game_day=1),
        places=PLACES if places is None else places,
        legs=[],
        clearances=list(clearances),
    )


def clearance(
    train: str,
    from_place: str,
    to_place: str,
    section: str,
    status: ClearanceStatus = WAITING,
    *,
    departed: bool = False,
) -> Clearance:
    """A clearance as drift.snapshot.clearance_of gives it."""
    return Clearance(
        clearance_id=f"clr-{train}",
        call=f"t{train}-{from_place}",
        train_number=train,
        section=section,
        from_place=from_place,
        to_place=to_place,
        status=status,
        departed=departed,
        requested_at="06:00",
        revision=1,
    )


def compare(sim: TellurianSimulator, now: Now, package: MeetPackage = PACKAGE) -> TellurianShadow:
    return shadow(package, now, read(sim), simulated=False, heard=HEARD, problem=None)


def by_train(result: TellurianShadow) -> dict[str, Any]:
    return {row.train: row for row in result.sections}


@pytest.fixture
def sim() -> Iterator[TellurianSimulator]:
    with TellurianSimulator.from_package(PACKAGE) as simulator:
        yield simulator


@pytest.fixture
def client(sim: TellurianSimulator) -> TellurianClient:
    return TellurianClient(check_address(sim.base_url, test_instance=True), timeout=0.5)


# --- The address --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "kind"),
    [
        ("192.168.1.20:5000", "private"),
        ("http://10.0.0.5", "private"),
        ("http://172.20.1.1:8080/", "private"),
        ("169.254.10.2", "link_local"),
        ("http://tellurian.local:5000", "mdns"),
    ],
)
def test_a_local_address_needs_no_test_instance(address: str, kind: str) -> None:
    assert check_address(address).kind == kind


@pytest.mark.parametrize(
    "address",
    [
        "http://8.8.8.8",
        "https://example.org",
        "http://127.0.0.1:5000",
        "http://localhost",
        "http://[fd00::1]:80",
        "http://172.32.0.1",
        "http://100.64.0.1",
    ],
)
def test_anything_else_needs_a_test_instance(address: str) -> None:
    with pytest.raises(AddressRejected) as caught:
        check_address(address)
    assert caught.value.code == "address_not_local"
    assert check_address(address, test_instance=True).test_instance


def test_the_address_is_an_origin_only() -> None:
    assert check_address("192.168.1.20:5000").origin == "http://192.168.1.20:5000"
    assert check_address("https://Tellurian.Example.org", test_instance=True).origin == (
        "https://tellurian.example.org:443"
    )
    assert check_address("http://[fd00::1]", test_instance=True).origin == "http://[fd00::1]:80"


@pytest.mark.parametrize(
    ("address", "code"),
    [
        ("https://server.trainmeet.app", "address_trainmeet_cloud"),
        ("https://trainmeet.app", "address_trainmeet_cloud"),
        ("https://TrainMeet.app.", "address_trainmeet_cloud"),
        ("ftp://192.168.1.2", "address_scheme"),
        ("http://user:pw@192.168.1.2", "address_credentials"),
        ("http://192.168.1.2/api/v1", "address_path"),
        ("http://192.168.1.2/?x=1", "address_path"),
        ("http://192.168.1.2/#x", "address_path"),
        ("", "address_required"),
        ("   ", "address_required"),
        ("http://192.168.1.2:99999", "address_invalid"),
        ("http://192.168.1.2:0", "address_invalid"),
        ("http://192.168.1 .2", "address_invalid"),
    ],
)
def test_a_test_instance_never_allows_cloud_or_odd_urls(address: str, code: str) -> None:
    with pytest.raises(AddressRejected) as caught:
        check_address(address, test_instance=True)
    assert caught.value.code == code


def test_an_mdns_name_must_resolve_to_a_local_address() -> None:
    endpoint = check_address("http://tellurian.local:5000")
    local = HttpTransport(endpoint, resolver=lambda *a: [(2, 1, 6, "", ("192.168.1.30", 5000))])
    assert local.pinned_address() == "192.168.1.30"
    public = HttpTransport(endpoint, resolver=lambda *a: [(2, 1, 6, "", ("93.184.216.34", 5000))])
    with pytest.raises(TellurianError) as caught:
        public.pinned_address()
    assert caught.value.code == "address_not_local"

    def fails(*args: object) -> list[tuple[Any, ...]]:
        raise socket.gaierror("no such name")

    with pytest.raises(TellurianError) as caught:
        HttpTransport(endpoint, resolver=fails).pinned_address()
    assert caught.value.code == "unreachable"


def test_the_resolved_address_is_the_one_connected_to(sim: TellurianSimulator) -> None:
    """The name is looked up once, by the transport's own resolver, and never again."""
    port = int(sim.base_url.rsplit(":", 1)[1])
    endpoint = check_address(f"http://tellurian.invalid:{port}", test_instance=True)
    asked: list[str] = []

    def resolver(host: str, port: int, *rest: int) -> list[tuple[Any, ...]]:
        asked.append(host)
        return [(2, 1, 6, "", ("127.0.0.1", port))]

    transport = HttpTransport(endpoint, timeout=0.5, resolver=resolver)
    assert [d.signature for d in TellurianClient(endpoint, transport=transport).dispatchers()] == [
        "Nby",
        "Ån",
        "Mlå",
        "Sjv",
    ]
    assert asked == ["tellurian.invalid"]


def test_hrefs_must_stay_on_the_configured_origin() -> None:
    endpoint = Endpoint("http", "192.168.1.20", 5000, "private", False)
    assert (
        safe_href("http://192.168.1.20:5000/api/v1/dispatchers/1", endpoint)
        == "/api/v1/dispatchers/1"
    )
    assert safe_href("/api/v1/dispatchers/1", endpoint) == "/api/v1/dispatchers/1"
    for href in (
        "http://192.168.1.21:5000/api/v1/x",
        "https://192.168.1.20:5000/api/v1/x",
        "//evil/api/v1/x",
        "/admin",
        "/api/v1/a//b",
        "/api/v1/%2e%2e/x",
        "/api/v1/../x",
        "/api/v1/x?y=1",
        "/api/v1/x\n",
        "javascript:alert(1)",
        42,
        None,
    ):
        assert safe_href(href, endpoint) is None, href
    with pytest.raises(ValueError):
        HttpTransport(endpoint).get("/admin")


# --- Reading over HTTP ----------------------------------------------------------------------


def test_dispatchers_and_views_follow_the_server_links(
    sim: TellurianSimulator, client: TellurianClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://192.0.2.1:9")  # never used: no proxy from the environment
    sim.set_sections([SimSection("Pt 101", "Nby", "Ån", train_state="Manned", total=2)])
    dispatchers = client.dispatchers()
    assert [d.signature for d in dispatchers] == ["Nby", "Ån", "Mlå", "Sjv"]
    assert [d.name for d in dispatchers] == ["Norrby", "Åsen", "Mellanå", "Sjövik"]
    view = client.view(dispatchers[0])
    departure = view.departures[0]
    assert (departure.from_code, departure.to_code, departure.train_state, departure.state) == (
        "Nby",
        "Ån",
        "Manned",
        TellurianState.NONE,
    )
    assert (departure.total, departure.train_id) == (2, "1")
    assert view.section(departure.id) == departure
    assert client.simulated, "the simulator's answers are marked simulated"
    assert sim.requests == [("GET", "/api/v1/dispatchers"), ("GET", "/api/v1/dispatchers/1")]


def test_a_foreign_dispatcher_link_falls_back_to_the_documented_path() -> None:
    rows = [
        {"id": 1, "signature": "Nby", "href": "http://evil.example/api/v1/dispatchers/1"},
        {"id": 2, "signature": "Ån", "href": "http://192.168.1.20:5000/api/v1/dispatchers/2"},
        {"id": 3, "signature": "Mlå", "links": [{"rel": "self", "href": "/api/v1/places/3"}]},
        {"id": 4, "signature": "Sjv", "href": "/api/v1/../admin", "stationName": "Sjövik"},
        {"id": 4, "signature": "Dup"},
        {"id": "bad id", "signature": "X"},
        {"id": 5},
        "not a row",
    ]
    dispatchers = parse_dispatchers({"items": rows}, LOCAL)
    assert [(d.id, d.signature, d.href) for d in dispatchers] == [
        ("1", "Nby", "/api/v1/dispatchers/1"),
        ("2", "Ån", "/api/v1/dispatchers/2"),
        ("3", "Mlå", "/api/v1/places/3"),
        ("4", "Sjv", "/api/v1/dispatchers/4"),
    ]
    assert [d.name for d in dispatchers] == ["Nby", "Ån", "Mlå", "Sjövik"]
    with pytest.raises(TellurianError) as caught:
        parse_dispatchers({"something": "else"}, LOCAL)
    assert caught.value.code == "bad_shape"


def test_sections_are_read_defensively() -> None:
    dispatcher = parse_dispatchers([{"id": 2, "signature": "Ån"}], LOCAL)[0]
    data = {
        "id": 2,
        "arrivals": [
            {"id": 1, "train": "Pt 101", "from": {"signature": "Nby"}, "state": "Requested"},
            {"id": 2, "train": "Pt 102", "state": "Bogus", "trainState": "Bogus"},
            {"id": 3, "state": "Requested"},
            {"id": "a/b", "train": "Pt 103"},
            {"id": 4, "train": "Pt\x07 104"},
        ],
        "departures": [{"id": 5, "train": "Gt 4501", "to": "Mlå", "totalTrackStretches": 0}],
    }
    view = parse_dispatcher_view(data, dispatcher)
    assert [(s.id, s.from_code, s.to_code, s.state) for s in view.sections()] == [
        ("1", "Nby", "Ån", TellurianState.REQUESTED),
        ("2", None, "Ån", TellurianState.UNKNOWN),
        ("5", "Ån", "Mlå", TellurianState.UNKNOWN),
    ]
    assert view.arrivals[1].train_state == "Unknown"
    assert view.departures[0].total == 1
    wrong: object
    for wrong in ([], {"id": 3, "arrivals": []}):
        with pytest.raises(TellurianError) as caught:
            parse_dispatcher_view(wrong, dispatcher)
        assert caught.value.code == "bad_shape"


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("redirect", "redirect"),
        ("oversize", "too_large"),
        ("invalid_json", "bad_json"),
        ("server_error", "http_500"),
        ("timeout", "timeout"),
    ],
)
def test_transport_faults_are_codes_without_provider_text(
    sim: TellurianSimulator, fault: str, code: str
) -> None:
    client = TellurianClient(check_address(sim.base_url, test_instance=True), timeout=0.3)
    sim.fail_next_read(fault)
    with pytest.raises(TellurianError) as caught:
        client.dispatchers()
    assert caught.value.code == code
    assert caught.value.args == (code,)
    assert caught.value.__cause__ is None
    assert "secret" not in repr(caught.value.args)
    assert "example.invalid" not in str(caught.value)
    assert {method for method, _ in sim.requests} == {"GET"}


def test_an_unreachable_server_is_a_short_code() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = TellurianClient(check_address(f"http://127.0.0.1:{port}", test_instance=True))
    with pytest.raises(TellurianError) as caught:
        client.dispatchers()
    assert caught.value.code == "unreachable"


def test_train_labels() -> None:
    assert parse_train_label("SJ IC 456") == ("SJ", "IC", "456")
    assert parse_train_label("IC 007") == ("", "IC", "7")
    assert parse_train_label("101") == ("", "", "101")
    assert parse_train_label("Rangering") == ("", "", None)
    assert parse_train_label("SJ ²") == ("", "", None)
    assert parse_train_label("") == ("", "", None)


# --- The simulator --------------------------------------------------------------------------


def arrivals(sim: TellurianSimulator, signature: str) -> list[object]:
    rows = sim.dispatcher_view(sim.dispatcher_id(signature))["arrivals"]
    assert isinstance(rows, list)
    return [row["train"] for row in rows]


def test_arrived_sections_are_hidden_and_lists_are_capped() -> None:
    two = [SimSection("Pt 101", "Nby", "Ån"), SimSection("Pt 103", "Nby", "Ån")]
    sim = TellurianSimulator.from_package(PACKAGE)
    first, _ = sim.set_sections(two)
    sim.update(first, state="Arrived", train_state="Completed")
    assert arrivals(sim, "Ån") == ["Pt 103"]
    capped = TellurianSimulator.from_package(PACKAGE, max_items=1)
    capped.set_sections(two)
    assert arrivals(capped, "Ån") == ["Pt 101"]
    with pytest.raises(KeyError):
        sim.dispatcher_view(99)


def test_the_simulator_records_and_refuses_anything_but_get(sim: TellurianSimulator) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", int(sim.base_url.rsplit(":", 1)[1]))
    try:
        connection.request("POST", "/api/v1/train-sections/101/actions/request")
        with connection.getresponse() as response:
            assert response.status == 405
    finally:
        connection.close()
    assert sim.requests == [("POST", "/api/v1/train-sections/101/actions/request")]


# --- Skuggan: Tellurian beside Drift --------------------------------------------------------


def test_shadow_over_http_shows_a_clearance_only_tellurian_has(
    sim: TellurianSimulator, client: TellurianClient
) -> None:
    sim.set_sections([SimSection("Pt 101", "Nby", "Ån", state="Requested", train_state="Manned")])
    now = drift_now()
    result = shadow(
        PACKAGE, now, client.views(), simulated=client.simulated, heard=HEARD, problem=None
    )
    assert result.differences == 1
    [row] = result.sections  # shown at Norrby and at Åsen, compared once
    assert (row.train_number, row.from_code, row.to_code, row.section) == (
        "101",
        "Nby",
        "Ån",
        "s-nby-asn",
    )
    assert (row.state, row.drift, row.differs) == (TellurianState.REQUESTED, None, True)
    assert row.note == "Tellurian: begärd, Drift: ingen klarering."
    assert (result.simulated, result.contact, result.unmatched) == (True, TellurianContact.OK, [])
    # The shadow never writes, and Drift's own clearances are untouched.
    assert {method for method, _ in sim.requests} == {"GET"}
    assert now == drift_now()


def test_shadow_shows_differences_against_drifts_own_clearance() -> None:
    sim = TellurianSimulator.from_package(PACKAGE)
    sim.set_sections(
        [
            SimSection("Pt 101", "Nby", "Ån", state="Requested", train_state="Manned"),
            SimSection("Gt 4501", "Nby", "Ån", state="Requested", train_state="Manned"),
        ]
    )
    now = drift_now(
        clearance("101", "nby", "asn", "s-nby-asn", APPROVED),
        clearance("102", "sjv", "mla", "s-mla-sjv", WAITING),
    )
    result = compare(sim, now)
    rows = by_train(result)
    assert (rows["Pt 101"].drift, rows["Pt 101"].differs) == (APPROVED, True)
    assert rows["Pt 101"].note == "Tellurian: begärd, Drift: klar."
    assert (rows["Gt 4501"].drift, rows["Gt 4501"].differs) == (None, True)
    # 101 differs, 4501 is only in Tellurian and 102 only in Drift.
    assert result.differences == 3


def test_states_are_compared_per_station_pair_and_train() -> None:
    sim = TellurianSimulator.from_package(PACKAGE)
    sim.set_sections(
        [
            SimSection("Pt 101", "Nby", "Ån", state="Departed", train_state="Running"),
            SimSection("Pt 102", "Sjv", "Mlå", state="Requested", train_state="Manned"),
            SimSection("SJ RC 9", "HPL", "Mlå", state="Requested", train_state="Manned"),
            SimSection("Pt 103", "Nby", "Ån", state="None", train_state="Manned"),
        ]
    )
    now = drift_now(
        clearance("101", "nby", "asn", "s-nby-asn", APPROVED, departed=True),
        clearance("102", "sjv", "mla", "s-mla-sjv", APPROVED),
    )
    result = compare(sim, now)
    rows = by_train(result)
    assert result.differences == 1
    assert (rows["Pt 102"].differs, rows["Pt 102"].note) == (
        True,
        "Tellurian: begärd, Drift: klar.",
    )
    assert (rows["Pt 101"].drift, rows["Pt 101"].differs, rows["Pt 101"].note) == (
        APPROVED,
        False,
        None,
    )
    assert (rows["Pt 103"].differs, rows["Pt 103"].note) == (False, None)
    # A place Drift does not have is not compared, as in the old Server.
    assert (rows["SJ RC 9"].section, rows["SJ RC 9"].differs) == (None, False)
    assert rows["SJ RC 9"].note == "Driftplatsen finns inte i Drift."


def test_places_match_exactly_on_signature() -> None:
    sim = TellurianSimulator.from_package(PACKAGE)
    sim.set_sections([SimSection("Pt 101", "Nby", "Ån", state="Requested")])
    extra = [NowPlace(place="x", code="nby", name="Liten bokstav")]
    extra.append(NowPlace(place="hpl", code="HPL", name="Hultaplan"))
    result = compare(sim, drift_now(places=PLACES + extra))
    assert result.unmatched == ["nby", "HPL"]
    assert by_train(result)["Pt 101"].section == "s-nby-asn"
    # A duplicate in Drift never matches; the section through it is not compared.
    twice = [*PLACES, NowPlace(place="asn2", code="Ån", name="Dubblett")]
    result = compare(sim, drift_now(places=twice))
    assert result.unmatched == ["Ån"]
    assert by_train(result)["Pt 101"].note == "Driftplatsen finns inte i Drift."
    # Nor does a duplicate in Tellurian, or a signature that differs only in case.
    for dispatchers, left in (
        (
            [("Nby", "Norrby"), ("Ån", "Åsen"), ("Mlå", "Mellanå"), ("Sjv", "S"), ("Sjv", "S")],
            "Sjv",
        ),
        ([("NBY", "Norrby"), ("Ån", "Åsen"), ("Mlå", "Mellanå"), ("Sjv", "Sjövik")], "Nby"),
    ):
        assert compare(TellurianSimulator(dispatchers), drift_now()).unmatched == [left]


def test_sections_match_drifts_section_by_the_station_pair() -> None:
    sim = TellurianSimulator.from_package(PACKAGE)
    sim.set_sections(
        [
            SimSection("Pt 101", "Nby", "Ån"),
            SimSection("Pt 102", "Ån", "Nby"),
            SimSection("Pt 103", "Mlå", "Sjv"),
            SimSection("Pt 105", "Nby", "Sjv", state="Requested"),
        ]
    )
    rows = by_train(compare(sim, drift_now()))
    assert {train: row.section for train, row in rows.items()} == {
        "Pt 101": "s-nby-asn",
        "Pt 102": "s-nby-asn",
        "Pt 103": "s-mla-sjv",
        "Pt 105": None,
    }
    assert rows["Pt 105"].note == "Tellurian: begärd, Drift: sträckan finns inte."
    # The direction counts: Drift's clearance from Norrby is not Tellurian's from Åsen.
    sim.set_sections([SimSection("Pt 101", "Ån", "Nby", state="Requested")])
    result = compare(sim, drift_now(clearance("101", "nby", "asn", "s-nby-asn")))
    assert (by_train(result)["Pt 101"].drift, result.differences) == (None, 2)


def test_trains_match_by_number_only_when_unambiguous() -> None:
    first = PACKAGE.trains[0]
    package = PACKAGE.model_copy(
        update={
            "trains": [
                *PACKAGE.trains,
                first.model_copy(update={"id": "t104b", "number": "104", "service_key": "b"}),
                first.model_copy(update={"id": "t106s", "number": "106", "days": [Weekday.SUN]}),
            ]
        }
    )
    sim = TellurianSimulator.from_package(package)
    sim.set_sections(
        [
            SimSection("TAB RC 101", "Nby", "Ån", state="Requested"),
            SimSection("SJ RC 101", "Nby", "Ån", state="Requested"),
            SimSection("Pt 0103", "Nby", "Ån", state="Requested"),
            SimSection("Pt 104", "Sjv", "Mlå", state="Requested"),
            SimSection("Pt 106", "Sjv", "Mlå", state="Requested"),
            SimSection("Pt 555", "Nby", "Ån", state="Requested"),
            SimSection("Rangering", "Nby", "Ån", state="Requested"),
        ]
    )
    now = drift_now(
        clearance("101", "nby", "asn", "s-nby-asn"),
        clearance("103", "nby", "asn", "s-nby-asn"),
        clearance("104", "sjv", "mla", "s-mla-sjv"),
        clearance("106", "sjv", "mla", "s-mla-sjv"),
    )
    result = compare(sim, now, package)
    rows = by_train(result)
    ambiguous = "Tåget går inte att skilja från ett annat med samma nummer."
    # Two of Tellurian's trains, or two of Drift's on the day, are never guessed between.
    for train in ("TAB RC 101", "SJ RC 101", "Pt 104"):
        assert (rows[train].drift, rows[train].differs, rows[train].note) == (
            None,
            False,
            ambiguous,
        )
    # A number that is unique on both sides matches, leading zeros or not; another day's
    # train with the same number does not count.
    for train in ("Pt 0103", "Pt 106"):
        assert (rows[train].drift, rows[train].differs) == (WAITING, False)
    for train in ("Pt 555", "Rangering"):
        assert rows[train].note == "Tellurian: begärd, Drift: tåget finns inte."
    assert rows["Rangering"].train_number is None
    assert result.differences == 2


def test_contact_problem_and_simulated() -> None:
    waiting = shadow(PACKAGE, drift_now(), [], simulated=True, heard=None, problem="unreachable")
    assert (waiting.contact, waiting.problem) == (TellurianContact.WAITING, PROBLEMS["unreachable"])
    assert (waiting.simulated, waiting.unmatched) == (True, [])

    def contact(at: datetime) -> TellurianContact:
        return shadow(
            PACKAGE, drift_now(), [], simulated=False, heard=HEARD, problem=None, at=at
        ).contact

    assert contact(HEARD + timedelta(seconds=15)) == TellurianContact.OK
    assert contact(HEARD + timedelta(seconds=16)) == TellurianContact.LOST
    lost = shadow(PACKAGE, drift_now(), [], simulated=False, heard=HEARD, problem="http_503")
    assert lost.problem == "Tellurian Dispatch svarade med fel (HTTP 503)."
    # No dispatcher read: every place is unmatched once Tellurian has answered.
    assert lost.unmatched == ["Nby", "Ån", "Mlå", "Sjv"]
    assert problem_text("secret stack trace") == "Tellurian Dispatch gick inte att läsa."
