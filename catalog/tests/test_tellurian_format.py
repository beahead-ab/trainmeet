"""Tellurian's format (#56, CAT-185, CAT-186): a vehicle out as a file for Tellurian's card app,
and such files in as drafts that the owner reviews and approves.

Ported from TrainCatalog's tests for the format: the round trip, the EVN split as the app wants
it, the painted grouping, names outside Latin-1, and odd files that fail by themselves. The files
here are made for the tests and hold no one's data.
"""

from __future__ import annotations

import base64
import io
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from catalog import tellurian
from catalog.tests.test_pictures import World, photo, problem, upload, world_with
from catalog.tests.test_prototypes import (
    C,
    Catalog,
    PretendReviewers,
    link,
    new_vehicle,
    proposed,
    reviewed,
    vehicle_of,
)
from catalog.tests.test_sharing import A, B
from contracts.catalog import (
    Batch,
    FieldProfile,
    TellurianImport,
    Vehicle,
    VehicleKind,
    VehiclePrototype,
)

API = "/api/catalog/1"

# A file as the app writes it, with the get-only properties it also writes. Made for the tests.
TELLURIAN_FILE: dict[str, Any] = {
    "IsPassengerWagon": False,
    "IsCargoWagon": True,
    "Description": "Täckt godsvagn med skjutdörrar",
    "LoadLimit": 27.5,
    "LoadVolume": 0,
    "LoadArea": 0,
    "LoadingInstructions": None,
    "IsEuropConformant": False,
    "IsInterfrigoConformant": False,
    "IsMcConformant": False,
    "IsOpwConformant": False,
    "IsRivConformant": True,
    "IsTenConformant": False,
    "IsFlatWagon": False,
    "WagonColor": "#6b2b1f",
    "ModelWeight": 95,
    "ModelWeightGrams": "95g",
    "HomeStation": {"Name": "Provbanan", "Region": 1, "CountryCode": "SE"},
    "BackColor": "#339967",
    "ForeColor": "#FFFFFF",
    "Interoperability": "21 RIV",
    "FrameColor": "#339967",
    "Scale": 0,
    "OperatorSignature": "GC",
    "OperatorLogo": None,
    "VehicleClass": "Gbs",
    "InteroperatbilityNumber": 21,
    "CountryRegistrationNumber": 74,
    "VehicleNumber": "150 3 087",
    "Epoch": "IV-V",
    "UicMainClass": None,
    "OperatingFromYear": 1970,
    "OperatingUptoYear": 2005,
    "MaxSpeed": 100,
    "SpeedUnit": 0,
    "YearOfManufacturing": None,
    "Manufacturer": "",
    "Length": 14.02,
    "OriginalImage": None,
    "OriginalImageUrl": "https://bilder.example.invalid/gbs.jpg",
    "ModelImage": None,
    "ModelImageUrl": None,
    "ModelManufacturer": "Provmodeller",
    "ModelNumber": "4711",
    "WheelType": None,
    "Marking": {
        "UseMarking": True,
        "UseColorMarking": False,
        "Color1": "#FF7700",
        "Color2": "#00FF77",
        "Color3": "#7700FF",
        "Color4": "#FFFFFF",
        "InventoryNumber": "",
        "IconHref": None,
        "TextLabel": None,
        "Icon": None,
    },
    "PrintOptions": {
        "PrintCard": True,
        "PrintInventoryCard": True,
        "PrintFredSticker": True,
        "PrintExtraFredSticker": False,
        "DisplayQRCode": True,
    },
    "Owner": {
        "OwnerName": "Provägaren",
        "ClubName": "Provklubben",
        "PhoneNumber": "",
        "EmailAddress": "prov@example.invalid",
    },
}
# The properties the app sets: what an exported file must carry.
TELLURIAN_KEYS = set(TELLURIAN_FILE) - {
    "IsCargoWagon",
    "ModelWeightGrams",
    "BackColor",
    "ForeColor",
    "Interoperability",
    "FrameColor",
}
GBS_NUMBER = "21 74 150 3 087-3"
CORE = ("kind", "litt", "number", "operator", "epoch", "scale", "maker", "article_number")


