"""Mätbilden under i Foto (#89 del d4, CAD-13, CAD-33, CAD8): the modules' measuring images from
TrainMeet CAD for a station that came from CAD, fetched when Studio makes the proposal (Gör
förslaget, Läs in igen) and kept with the station, so that Foto shows them at a meet without
internet.

TKL asks CAD with the person's own access token from ID, as for the graph (tkl/cad_client.py).
An image already kept for the same module, version and photo is not fetched again; Läs in igen
fetches only what changed. The images are JPEG at 1 px per mm, CAD's display copy of the
measuring image: a module 1500 × 600 mm is 1500 × 600 pixels, a few hundred kB. TKL keeps at
most IMAGE_LIMIT per image and STATION_LIMIT for the images of one link; a module whose image
does not fit is drawn as vectors, with the reason.

The choice to draw them is the station's (Mätbilden under), off by default, and grey with the
reason when the station has nothing to show: not from CAD, or no module photographed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from contracts.cad import StudioSourceKind
from contracts.station_model import StationModel
from contracts.tkl import TklCadImage, TklCadLink, TklImageUnder
from tkl.cad_client import Cad, CadError
from tkl.store import TklStore
from tkl.studio.fran_cad import from_cad

IMAGE_LIMIT: Final = 4 * 1024 * 1024
"""The largest measuring image TKL keeps: a module of 4 × 1 m at 1 px per mm is about 1 MB."""
STATION_LIMIT: Final = 32 * 1024 * 1024
"""What one station's images may take together: some hundred modules."""

NOT_FROM_CAD: Final = (
    "Mätbilden under kräver en station från TrainMeet CAD, med Från CAD under Rita i Studio. "
    "Foto ritar stationen som vektorer."
)
READ_AGAIN: Final = "Läs in stationen igen med Från CAD under Rita i Studio."
NOT_FETCHED: Final = f"Mätbilderna är inte hämtade. {READ_AGAIN}"
FAILED: Final = "Mätbilderna kunde inte hämtas"
NO_IMAGES: Final = (
    "Ingen av stationens moduler har en mätbild i TrainMeet CAD. Fota dem i CAD och läs in "
    "stationen igen."
)
TOO_LARGE: Final = "mätbilden är större än 4 MB och hämtas inte."
NO_ROOM: Final = "stationens mätbilder får ta högst 32 MB, och den här får inte plats."


def url(image: TklCadImage) -> str:
    """TKL's own address for a kept image: the photo in the query, so that a new photo is a
    new address."""
    return f"/api/tkl/1/matbilden/{image.module}/{image.version}?bild={image.job}"


@dataclass(frozen=True)
class Fetched:
    """What Gör förslaget got of the images: those kept, the modules without one with the
    reason, and the source's gauge."""

    images: list[TklCadImage]
    missing: list[str]
    gauge: float | None = None
    failed: bool = False
    """CAD did not give the list: the images a link has keep while its track plan stays."""

    def on(self, link: TklCadLink) -> TklCadLink:
        return link.model_copy(
            update={"images": self.images, "missing": self.missing, "gauge": self.gauge}
        )


def fetch(cad: Cad, store: TklStore, slot: str, kind: StudioSourceKind, source: UUID) -> Fetched:
    """The source's measuring images, kept with the station: those already kept for the same
    photo as they are, the others fetched. And the modules without one, with the reason. CAD
    not answering is a reason too: the proposal does not wait for the images."""
    try:
        listed = cad.images(kind, source)
    except CadError as error:
        return Fetched([], [f"{FAILED}: {error.detail}"], failed=True)
    kept = store.cad_images(slot)
    images: list[TklCadImage] = []
    missing = [f"{m.title}: {m.reason}" for m in listed.missing]
    total = 0
    for found in listed.images:
        title = f"{found.number} {found.name}"
        have = kept.get((str(found.module), found.version))
        data: bytes | None = None
        if have is not None and have[0] == str(found.job):
            size = have[1]
        else:
            try:
                data = cad.image(kind, source, found.module, found.version, IMAGE_LIMIT)
            except CadError as error:
                missing.append(f"{title}: {TOO_LARGE if error.status == 413 else error.detail}")
                continue
            size = len(data)
        if total + size > STATION_LIMIT:
            missing.append(f"{title}: {NO_ROOM}")
            continue
        if data is not None:
            store.keep_cad_image(slot, str(found.module), found.version, str(found.job), data)
        total += size
        images.append(
            TklCadImage(
                module=found.module,
                version=found.version,
                job=found.job,
                title=title,
                width=found.frame.width,
                height=found.frame.height,
                matrix=found.to_source,
                outline=found.outline,
                bytes=size,
            )
        )
    return Fetched(images, missing, listed.gauge)


def under(link: TklCadLink | None, model: StationModel | None, on: bool) -> TklImageUnder:
    """What Foto gets: the station's images and its choice, or grey with the reason. Only a
    model whose track plan still comes from CAD gets them: another model's geometry is not the
    images'."""
    images = link.images if link is not None else []
    missing = link.missing if link is not None else []
    reason: str | None = None
    if link is None or model is None or not any(from_cad(p.origin) for p in model.pieces):
        reason, images, missing = NOT_FROM_CAD, [], []
    elif not images and missing and missing[0].startswith(FAILED):
        reason = f"{missing[0]} {READ_AGAIN}"
    elif not images:
        reason = NO_IMAGES if missing else NOT_FETCHED
    return TklImageUnder(
        available=reason is None,
        reason=reason,
        on=on and reason is None,
        images=[i.model_copy(update={"url": url(i)}) for i in images],
        missing=missing,
        gauge=link.gauge if link is not None and reason is None else None,
        bytes=sum(i.bytes for i in images),
        limit=STATION_LIMIT,
    )
