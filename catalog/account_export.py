"""Kontoexport (#56, CAT-188): everything the owner has in Catalog, as one ZIP file.

The ZIP has catalog.json, shaped by CatalogExport (contracts/catalog.py): the vehicles with their
tags and their links to prototypes, their history, the places, the settings, the trips with their
pack lists and ticks, the tags with their links and the owner's own events, and the pictures.
Beside it are the pictures' files, under bilder/<vehicle>/: the display picture, and the original
where Spara original kept one (CAT-17). The thumbnails, and what is kept to change a background,
are made from these and are left out. The pictures' addresses are left out too, since they expire
(CAT-130): the files are in the ZIP instead.

Only the owner's own is in it: everything is read by the owner's id, so someone else's vehicles,
tags, events and pictures never are. The data is read before the first byte is sent, so a no
comes as a no. Then the pictures are fetched one at a time and written to the ZIP while it goes
to the browser, so a fleet with many pictures is never held in memory. catalog.json comes last
and lists only the pictures whose files are in the ZIP: one removed meanwhile is left out.
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from catalog.fleet import Fleet, Refused
from catalog.pictures import EXTENSIONS, Pictures, Stored, kind_of
from catalog.tags import Tags
from catalog.trips import Trips
from contracts.catalog import CatalogExport, ExportPicture, Trip, Vehicle

LOGGER = logging.getLogger("catalog.export")
DATA: Final = "catalog.json"
"""The owner's data in the ZIP, shaped by CatalogExport."""


class _Spool:
    """Where the ZIP is written: the part not yet sent. zipfile goes back to finish each file's
    header once it knows the file's size and checksum, always within the file it has just
    written, so the ZIP needs no data descriptors; a part that is sent is never written again."""

    def __init__(self) -> None:
        self.sent = 0
        self.at = 0
        self.waiting = bytearray()

    def write(self, data: bytes) -> int:
        start = self.at - self.sent
        if start > len(self.waiting):
            self.waiting.extend(bytes(start - len(self.waiting)))
        self.waiting[start : start + len(data)] = data
        self.at += len(data)
        return len(data)

    def tell(self) -> int:
        return self.at

    def seek(self, offset: int, whence: int = 0) -> int:
        end = self.sent + len(self.waiting)
        target = {0: offset, 1: self.at + offset, 2: end + offset}[whence]
        if target < self.sent:
            raise OSError("That part of the ZIP is already sent.")
        self.at = target
        return target

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def take(self) -> bytes:
        """What is written and finished, to send now."""
        done = bytes(self.waiting)
        self.sent += len(done)
        self.at = self.sent
        self.waiting.clear()
        return done


def _without_address(vehicle: Vehicle) -> Vehicle:
    return vehicle.model_copy(update={"picture": None})


def _trip_without_addresses(trip: Trip) -> Trip:
    rows = [row.model_copy(update={"vehicle": _without_address(row.vehicle)}) for row in trip.rows]
    return trip.model_copy(update={"rows": rows})


@dataclass(frozen=True)
class Export:
    """What the owner has, read before anything is sent: the data, and the pictures to fetch."""

    data: CatalogExport
    stored: list[Stored]
    made_at: datetime

    @property
    def file_name(self) -> str:
        return f"trainmeet-catalog-{self.made_at:%Y-%m-%d}.zip"


class Exports:
    def __init__(self, fleet: Fleet, tags: Tags, trips: Trips, pictures: Pictures) -> None:
        self.fleet = fleet
        self.tags = tags
        self.trips = trips
        self.pictures = pictures

    def read(self, owner: UUID) -> Export:
        """The owner's data, and the pictures to fetch. The right is checked before: the
        owner's (catalog/access.py)."""
        data = self.fleet.export(owner)
        return Export(
            data=data.model_copy(
                update={
                    "vehicles": [_without_address(vehicle) for vehicle in data.vehicles],
                    "trips": [_trip_without_addresses(trip) for trip in self.trips.export(owner)],
                    "tags": self.tags.export(owner),
                }
            ),
            stored=self.pictures.of_owner(owner),
            made_at=datetime.now(UTC),
        )

    def zip(self, export: Export) -> Iterator[bytes]:
        """The ZIP, a part at a time: each picture's file as soon as it is written, and
        catalog.json last."""
        spool = _Spool()
        stamp = export.made_at.timetuple()[:6]
        listed: list[ExportPicture] = []
        with zipfile.ZipFile(spool, "w") as archive:
            for picture in export.stored:
                folder = f"bilder/{picture.vehicle}/{picture.id}"
                display = f"{folder}.{EXTENSIONS[kind_of(picture.display_key)]}"
                if not self._put(archive, display, picture.display_key, stamp):
                    continue
                yield spool.take()
                original: str | None = None
                if picture.original_key is not None:
                    named = f"{folder}-original.{EXTENSIONS[kind_of(picture.original_key)]}"
                    if self._put(archive, named, picture.original_key, stamp):
                        original = named
                        yield spool.take()
                listed.append(
                    ExportPicture(
                        id=picture.id,
                        vehicle=picture.vehicle,
                        main=picture.main,
                        position=picture.position,
                        width=picture.width,
                        height=picture.height,
                        background=picture.background,
                        display=display,
                        original=original,
                    )
                )
            data = export.data.model_copy(update={"pictures": listed})
            info = zipfile.ZipInfo(DATA, stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data.model_dump_json(indent=2).encode("utf-8"))
            yield spool.take()
        yield spool.take()

    def _put(
        self,
        archive: zipfile.ZipFile,
        name: str,
        key: str,
        stamp: tuple[int, int, int, int, int, int],
    ) -> bool:
        """One file, stored as it is: the pictures are compressed already."""
        try:
            data = self.pictures.fetch(key)
        except Refused:
            LOGGER.warning("En bild kom inte med i kontoexporten: den fanns inte i lagringen.")
            return False
        info = zipfile.ZipInfo(name, stamp)
        info.compress_type = zipfile.ZIP_STORED
        archive.writestr(info, data)
        return True