@pytest.fixture
def world(database_url: str, tmp_path: Path) -> Iterator[World]:
    with world_with(database_url, tmp_path, batch_queue=False) as made:
        yield made


@pytest.fixture
def reviewing(database_url: str, tmp_path: Path) -> Iterator[Catalog]:
    """Catalog with a reviewer of the prototypes, Provkonto C, as in test_prototypes.py."""
    pretend = PretendReviewers()
    with world_with(database_url, tmp_path, pretend=pretend) as made:
        c = TestClient(made.nobody.app)
        assert c.post(f"{API}/trial/login", json={"account": C}).status_code == 200
        pretend.reviewers.add(C)
        yield Catalog(made, pretend, made.a, made.b, c)


def jpeg(color: tuple[int, int, int], size: tuple[int, int] = (120, 60)) -> str:
    return base64.b64encode(photo(size, color)).decode("ascii")


def file(wagon: Any, name: str = "Gbs.json") -> tuple[str, tuple[str, bytes, str]]:
    data = wagon if isinstance(wagon, bytes) else json.dumps(wagon).encode("utf-8")
    return ("files", (name, data, "application/json"))


def imported(
    client: httpx.Client | Any,
    *wagons: Any,
    ident: uuid.UUID | None = None,
    fleet: str | None = None,
) -> httpx.Response:
    data = {"id": str(ident or uuid.uuid4())}
    files = [file(wagon, f"fil{n}.json") for n, wagon in enumerate(wagons, start=1)]
    path = f"{API}/batches/tellurian" + (f"?fleet={fleet}" if fleet else "")
    answer: httpx.Response = client.post(path, data={"data": json.dumps(data)}, files=files)
    return answer


def result(answer: httpx.Response) -> TellurianImport:
    assert answer.status_code == 200, answer.text
    return TellurianImport.model_validate(answer.json())


def approve(client: httpx.Client | Any, batch: Batch) -> list[Vehicle]:
    cards = [{"id": str(card.id), "version": card.version} for card in batch.cards]
    answer = client.post(f"{API}/batches/{batch.id}/approve", json={"cards": cards})
    assert answer.status_code == 200, answer.text
    done = Batch.model_validate(answer.json())
    return [
        Vehicle.model_validate(client.get(f"{API}/vehicles/{card.vehicle}").json())
        for card in done.cards
    ]


def exported(client: httpx.Client | Any, vehicle: str | uuid.UUID) -> tuple[httpx.Response, Any]:
    answer: httpx.Response = client.get(f"{API}/vehicles/{vehicle}/tellurian")
    assert answer.status_code == 200, answer.text
    return answer, json.loads(answer.content)


def made(client: httpx.Client | Any, **fields: Any) -> dict[str, Any]:
    body = {"status": "ready", "kind": "freight_wagon", "litt": "Gbs", **fields}
    answer = client.post(f"{API}/vehicles", json=body)
    assert answer.status_code == 201, answer.text
    found: dict[str, Any] = answer.json()
    return found


# --- The import makes drafts (CAT-186, CAT-148) -------------------------------------------------


def test_the_import_makes_drafts_not_vehicles_until_they_are_approved(world: World) -> None:
    done = result(imported(world.a, TELLURIAN_FILE))
    (one,) = done.files
    assert (one.ok, one.name, one.already, one.error) == (True, "fil1.json", False, None)
    assert one.notes == [tellurian.NO_LINKS, tellurian.NO_TYPE_DATA, tellurian.NO_OWNER_DATA]
    batch = done.batch
    assert batch is not None and one.batch == batch.id
    assert (batch.source, batch.ai, batch.mine) == ("file", False, True)
    (card,) = batch.cards
    assert (card.id, card.source, card.file_name, card.status) == (
        one.card,
        "file",
        "fil1.json",
        "ready",
    )
    assert card.picture is None and card.suggestions == {}
    assert card.warnings == one.notes
    values = card.values.model_dump(mode="json")
    assert {key: values[key] for key in CORE} == {
        "kind": "freight_wagon",
        "litt": "Gbs",
        "number": GBS_NUMBER,
        "operator": "GC",
        "epoch": "IV-V",
        "scale": "H0",
        "maker": "Provmodeller",
        "article_number": "4711",
    }
    # A draft, not a vehicle: not in the list, and the batch waits under Fordon.
    assert world.a.get(f"{API}/vehicles").json()["total"] == 0
    (waiting,) = world.a.get(f"{API}/batches").json()
    assert (waiting["source"], waiting["open"]) == ("file", 1)

    (vehicle,) = approve(world.a, batch)
    assert world.a.get(f"{API}/vehicles").json()["total"] == 1
    assert vehicle.status == "ready" and vehicle.number == GBS_NUMBER
    assert vehicle.evn is not None and vehicle.evn.text == GBS_NUMBER and vehicle.evn.valid
    # What was approved as the file had it came from the import (CAT-64).
    assert vehicle.field_sources == dict.fromkeys(CORE, "import")
    # The owner's details in the file never become anyone's.
    assert "Provklubben" not in json.dumps(world.a.get(f"{API}/vehicles").json())
    assert world.a.get(f"{API}/batches").json() == []


