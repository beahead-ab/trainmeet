"""Förebildskatalogen (#53 del a, CAT-03, CAT-141, CAT-155–CAT-165, CAT-173, CAT-213).

A pretend ID says who reviews (the role reviewer on catalog:prototypes, CAT-165), who the fleet
is shared with, and reads the photos as for a reading. The people log in with the trial login:
Provkonto A and B propose and link, and Provkonto C reviews when the pretend ID says so. Ported
from TrainCatalog's catalog/test_catalog.py and catalog/test_profiles.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from catalog.login import TRIAL_ACCOUNTS
from catalog.prototype_fields import BY_KEY, PROFILES, REGISTER, RETIRED, BadTypeData, clean
from catalog.tests.test_batches import batch, sent
from catalog.tests.test_pictures import World, photo, world_with
from catalog.tests.test_reading import PretendMeter, read, send
from catalog.tests.test_sharing import HBIS, A, B
from contracts.catalog import (
    FieldProfile,
    FieldRegister,
    Prototype,
    PrototypeList,
    PrototypeRevision,
    Vehicle,
)

API = "/api/catalog/1"
C = str(TRIAL_ACCOUNTS[2].id)
OWN = {"kind": "own", "text": "Egen mätning och SJ:s typritning."}
TYPE = {
    "litt": "Hbis",
    "operator": "SJ",
    "description": "Täckt godsvagn med skjutväggar",
    "length_over_buffers": "14 020",
    "max_speed": "100",
    "axles": "2",
}


@dataclass
class PretendReviewers(PretendMeter):
    """ID, which also says who reviews the prototypes: reviewer on catalog:prototypes."""

    reviewers: set[str] = field(default_factory=set)

    def handle(self, request: httpx.Request) -> httpx.Response:
        resource = request.url.params.get("resource", "")
        if request.url.path.endswith("/apps/access") and resource.startswith("catalog:"):
            assert resource == "catalog:prototypes"
            assert request.headers["authorization"] == f"Bearer t{self.tokens}"
            if self.down:
                raise httpx.ConnectError("nere", request=request)
            person = request.url.params["person"]
            return httpx.Response(
                200, json={"roles": ["reviewer"] if person in self.reviewers else []}
            )
        return super().handle(request)


@dataclass
class Catalog:
    world: World
    id: PretendReviewers
    a: TestClient
    b: TestClient
    c: TestClient
    """Provkonto C, a reviewer."""


@pytest.fixture
def pretend() -> PretendReviewers:
    return PretendReviewers()


@pytest.fixture
def cat(database_url: str, tmp_path: Path, pretend: PretendReviewers) -> Iterator[Catalog]:
    with world_with(database_url, tmp_path, pretend=pretend) as made:
        c = TestClient(made.nobody.app)
        assert c.post(f"{API}/trial/login", json={"account": C}).status_code == 200
        pretend.reviewers.add(C)
        yield Catalog(made, pretend, made.a, made.b, c)


def proposal(**change: Any) -> dict[str, Any]:
    return {
        "name": "Hbis",
        "kind": "freight_wagon",
        "profile": "SE",
        "fields": TYPE,
        "source": OWN,
        "may_share": True,
        **change,
    }


def proposed(client: TestClient, **change: Any) -> PrototypeRevision:
    answer = client.post(f"{API}/prototypes/proposals", json=proposal(**change))
    assert answer.status_code == 201, answer.text
    return PrototypeRevision.model_validate(answer.json())


def reviewed(
    cat: Catalog, revision: PrototypeRevision, decision: str = "approve", comment: str = "Stämmer."
) -> PrototypeRevision:
    answer = cat.c.post(
        f"{API}/prototypes/proposals/{revision.id}/review",
        json={"decision": decision, "comment": comment},
    )
    assert answer.status_code == 200, answer.text
    return PrototypeRevision.model_validate(answer.json())


def listed(client: TestClient, query: str = "") -> PrototypeList:
    answer = client.get(f"{API}/prototypes{query}")
    assert answer.status_code == 200, answer.text
    return PrototypeList.model_validate(answer.json())


def vehicle_of(answer: httpx.Response) -> Vehicle:
    assert answer.status_code == 200, answer.text
    return Vehicle.model_validate(answer.json())


def link(
    client: TestClient, car: Vehicle, revision: PrototypeRevision, fleet: str | None = None
) -> httpx.Response:
    path = f"{API}/vehicles/{car.id}/prototype" + (f"?fleet={fleet}" if fleet else "")
    body = {
        "version": car.version,
        "prototype": str(revision.prototype),
        "revision": revision.number,
    }
    answered: httpx.Response = client.post(path, json=body)
    return answered


def own_values(client: TestClient, car: Vehicle, fields: dict[str, str]) -> httpx.Response:
    answered: httpx.Response = client.put(
        f"{API}/vehicles/{car.id}/prototype", json={"version": car.version, "fields": fields}
    )
    return answered


def new_vehicle(client: TestClient) -> Vehicle:
    answer = client.post(f"{API}/vehicles", json=HBIS)
    assert answer.status_code == 201, answer.text
    return Vehicle.model_validate(answer.json())


# --- The field register (CAT-156, CAT-157, CAT-158) -------------------------------------------

PUBLISHED = {
    "litt": ("text", ""),
    "operator": ("text", ""),
    "epoch": ("text", ""),
    "description": ("text", ""),
    "length_over_buffers": ("number", "mm"),
    "wheelbase": ("number", "mm"),
    "weight": ("number", "t"),
    "max_speed": ("number", "km/h"),
    "load": ("number", "t"),
    "axles": ("integer", ""),
    "built": ("text", ""),
    "brake": ("text", ""),
    "length_ft": ("number", "ft"),
    "truck_centers_ft": ("number", "ft"),
    "weight_lbs": ("number", "lbs"),
    "max_speed_mph": ("number", "mph"),
    "load_lbs": ("number", "lbs"),
}
"""Every key once published, with its kind and unit. A key keeps its meaning for good: this
list only grows, and a key that is no longer wanted moves to RETIRED, never to a new meaning."""


def test_the_field_register_never_reuses_a_key_with_another_meaning() -> None:
    keys = [f.key for f in REGISTER]
    assert len(keys) == len(set(keys)), "a key is in the register once"
    assert not set(keys) & RETIRED, "a retired key is never used again"
    assert set(PUBLISHED) <= set(keys) | RETIRED, "a published key is never dropped silently"
    for key, (kind, unit) in PUBLISHED.items():
        if key in BY_KEY:
            assert (BY_KEY[key].kind.value, BY_KEY[key].unit) == (kind, unit), key
    assert set(keys) <= set(PUBLISHED), "a new key is added to PUBLISHED with its meaning"
    # Sweden, Europe and the USA from the start, each with the twelve type data (CAT-157,
    # CAT-158); the US profile in its own units, with keys of their own.
    assert set(PROFILES) == set(FieldProfile)
    for profile in PROFILES.values():
        assert len(profile.keys) == len(set(profile.keys)) == 12
        assert set(profile.keys) <= set(BY_KEY) and set(profile.labels) <= set(profile.keys)
    assert PROFILES[FieldProfile.SE].keys == PROFILES[FieldProfile.EU].keys
    us_units = {BY_KEY[key].unit for key in PROFILES[FieldProfile.US].keys}
    assert not us_units & {"mm", "t", "km/h"}


def test_the_values_are_checked_against_the_register_and_the_profile() -> None:
    se = FieldProfile.SE
    assert clean(se, {"length_over_buffers": "14 020", "weight": "12,50", "axles": "2"}) == {
        "length_over_buffers": "14020",
        "weight": "12.5",
        "axles": "2",
    }
    assert clean(se, {"brake": "  ", "litt": " Hbis "}) == {"litt": "Hbis"}
    assert clean(se, {"brake": ""}, empty=True) == {"brake": ""}
    for wrong in (
        {"max_speed": "snabb"},
        {"max_speed": "-5"},
        {"axles": "2.5"},
        {"length_ft": "46"},  # the US profile's
        {"number": "2253"},  # the vehicle's own number is never type data (CAT-155)
        {"litt": "x" * 41},
    ):
        with pytest.raises(BadTypeData):
            clean(se, wrong)
    assert clean(FieldProfile.US, {"length_ft": "50.5"}) == {"length_ft": "50.5"}


def test_the_register_is_published_to_anyone(cat: Catalog) -> None:
    answer = cat.world.nobody.get(f"{API}/prototypes/fields")
    assert answer.status_code == 200, answer.text
    register = FieldRegister.model_validate(answer.json())
    assert [p.profile for p in register.profiles] == ["SE", "EU", "US"]
    units = {f.key: f.unit for f in register.fields}
    assert (units["max_speed"], units["max_speed_mph"]) == ("km/h", "mph")
    us = {f.key: f.label for f in register.profiles[2].fields}
    assert us["litt"] == "Klass"
    assert cat.world.nobody.get(f"{API}/prototypes").status_code == 401


# --- Proposals and the review (CAT-163, CAT-164, CAT-165) -------------------------------------


def test_a_proposal_waits_in_the_queue_and_is_seen_by_everyone_once_approved(cat: Catalog) -> None:
    first = proposed(cat.a)
    assert (first.number, first.status, first.mine, first.base) == (1, "proposed", True, None)
    assert first.fields["length_over_buffers"] == "14020"
    # Only reviewed prototypes are seen by others (CAT-164).
    assert listed(cat.b).prototypes == []
    assert cat.b.get(f"{API}/prototypes/{first.prototype}").status_code == 404
    mine = listed(cat.a)
    assert [(p.name, p.status) for p in mine.prototypes] == [("Hbis", "proposed")]
    assert (mine.reviewer, mine.to_review) == (False, 0)
    assert [r.id for r in revisions_of(cat.a.get(f"{API}/prototypes/proposals/mine"))] == [first.id]
    # The queue and the review are for the reviewers ID names (CAT-165).
    assert cat.a.get(f"{API}/prototypes/proposals/queue").status_code == 403
    no = cat.a.post(f"{API}/prototypes/proposals/{first.id}/review", json={"decision": "approve"})
    assert no.status_code == 403
    queue = revisions_of(cat.c.get(f"{API}/prototypes/proposals/queue"))
    assert [(r.id, r.proposed_by, r.mine) for r in queue] == [(first.id, "Provkonto A", False)]
    assert (listed(cat.c).reviewer, listed(cat.c).to_review) == (True, 1)
    done = reviewed(cat, first, comment="Stämmer med ritningen.")
    assert (done.status, done.comment) == ("reviewed", "Stämmer med ritningen.")
    assert done.reviewed_at is not None
    # Now everyone sees it, without who proposed it.
    (seen,) = listed(cat.b).prototypes
    assert (seen.status, seen.revision, seen.vehicles, seen.fields["max_speed"]) == (
        "reviewed",
        1,
        0,
        "100",
    )
    page = Prototype.model_validate(cat.b.get(f"{API}/prototypes/{first.prototype}").json())
    assert [(r.number, r.status, r.proposed_by) for r in page.revisions] == [(1, "reviewed", None)]
    assert "Provkonto A" not in cat.b.get(f"{API}/prototypes").text
    assert cat.c.get(f"{API}/prototypes/proposals/queue").json() == []
    again = cat.c.post(
        f"{API}/prototypes/proposals/{first.id}/review", json={"decision": "approve"}
    )
    assert (again.status_code, again.json()["code"]) == (409, "changed")


def revisions_of(answer: httpx.Response) -> list[PrototypeRevision]:
    assert answer.status_code == 200, answer.text
    return [PrototypeRevision.model_validate(item) for item in answer.json()]


def test_a_proposal_needs_a_name_a_source_and_the_yes_to_share(cat: Catalog) -> None:
    """CAT-163, CAT-213: and only the type data of the profile, by the register (CAT-156)."""
    for wrong in (
        {"may_share": False},
        {"name": ""},
        {"source": {"kind": "own", "text": ""}},
        {"source": {"kind": "rykte", "text": "Hört"}},
    ):
        assert cat.a.post(f"{API}/prototypes/proposals", json=proposal(**wrong)).status_code == 422
    body = proposal()
    del body["may_share"]
    assert cat.a.post(f"{API}/prototypes/proposals", json=body).status_code == 422
    for fields in ({"number": "2253"}, {"max_speed": "fort"}, {"length_ft": "46"}):
        answer = cat.a.post(f"{API}/prototypes/proposals", json=proposal(fields=fields))
        assert (answer.status_code, answer.json()["code"]) == (422, "bad_type_data"), fields
    assert cat.world.nobody.post(f"{API}/prototypes/proposals", json=proposal()).status_code == 401
    assert listed(cat.c).to_review == 0


def test_a_rejection_has_a_comment_and_stays_with_the_proposer(cat: Catalog) -> None:
    zans = proposed(cat.a, name="Zans", fields={"litt": "Zans", "operator": "SJ"})
    silent = cat.c.post(f"{API}/prototypes/proposals/{zans.id}/review", json={"decision": "reject"})
    assert silent.status_code == 422
    no = reviewed(cat, zans, "reject", "Källan räcker inte. Ange typritningen.")
    assert (no.status, no.comment) == ("rejected", "Källan räcker inte. Ange typritningen.")
    (mine,) = revisions_of(cat.a.get(f"{API}/prototypes/proposals/mine"))
    assert (mine.status, mine.comment) == ("rejected", "Källan räcker inte. Ange typritningen.")
    assert cat.b.get(f"{API}/prototypes/{zans.prototype}").status_code == 404
    assert listed(cat.a).prototypes == [] and listed(cat.b).prototypes == []
    page = cat.a.get(f"{API}/prototypes/{zans.prototype}")
    assert (page.status_code, page.json()["status"]) == (200, "rejected")


def test_a_reviewer_who_id_no_longer_names_reviews_nothing(cat: Catalog) -> None:
    first = proposed(cat.a)
    cat.id.reviewers.clear()
    assert cat.c.get(f"{API}/prototypes/proposals/queue").status_code == 403
    assert listed(cat.c).reviewer is False
    cat.id.reviewers.add(C)
    cat.id.down = True
    gone = cat.c.post(f"{API}/prototypes/proposals/{first.id}/review", json={"decision": "approve"})
    assert (gone.status_code, gone.json()["code"]) == (503, "unavailable")


def test_a_change_is_a_new_revision_built_on_the_reviewed_one(cat: Catalog) -> None:
    first = reviewed(cat, proposed(cat.a))
    change = proposed(
        cat.b,
        prototype=str(first.prototype),
        base=1,
        fields={**TYPE, "max_speed": "120"},
        source={"kind": "reference", "text": "Svenska godsvagnar, del 2."},
    )
    assert (change.number, change.base, change.status) == (2, 1, "proposed")
    stale = cat.a.post(
        f"{API}/prototypes/proposals",
        json=proposal(prototype=str(first.prototype), base=2),
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "changed")
    unknown = cat.a.post(
        f"{API}/prototypes/proposals", json=proposal(prototype=str(uuid.uuid4()), base=1)
    )
    assert unknown.status_code == 404
    # Everyone still sees revision 1 until the change is approved.
    assert listed(cat.a).prototypes[0].revision == 1
    assert listed(cat.a).prototypes[0].waiting == 0
    assert listed(cat.b).prototypes[0].waiting == 1
    reviewed(cat, change)
    page = Prototype.model_validate(cat.a.get(f"{API}/prototypes/{first.prototype}").json())
    assert (page.revision, page.fields["max_speed"]) == (2, "120")
    assert [(r.number, r.status) for r in page.revisions] == [(2, "reviewed"), (1, "reviewed")]
    # Two changes on the same revision: the second cannot be approved after the first.
    one = proposed(cat.a, prototype=str(first.prototype), base=2, fields={**TYPE, "axles": "4"})
    two = proposed(cat.b, prototype=str(first.prototype), base=2, fields={**TYPE, "brake": "KE"})
    reviewed(cat, one)
    late = cat.c.post(f"{API}/prototypes/proposals/{two.id}/review", json={"decision": "approve"})
    assert (late.status_code, late.json()["code"]) == (409, "changed")
    assert reviewed(cat, two, "reject", "Bygg på revision 3.").status == "rejected"


# --- The vehicle (CAT-160, CAT-161, CAT-162) -----------------------------------------------------


def test_a_linked_vehicle_keeps_its_snapshot_and_sees_that_a_newer_one_exists(
    cat: Catalog,
) -> None:
    first = reviewed(cat, proposed(cat.a))
    car = new_vehicle(cat.a)
    linked = vehicle_of(link(cat.a, car, first))
    assert linked.version == car.version + 1
    assert linked.prototype is not None
    assert (linked.prototype.name, linked.prototype.revision, linked.prototype.newer) == (
        "Hbis",
        1,
        False,
    )
    assert linked.prototype.fields == linked.prototype.snapshot == first.fields
    assert (linked.litt, linked.number, linked.operator) == (car.litt, car.number, car.operator)
    assert listed(cat.b).prototypes[0].vehicles == 1
    change = proposed(
        cat.b, prototype=str(first.prototype), base=1, fields={**TYPE, "max_speed": "120"}
    )
    reviewed(cat, change)
    # Never overwritten in the background (CAT-161): the card says that a newer one exists.
    now = vehicle_of(cat.a.get(f"{API}/vehicles/{car.id}"))
    assert now.prototype is not None
    assert (now.prototype.revision, now.prototype.latest, now.prototype.newer) == (1, 2, True)
    assert now.prototype.fields["max_speed"] == "100"
    assert now.version == linked.version
    # The update is the owner's choice: linking again to the newer revision.
    updated = vehicle_of(link(cat.a, now, change))
    assert updated.prototype is not None
    assert (updated.prototype.revision, updated.prototype.newer) == (2, False)
    assert updated.prototype.fields["max_speed"] == "120"
    # A change built on an older version of the vehicle is refused (CAT-63).
    assert link(cat.a, now, change).json()["code"] == "changed"
    # A proposal is never linked, only a reviewed revision.
    waiting = proposed(cat.b, name="Gbs", fields={"litt": "Gbs"})
    assert link(cat.a, updated, waiting).status_code == 404
    # Koppla bort: the type data go, the core fields stay.
    gone = vehicle_of(cat.a.delete(f"{API}/vehicles/{car.id}/prototype?version={updated.version}"))
    assert gone.prototype is None
    assert (gone.litt, gone.number, gone.operator) == (car.litt, car.number, car.operator)
    assert listed(cat.b).prototypes[0].vehicles == 0


def test_the_owners_own_values_are_kept_and_an_equal_value_inherits(cat: Catalog) -> None:
    first = reviewed(cat, proposed(cat.a))
    car = vehicle_of(link(cat.a, new_vehicle(cat.a), first))
    assert car.prototype is not None
    # Sent back as shown, nothing is the owner's own: the equal values inherit (CAT-162).
    same = vehicle_of(own_values(cat.a, car, dict(car.prototype.fields)))
    assert same.prototype is not None and same.prototype.overrides == {}
    written = {
        **TYPE,
        "length_over_buffers": "14020,0",
        "max_speed": "90",
        "axles": "",
        "brake": "",
    }
    own = vehicle_of(own_values(cat.a, same, written))
    assert own.prototype is not None
    # An empty value is the owner's own when the prototype has one, as axles here.
    assert own.prototype.overrides == {"max_speed": "90", "axles": ""}
    assert own.prototype.fields["max_speed"] == "90"
    assert "axles" not in own.prototype.fields
    assert own.prototype.snapshot["max_speed"] == "100"
    bad = own_values(cat.a, own, {"max_speed": "snabb"})
    assert (bad.status_code, bad.json()["code"]) == (422, "bad_type_data")
    # A new revision: the update keeps the owner's own values, and inherits the rest.
    change = reviewed(
        cat,
        proposed(
            cat.b,
            prototype=str(first.prototype),
            base=1,
            fields={**TYPE, "max_speed": "110", "weight": "12.5", "brake": "KE-GP"},
        ),
    )
    updated = vehicle_of(link(cat.a, own, change))
    assert updated.prototype is not None
    assert updated.prototype.overrides == {"max_speed": "90", "axles": ""}
    assert (updated.prototype.fields["max_speed"], updated.prototype.fields["weight"]) == (
        "90",
        "12.5",
    )
    assert updated.prototype.fields["brake"] == "KE-GP"
    assert "axles" not in updated.prototype.fields
    # An own value that the prototype now has too is no longer the owner's own.
    agreed = reviewed(
        cat,
        proposed(
            cat.b,
            prototype=str(first.prototype),
            base=2,
            fields={**TYPE, "max_speed": "90", "weight": "12.5"},
        ),
    )
    again = vehicle_of(link(cat.a, updated, agreed))
    assert again.prototype is not None
    assert again.prototype.overrides == {"axles": ""}
    # Another prototype starts without them.
    other = reviewed(cat, proposed(cat.b, name="Gbs", fields={"litt": "Gbs", "operator": "SJ"}))
    moved = vehicle_of(link(cat.a, again, other))
    assert moved.prototype is not None
    assert (moved.prototype.name, moved.prototype.overrides) == ("Gbs", {})


def test_an_editor_links_and_someone_who_looks_does_not(cat: Catalog) -> None:
    """CAT-46: linking a prototype is an edit; 404 for a fleet not shared (CAT-49)."""
    first = reviewed(cat, proposed(cat.a))
    car = new_vehicle(cat.a)
    assert link(cat.b, car, first, fleet=A).status_code == 404
    cat.id.roles[(B, A)] = "viewer"
    looked = link(cat.b, car, first, fleet=A)
    assert (looked.status_code, looked.json()["code"]) == (403, "forbidden")
    assert own_values(cat.b, car, {}).status_code == 404  # without ?fleet=, B's own
    cat.id.roles[(B, A)] = "editor"
    edited = vehicle_of(link(cat.b, car, first, fleet=A))
    assert edited.prototype is not None and edited.tags == []
    cat.id.roles[(B, A)] = "viewer"
    seen = vehicle_of(cat.b.get(f"{API}/vehicles/{car.id}?fleet={A}"))
    assert seen.prototype is not None and seen.prototype.name == "Hbis"
    path = f"{API}/vehicles/{car.id}/prototype?fleet={A}&version={edited.version}"
    assert cat.b.delete(path).status_code == 403
    cat.id.roles[(B, A)] = "editor"
    assert vehicle_of(cat.b.delete(path)).prototype is None


# --- The suggestion from a reading and a batch card (CAT-141) ----------------------------------


def test_a_reading_suggests_the_reviewed_prototype_whose_litt_and_operator_match(
    cat: Catalog,
) -> None:
    waiting = proposed(cat.b, fields={"litt": "HBIS", "operator": " S J "})
    before = read(send(cat.a))
    assert {n: s.value for n, s in before.suggestions.items()}["litt"] == "Hbis"
    assert before.prototype is None, "a proposal is never suggested"
    reviewed(cat, waiting)
    reading = read(send(cat.a))
    assert reading.prototype is not None
    assert (reading.prototype.id, reading.prototype.name, reading.prototype.revision) == (
        waiting.prototype,
        "Hbis",
        1,
    )
    # Only a suggestion: nothing is linked, and no vehicle is made (CAT-136, CAT-143).
    assert cat.a.get(f"{API}/vehicles").json()["total"] == 0
    # Another operator is another type.
    other = proposed(cat.b, name="Hbis Green Cargo", fields={"litt": "Hbis", "operator": "GC"})
    reviewed(cat, other)
    assert read(send(cat.a)).prototype == reading.prototype


def test_a_batch_card_suggests_the_prototype_for_its_litt_and_operator(cat: Catalog) -> None:
    hbis = reviewed(cat, proposed(cat.b))
    made = batch(sent(cat.a, [photo()], ai=False))
    (card,) = made.cards
    assert card.prototype is None
    values = {**card.values.model_dump(mode="json"), "litt": "hbis ", "operator": "sj"}
    changed = cat.a.post(
        f"{API}/batches/{made.id}/cards/{card.id}", json={"values": values, "version": card.version}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["prototype"] == {"id": str(hbis.prototype), "name": "Hbis", "revision": 1}
    shown = cat.a.get(f"{API}/batches/{made.id}").json()["cards"][0]
    assert shown["prototype"]["id"] == str(hbis.prototype)


def test_the_catalog_is_searched_on_litt_operator_and_type(cat: Catalog) -> None:
    """CAT-173: one type per row, with the type data in the row."""
    reviewed(cat, proposed(cat.a))
    reviewed(
        cat,
        proposed(
            cat.a,
            name="Rc6",
            kind="locomotive",
            fields={"litt": "Rc 6", "operator": "SJ", "description": "Ellok"},
        ),
    )
    assert [p.name for p in listed(cat.b).prototypes] == ["Hbis", "Rc6"]
    for query, names in (
        ("?q=rc6", ["Rc6"]),
        ("?q=skjutväggar", ["Hbis"]),
        ("?q=sj", ["Hbis", "Rc6"]),
        ("?kind=locomotive", ["Rc6"]),
        ("?q=Zans", []),
    ):
        assert [p.name for p in listed(cat.b, query).prototypes] == names, query
    whole = listed(cat.b)
    assert (whole.license, whole.license_url) == (
        "CC BY-SA 4.0",
        "https://creativecommons.org/licenses/by-sa/4.0/",
    )