def test_a_value_the_owner_changes_before_approval_is_the_owners(world: World) -> None:
    batch = result(imported(world.a, TELLURIAN_FILE)).batch
    assert batch is not None
    (card,) = batch.cards
    values = {**card.values.model_dump(mode="json"), "litt": "Gbss"}
    changed = world.a.post(
        f"{API}/batches/{batch.id}/cards/{card.id}",
        json={"values": values, "version": card.version},
    )
    assert changed.status_code == 200, changed.text
    (vehicle,) = approve(
        world.a, Batch.model_validate(world.a.get(f"{API}/batches/{batch.id}").json())
    )
    assert vehicle.field_sources["litt"] == "owner"
    assert vehicle.field_sources["number"] == "import"


def test_someone_who_edits_imports_for_the_owner_to_approve(world: World) -> None:
    world.id.roles[(B, A)] = "editor"
    done = result(imported(world.b, TELLURIAN_FILE, fleet=A))
    assert done.batch is not None and done.batch.mine
    approved = world.b.post(
        f"{API}/batches/{done.batch.id}/approve?fleet={A}",
        json={"cards": [{"id": str(c.id), "version": c.version} for c in done.batch.cards]},
    )
    assert problem(approved) == (403, "forbidden")
    (vehicle,) = approve(world.a, done.batch)
    assert vehicle.litt == "Gbs"
    world.id.roles[(B, A)] = "viewer"
    assert problem(imported(world.b, TELLURIAN_FILE, fleet=A)) == (403, "forbidden")


# --- Export and import again (CAT-185) ----------------------------------------------------------


def test_the_export_opens_in_the_app_and_imports_to_the_same_core_fields(world: World) -> None:
    batch = result(imported(world.a, TELLURIAN_FILE)).batch
    assert batch is not None
    (vehicle,) = approve(world.a, batch)
    answer, wagon = exported(world.a, vehicle.id)
    assert answer.headers["content-type"].startswith("application/json")
    assert answer.headers["content-disposition"].startswith("attachment;")
    assert 'filename="Gbs_21_74_150_3_087-3.json"' in answer.headers["content-disposition"]
    assert set(wagon) == TELLURIAN_KEYS
    for key in (
        "OperatorSignature",
        "VehicleClass",
        "InteroperatbilityNumber",
        "CountryRegistrationNumber",
        "VehicleNumber",
        "Epoch",
        "ModelManufacturer",
        "ModelNumber",
        "IsPassengerWagon",
        "Scale",
    ):
        assert wagon[key] == TELLURIAN_FILE[key], key
    # Types as the C# properties want them: System.Text.Json is strict.
    assert isinstance(wagon["InteroperatbilityNumber"], int)
    assert isinstance(wagon["LoadLimit"], float)
    assert isinstance(wagon["Marking"]["UseColorMarking"], bool)
    assert set(wagon["Marking"]) == set(TELLURIAN_FILE["Marking"])
    assert set(wagon["PrintOptions"]) == set(TELLURIAN_FILE["PrintOptions"])
    assert set(wagon["Owner"]) == set(TELLURIAN_FILE["Owner"])
    assert set(wagon["HomeStation"]) == set(TELLURIAN_FILE["HomeStation"])
    # The owner's name is the only owner data; the note never leaves (CAT-191).
    assert wagon["Owner"] == {
        "OwnerName": "Provkonto A",
        "ClubName": "",
        "PhoneNumber": "",
        "EmailAddress": "",
    }

    # The exported file imports again to the same core fields.
    again = result(imported(world.a, wagon))
    assert again.files[0].notes == []
    assert again.batch is not None
    (card,) = again.batch.cards
    assert card.values.model_dump(include=set(CORE)) == vehicle.model_dump(include=set(CORE))


def test_a_vehicle_made_by_hand_goes_out_and_back_the_same(world: World) -> None:
    car = made(
        world.a,
        kind="passenger_coach",
        litt="B7",
        number="50 74 20-35 123-5",
        operator="SJ",
        epoch="III",
        scale="N",
        maker="Provmodeller",
        article_number="B-7",
        note="Hemligt: köpt på loppis",
    )
    _, wagon = exported(world.a, car["id"])
    assert (
        wagon["InteroperatbilityNumber"],
        wagon["CountryRegistrationNumber"],
        wagon["VehicleNumber"],
    ) == (50, 74, "20-35 123")
    assert (wagon["IsPassengerWagon"], wagon["Scale"]) == (True, 1)
    assert "loppis" not in json.dumps(wagon, ensure_ascii=False)
    batch = result(imported(world.a, wagon)).batch
    assert batch is not None
    (card,) = batch.cards
    assert card.values.model_dump(mode="json", include=set(CORE)) == {key: car[key] for key in CORE}


def test_the_evn_is_split_and_joined_as_the_app_has_it() -> None:
    assert tellurian.split_number("31 76 393 3 013-1") == (31, 76, "393 3 013")
    assert tellurian.split_number("50 74 20-35 123-5") == (50, 74, "20-35 123")
    assert tellurian.split_number("21 74 1503087") == (21, 74, "1503087")
    # Without its check digit the EVN is still read; the app adds the digit itself.
    assert tellurian.split_number("21 74 150 3 087") == (21, 74, "150 3 087")
    # A wrong painted check digit is never corrected (CAT-59): the number goes whole.
    assert tellurian.split_number("31 76 393 3 013-2") == (0, 0, "31 76 393 3 013-2")
    assert tellurian.split_number("3087") == (0, 0, "3087")
    assert tellurian.split_number("") == (0, 0, "")

    assert tellurian.join_number(31, 76, "393 3 013") == ("31 76 393 3 013-1", True)
    assert tellurian.join_number(50, 74, "20-35 123") == ("50 74 20-35 123-5", True)
    # Its own check digit stays, right or wrong; the card shows whether it is (CAT-59).
    assert tellurian.join_number(31, 76, "393 3 013-2") == ("31 76 393 3 013-2", True)
    assert tellurian.join_number(None, None, "6018 035-3") == ("6018 035-3", True)
    assert tellurian.join_number(31, 76, "31 76 393 3 013-1") == ("31 76 393 3 013-1", True)
    assert tellurian.join_number(31, 76, "1234") == ("1234", False)


def test_the_evn_is_split_in_the_file_and_the_check_digit_is_shown_on_import(
    world: World,
) -> None:
    car = made(world.a, litt="Rps", number="31 76 393 3 013-1", operator="NSB")
    _, wagon = exported(world.a, car["id"])
    assert (
        wagon["InteroperatbilityNumber"],
        wagon["CountryRegistrationNumber"],
        wagon["VehicleNumber"],
    ) == (31, 76, "393 3 013")
    wrong = made(world.a, litt="Rps", number="31 76 393 3 013-2")
    _, sent = exported(world.a, wrong["id"])
    assert (
        sent["InteroperatbilityNumber"],
        sent["CountryRegistrationNumber"],
        sent["VehicleNumber"],
    ) == (0, 0, "31 76 393 3 013-2")
    short = {**TELLURIAN_FILE, "VehicleNumber": "1234"}
    (one,) = result(imported(world.a, short)).files
    assert tellurian.NO_PARTS in one.notes


def test_the_type_data_go_out_from_the_prototype() -> None:
    """The description, top speed, length and load the app shows are the prototype's."""
    now = "2026-11-18T12:00:00Z"
    prototype = VehiclePrototype(
        id=uuid.uuid4(),
        name="Gbs",
        kind=VehicleKind.FREIGHT_WAGON,
        profile=FieldProfile.SE,
        revision=2,
        snapshot={},
        overrides={},
        fields={
            "description": "Täckt godsvagn",
            "length_over_buffers": "14020",
            "max_speed": "100",
            "load": "27.5",
            "built": "1968–1975",
        },
        latest=2,
        newer=False,
    )
    vehicle = Vehicle.model_validate(
        {
            "id": str(uuid.uuid4()),
            "version": 1,
            "state": "home",
            "status": "ready",
            "kind": "freight_wagon",
            "litt": "Gbs",
            "number": GBS_NUMBER,
            "created_at": now,
            "updated_at": now,
            "prototype": prototype.model_dump(mode="json"),
        }
    )
    wagon = tellurian.to_tellurian(vehicle, "Provkonto A", None)
    assert (wagon["Description"], wagon["MaxSpeed"], wagon["SpeedUnit"]) == (
        "Täckt godsvagn",
        100,
        0,
    )
    assert (wagon["Length"], wagon["LoadLimit"], wagon["YearOfManufacturing"]) == (
        14.02,
        27.5,
        1968,
    )
    american = prototype.model_copy(update={"fields": {"max_speed_mph": "60", "length_ft": "50"}})
    us = tellurian.to_tellurian(vehicle.model_copy(update={"prototype": american}), "", None)
    assert (us["MaxSpeed"], us["SpeedUnit"], us["Length"]) == (60, 1, 15.24)
    assert (
        tellurian.to_tellurian(vehicle.model_copy(update={"prototype": None}), "", None)["MaxSpeed"]
        is None
    )


def test_the_file_has_the_type_data_of_the_linked_prototype(reviewing: Catalog) -> None:
    revision = reviewed(reviewing, proposed(reviewing.a))
    car = vehicle_of(link(reviewing.a, new_vehicle(reviewing.a), revision))
    _, wagon = exported(reviewing.a, car.id)
    assert (wagon["Description"], wagon["MaxSpeed"], wagon["Length"]) == (
        "Täckt godsvagn med skjutväggar",
        100,
        14.02,
    )


def test_names_outside_latin_1_still_download(world: World) -> None:
    car = made(world.a, litt="Eas", number="31 54 593 0 001-0", operator="ČD")
    answer, _ = exported(world.a, car["id"])
    assert answer.headers["content-disposition"].startswith("attachment;")
    assert "filename*=utf-8''Eas_31_54_593_0_001-0.json" in answer.headers["content-disposition"]
    sj = made(world.a, litt="Žaes", number="7720")
    named = exported(world.a, sj["id"])[0].headers["content-disposition"]
    assert "filename*=utf-8''%C5%BDaes_7720.json" in named
    assert 'filename="_aes_7720.json"' in named


def test_only_the_owner_exports(world: World) -> None:
    car = made(world.a, number="3087")
    path = f"{API}/vehicles/{car['id']}/tellurian"
    world.id.roles[(B, A)] = "editor"
    assert problem(world.b.get(f"{path}?fleet={A}")) == (403, "forbidden")
    world.id.roles[(B, A)] = "viewer"
    assert problem(world.b.get(f"{path}?fleet={A}")) == (403, "forbidden")
    del world.id.roles[(B, A)]
    assert problem(world.b.get(f"{path}?fleet={A}")) == (404, "not_found")
    assert problem(world.b.get(path)) == (404, "not_found")
    assert problem(world.nobody.get(path)) == (401, "login")


# --- The pictures in the file ---------------------------------------------------------------------


def test_the_model_picture_comes_along_and_the_prototype_picture_does_not(world: World) -> None:
    wagon = {
        **TELLURIAN_FILE,
        "ModelImageUrl": None,
        "OriginalImageUrl": None,
        "ModelImage": {"Base64data": jpeg((120, 60, 40)), "ContentType": "image/jpeg"},
        "OriginalImage": {"Base64data": jpeg((90, 90, 90)), "ContentType": "image/jpeg"},
    }
    done = result(imported(world.a, wagon))
    assert tellurian.NO_PROTOTYPE_PICTURE in done.files[0].notes
    assert tellurian.NO_LINKS not in done.files[0].notes
    assert done.batch is not None
    (card,) = done.batch.cards
    assert card.picture is not None
    shown = Image.open(io.BytesIO(world.nobody.get(card.picture.display_url).content))
    assert shown.size == (120, 60)
    (vehicle,) = approve(world.a, done.batch)
    assert vehicle.picture is not None
    pictures = world.a.get(f"{API}/vehicles/{vehicle.id}/pictures").json()
    assert [p["main"] for p in pictures] == [True]
    # Out again as the model picture, a JPEG.
    _, out = exported(world.a, vehicle.id)
    model = base64.b64decode(out["ModelImage"]["Base64data"])
    assert Image.open(io.BytesIO(model)).format == "JPEG"
    assert out["ModelImage"]["ContentType"] == "image/jpeg"
    assert out["OriginalImage"] is None


def test_a_transparent_picture_goes_out_as_a_jpeg_on_white(world: World) -> None:
    clear = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    out = io.BytesIO()
    clear.save(out, "WEBP")
    flat = Image.open(io.BytesIO(tellurian.as_jpeg(out.getvalue())))
    assert flat.format == "JPEG" and flat.convert("RGB").getpixel((5, 5)) == (255, 255, 255)
    plain = photo()
    assert tellurian.as_jpeg(plain) == plain
    car = made(world.a, number="3087")
    assert upload(world, car["id"], photo((80, 50))).status_code == 201
    _, wagon = exported(world.a, car["id"])
    assert Image.open(io.BytesIO(base64.b64decode(wagon["ModelImage"]["Base64data"]))).size == (
        80,
        50,
    )


def test_a_picture_that_cannot_be_used_leaves_the_draft_without_it(world: World) -> None:
    broken = {**TELLURIAN_FILE, "ModelImage": {"Base64data": "inte base64!"}}
    not_a_picture = {
        **TELLURIAN_FILE,
        "VehicleClass": "Gbss",
        "ModelImage": {"Base64data": base64.b64encode(b"GIF89a").decode("ascii")},
    }
    first, second = result(imported(world.a, broken, not_a_picture)).files
    assert (first.ok, first.error) == (False, tellurian.BAD_PICTURE)
    assert second.ok and second.notes[-1].startswith("Modellbilden kom inte med: ")


# --- Files that cannot be read (CAT-186) ----------------------------------------------------------


def test_bad_files_are_reported_one_by_one_in_swedish(world: World) -> None:
    mph = {**TELLURIAN_FILE, "SpeedUnit": 1, "MaxSpeed": 60}
    bad = {**TELLURIAN_FILE, "VehicleClass": 12}
    data = {"data": json.dumps({"id": str(uuid.uuid4())})}
    files = [
        file(mph, "mph.json"),
        file(bad, "bad.json"),
        file({"hello": 1}, "hello.json"),
        file(b"{not json", "x.json"),
        file(b"[1, 2]", "lista.json"),
    ]
    done = result(world.a.post(f"{API}/batches/tellurian", data=data, files=files))
    assert [(f.name, f.ok) for f in done.files] == [
        ("mph.json", True),
        ("bad.json", False),
        ("hello.json", False),
        ("x.json", False),
        ("lista.json", False),
    ]
    assert (
        done.files[1].error == "Filen har ett värde som inte kan läsas: VehicleClass ska vara text."
    )
    assert done.files[2].error == "Filen är inte ett vagnkort i Tellurians format."
    assert done.files[3].error == "Filen är inte giltig JSON."
    assert done.files[4].error == "Filen är inte ett vagnkort i Tellurians format."
    assert done.batch is not None and len(done.batch.cards) == 1
    assert world.a.get(f"{API}/vehicles").json()["total"] == 0


def test_odd_values_fail_their_own_file_only(world: World) -> None:
    data = {"data": json.dumps({"id": str(uuid.uuid4())})}
    files = [
        file(b"[" * 200_000, "djup.json"),
        file(TELLURIAN_FILE, "gbs.json"),
        file(b'{"VehicleClass": "Rps", "MaxSpeed": 1e999, "SpeedUnit": 1}', "inf.json"),
        file(b'{"VehicleClass": "Rps", "LoadLimit": NaN}', "nan.json"),
        file(b'{"VehicleClass": "Rps", "Scale": true, "IsPassengerWagon": 1}', "udda.json"),
    ]
    done = result(world.a.post(f"{API}/batches/tellurian", data=data, files=files))
    assert [f.ok for f in done.files] == [False, True, True, False, True]
    assert done.files[0].error == done.files[3].error == "Filen är inte giltig JSON."
    assert done.batch is not None
    infinite, odd = done.batch.cards[1], done.batch.cards[2]
    assert (infinite.values.litt, infinite.warnings) == ("Rps", [])
    assert (odd.values.scale, odd.values.kind) == ("", "freight_wagon")


def test_fifty_files_are_allowed_and_fifty_one_are_refused(world: World) -> None:
    many = [{**TELLURIAN_FILE, "VehicleNumber": f"150 3 {n:03d}"} for n in range(51)]
    assert problem(imported(world.a, *many)) == (422, "bad_form")
    assert problem(imported(world.a)) == (422, "bad_form")
    done = result(imported(world.a, *many[:50]))
    assert done.batch is not None and len(done.batch.cards) == 50
    assert all(f.ok and not f.already for f in done.files)
    assert world.a.get(f"{API}/vehicles").json()["total"] == 0


def test_the_files_together_stay_under_the_limit(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("catalog.reading_api.MAX_FORM", 100)
    answer = imported(world.a, TELLURIAN_FILE)
    assert problem(answer) == (413, "files_too_large")
    assert "MB tillsammans" in answer.json()["message"]
    assert world.a.get(f"{API}/batches").json() == []


def test_a_file_too_large_is_refused_by_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tellurian, "MAX_FILE_BYTES", 10)
    with pytest.raises(tellurian.Unreadable, match="större än 20 MB"):
        tellurian.read(json.dumps(TELLURIAN_FILE).encode())


# --- The same file once (CAT-149) -----------------------------------------------------------------


def test_a_duplicate_file_gives_no_second_draft(world: World) -> None:
    first = result(imported(world.a, TELLURIAN_FILE, TELLURIAN_FILE))
    assert first.batch is not None and len(first.batch.cards) == 1
    one, two = first.files
    assert (one.already, two.already, one.card == two.card) == (False, True, True)

    # In a new import: the draft it already is, and no new batch.
    again = result(imported(world.a, TELLURIAN_FILE))
    assert again.batch is None
    (same,) = again.files
    assert (same.ok, same.already, same.card, same.batch) == (True, True, one.card, one.batch)

    # The same request again, with the same batch: the same answer, nothing more.
    retried = result(imported(world.a, TELLURIAN_FILE, ident=first.batch.id))
    assert retried.batch is not None and len(retried.batch.cards) == 1

    # Approved, it is still the vehicle it became: never a second draft.
    approve(world.a, first.batch)
    after = result(imported(world.a, TELLURIAN_FILE))
    assert after.files[0].already and after.batch is None
    assert world.a.get(f"{API}/vehicles").json()["total"] == 1

    # Another owner's same file is their own draft.
    theirs = result(imported(world.b, TELLURIAN_FILE))
    assert theirs.batch is not None and not theirs.files[0].already


def test_a_photo_batchs_id_is_not_taken_over_by_an_import(world: World) -> None:
    ident = uuid.uuid4()
    photos = world.a.post(
        f"{API}/batches",
        data={"data": json.dumps({"id": str(ident), "ai": False})},
        files=[("images", ("foto.jpg", photo(), "image/jpeg"))],
    )
    assert photos.status_code == 200, photos.text
    assert problem(imported(world.a, TELLURIAN_FILE, ident=ident)) == (409, "changed")
