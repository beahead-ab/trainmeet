"""The vehicles' pictures (CAT-05, CAT-17, CAT-123–CAT-133): several per vehicle, one main
picture, and the storage counted per owner.

An upload is prepared before anything is saved: read with Pillow, at most 15 MB and 40
megapixel, JPEG, PNG or WebP (CAT-123); turned upright and copied pixel by pixel into a new
picture, so no position, camera, colour profile or comment survives (CAT-124); and made into a
display picture and a thumbnail, and the original only with Spara original (CAT-126). Then the
files are stored, and the picture is saved in a short transaction that locks the owner's row
first (CAT-40), so two uploads at once never go over the owner's limit (CAT-131). The owner is
the fleet's owner, also for someone who edits a shared fleet (CAT-133). Whatever fails after
the files were stored deletes them again.

The files are private: in Object Storage (S3Store), or on Catalog's own disk when there is none
(DiskStore, locally and in the tests). Either way they are fetched with signed addresses that
expire (CAT-130). An address stays the same for half an hour, so the browser can keep the
picture, and is valid for at least half an hour more.

A removed picture's keys go to picture_trash by a trigger, also when its vehicle or its owner is
removed, and sweep() deletes the files. So do the keys a change of background leaves, by
another trigger. An upload marks its keys there before it stores them, due an hour later, and
takes the marks away when the picture is saved: an upload that stops halfway, even with the
process, leaves no files behind for long. A change of background does the same.

The background removal (catalog/backgrounds.py, CAT-127–CAT-129) runs at the upload when the
model is there: the photo is cut around the vehicle and gets the background chosen, original
by default. For any other background the photo at display size is kept too, and the mask
always, so the background can be changed later without a new upload; both count in the
storage. With the original background the display picture is itself the kept photo.

Paid storage over the free level (CAT-132) comes later.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import logging
import os
import re
import secrets
import time
import uuid
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol, cast
from urllib.parse import quote
from uuid import UUID

import httpx
from botocore.auth import S3SigV4Auth, S3SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
from psycopg import Connection
from psycopg.rows import DictRow

from catalog.backgrounds import (
    NoSegmenter,
    Segmenter,
    backgrounds_off,
    crop_box,
    fit,
    no_vehicle,
    render,
    subject_box,
)
from catalog.db import Database
from catalog.fleet import Refused, not_found
from catalog.settings import Settings
from contracts.catalog import (
    Picture,
    PictureBackground,
    PictureLinks,
    ProblemCode,
    StorageUse,
)

LOGGER = logging.getLogger("catalog.pictures")

MB: Final = 1024 * 1024
MAX_BYTES: Final = 15 * MB
"""The most an uploaded picture may be (CAT-123)."""
MAX_PIXELS: Final = 40_000_000
"""40 megapixel (CAT-123)."""
PER_VEHICLE: Final = 10
"""Pictures per vehicle, for everyone (CAT-17)."""
PERSON_LIMIT: Final = 100 * MB
"""A person's free storage (CAT-17)."""
CLUB_LIMIT: Final = 2 * 1024 * MB
"""A club's free storage (TOKEN-29, TK17)."""
KINDS: Final = frozenset({"image/jpeg", "image/png", "image/webp"})
"""What an upload may say it is."""
LINK_LIFETIME: Final = 3600
"""How long a signed address is valid, in seconds (CAT-130)."""
FILES_PATH: Final = "/api/catalog/1/pictures/file/"
"""Where Catalog serves DiskStore's files."""

_FORMATS: Final = ("JPEG", "PNG", "WEBP")
_DISPLAY: Final = ((1800, 1800), 82)
_THUMB: Final = ((360, 240), 75)
_ORIGINAL_QUALITY: Final = 95
EXTENSIONS: Final = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
"""What a stored file is, by its key's ending. The masks are PNG, transparency is WebP."""
_KEY: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[0-9a-f]{32}\.(?:jpg|png|webp)"
)
_UPLOAD_GRACE: Final = timedelta(hours=1)
_SWEEP_BATCH: Final = 200
_SRGB: Final = ImageCms.createProfile("sRGB")
_COLUMNS: Final = (
    "id, is_main, position, width, height, bytes, display_key, thumb_key, original_key, "
    "background, source_key, mask_key"
)


def _unreadable() -> Refused:
    return Refused(
        422,
        ProblemCode.BAD_PICTURE,
        "Bilden kunde inte läsas. Välj en giltig JPEG-, PNG- eller WebP-bild.",
    )


def wrong_kind() -> Refused:
    return Refused(
        415,
        ProblemCode.BAD_PICTURE,
        "Välj JPEG, PNG eller WebP. Exportera HEIC/HEIF som JPEG först.",
    )


def too_large() -> Refused:
    return Refused(413, ProblemCode.PICTURE_TOO_LARGE, "Bilden är för stor. Högst 15 MB per bild.")


def _too_many_pixels() -> Refused:
    return Refused(
        422,
        ProblemCode.PICTURE_TOO_LARGE,
        "Bilden har för hög upplösning. Högst 40 megapixel.",
    )


def _no_picture() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Bilden finns inte.")


def _picture_changed() -> Refused:
    return Refused(
        409,
        ProblemCode.CHANGED,
        "Bilden ändrades under tiden. Öppna fordonet igen och försök på nytt.",
    )


def _store_down() -> Refused:
    return Refused(
        503, ProblemCode.UNAVAILABLE, "Bilderna kan inte sparas just nu. Försök igen om en stund."
    )


def _size(amount: int) -> str:
    """100 MB, 2 GB, or 0,3 MB: as the person reads it."""
    unit, divisor = ("GB", 1024 * MB) if amount >= 1024 * MB else ("MB", MB)
    value = amount / divisor
    shown = f"{value:.0f}" if value == int(value) else f"{value:.1f}"
    return f"{shown.replace('.', ',')} {unit}"


# --- Preparing a picture (CAT-123, CAT-124, CAT-126) -----------------------------------------


@dataclass(frozen=True)
class Prepared:
    """A picture ready to be stored, without metadata: the display picture and the thumbnail,
    the original with Spara original, and with a mask what is kept to change the background."""

    display: bytes
    thumb: bytes
    original: bytes | None
    width: int
    height: int
    """The display picture's size in pixels."""
    kind: str = "image/jpeg"
    """The display picture's and the thumbnail's: JPEG, or WebP for transparent (CAT-128)."""
    background: PictureBackground = PictureBackground.ORIGINAL
    source: bytes | None = None
    """The photo at display size, cut around the vehicle, when the display picture has another
    background than the original: what a change of background is made from."""
    mask: bytes | None = None
    """The vehicle's mask for the photo, PNG, when the background removal found it."""

    @property
    def size(self) -> int:
        """What the picture takes of the owner's storage (CAT-131)."""
        files = (self.display, self.thumb, self.original, self.source, self.mask)
        return sum(len(data) for data in files if data is not None)


def _jpeg(image: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _shown(picture: Image.Image) -> tuple[bytes, bytes, str]:
    """The display picture and its thumbnail as stored, and what they are: JPEG, or WebP when
    the picture is transparent, so its alpha channel is kept (CAT-128)."""
    thumb = fit(picture, _THUMB[0])
    if picture.mode == "RGBA":
        return _webp(picture, _DISPLAY[1]), _webp(thumb, _THUMB[1]), "image/webp"
    return _jpeg(picture, _DISPLAY[1]), _jpeg(thumb, _THUMB[1]), "image/jpeg"


def _webp(image: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    image.save(out, format="WEBP", quality=quality, alpha_quality=100, method=4)
    return out.getvalue()


def _in_srgb(image: Image.Image, icc: object) -> Image.Image:
    """The colours as the camera meant them, before its profile is dropped. An odd profile
    leaves the pixels as they are."""
    if not isinstance(icc, bytes) or not icc:
        return image
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        converted = ImageCms.profileToProfile(image, profile, _SRGB, outputMode="RGB")
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
        return image
    return converted if converted is not None else image


def _clean(source: Image.Image) -> Image.Image:
    """The pixels alone, upright and in RGB: a new picture, so no EXIF, ICC profile or
    comment of the file survives (CAT-124). Transparency becomes white."""
    icc = source.info.get("icc_profile")
    upright = ImageOps.exif_transpose(source)
    upright = upright if upright is not None else source
    if upright.mode in ("RGBA", "LA", "PA") or (
        upright.mode == "P" and "transparency" in upright.info
    ):
        rgba = upright.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.getchannel("A"))
    else:
        flat = upright.convert("RGB")
    flat = _in_srgb(flat, icc)
    clean = Image.new("RGB", flat.size)
    clean.paste(flat)
    return clean


def _read(data: bytes) -> Image.Image:
    """The upload's pixels, checked and clean (CAT-123, CAT-124)."""
    if len(data) > MAX_BYTES:
        raise too_large()
    try:
        with warnings.catch_warnings():
            # Pillow's own protection against decompression bombs: here its warning is an error.
            # Two uploads at once can at worst leave this filter on, which is what is wanted.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=_FORMATS) as source:
                # The size is in the header: checked before a single pixel is unpacked.
                if source.width * source.height > MAX_PIXELS:
                    raise _too_many_pixels()
                source.load()
                return _clean(source)
    except Refused:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise _too_many_pixels() from error
    except UnidentifiedImageError as error:
        raise wrong_kind() from error
    except Exception as error:  # a broken file can fail in many ways inside Pillow
        raise _unreadable() from error


def _mask(
    photo: Image.Image, background: PictureBackground, segmenter: Segmenter
) -> Image.Image | None:
    """The vehicle's mask in the photo. For the original background None when there is no
    model or no clear vehicle, and the photo is shown as it is; for the others refused."""
    if background is PictureBackground.ORIGINAL:
        if not segmenter.available():
            return None
        try:
            mask = _same_size(segmenter.segment(photo), photo)
        except Refused:
            return None  # nothing stands out, or the model failed: the photo as it is
        return mask if subject_box(mask) is not None else None
    if not segmenter.available():
        raise backgrounds_off()
    mask = _same_size(segmenter.segment(photo), photo)
    if subject_box(mask) is None:
        raise no_vehicle()
    return mask


def _same_size(mask: Image.Image, photo: Image.Image) -> Image.Image:
    mask = mask.convert("L")
    return mask if mask.size == photo.size else mask.resize(photo.size, Image.Resampling.LANCZOS)


def prepare(
    data: bytes,
    keep_original: bool = False,
    background: PictureBackground = PictureBackground.ORIGINAL,
    segmenter: Segmenter | None = None,
) -> Prepared:
    """Check the upload and make its files: the display picture and the thumbnail, and the
    original only with keep_original (Spara original, CAT-17). Refused with a Swedish message
    when it is too large, too many megapixels, or not a JPEG, PNG or WebP.

    With the background removal the photo is cut around the vehicle (CAT-129) and kept with
    its mask; the display picture is that photo for the original background, else the vehicle
    on the background chosen (CAT-128). Without it only the original background can be
    chosen, and the photo is shown as it is."""
    clean = _read(data)
    photo = fit(clean, _DISPLAY[0])
    original = _jpeg(clean, _ORIGINAL_QUALITY) if keep_original else None
    mask = _mask(photo, background, segmenter if segmenter is not None else NoSegmenter())
    if mask is None:
        display, thumb, kind = _shown(photo)
        return Prepared(display, thumb, original, photo.width, photo.height, kind)
    window = crop_box(mask, inside=True)
    assert window is not None  # _mask saw the vehicle
    kept, kept_mask = photo.crop(window), mask.crop(window)
    original_background = background is PictureBackground.ORIGINAL
    shown = kept if original_background else render(kept, kept_mask, background, limit=_DISPLAY[0])
    display, thumb, kind = _shown(shown)
    return Prepared(
        display,
        thumb,
        original,
        shown.width,
        shown.height,
        kind,
        background,
        source=None if original_background else _jpeg(kept, _DISPLAY[1]),
        mask=_png(kept_mask),
    )


# --- Where the files lie (CAT-130) -----------------------------------------------------------


class StoreFailed(Exception):
    """The store did not do what was asked. Never holds a key or a secret."""


class Store(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        """Store the file under the key. Raises StoreFailed."""
        ...

    def get(self, key: str) -> bytes:
        """The file, to make a new background from it (CAT-128). Raises StoreFailed."""
        ...

    def size(self, key: str) -> int:
        """What the file takes, in bytes, without fetching it. Raises StoreFailed."""
        ...

    def delete(self, key: str) -> None:
        """Delete the file; a file that is not there is no error. Raises StoreFailed."""
        ...

    def url(self, key: str, now: float | None = None) -> str:
        """A signed address to fetch the file, which expires (LINK_LIFETIME)."""
        ...


def signed_at(now: float) -> int:
    """When an address made now is signed: at the start of its half hour, so the same picture
    keeps the same address for half an hour, valid for at least half an hour more."""
    half = LINK_LIFETIME // 2
    return int(now) // half * half


def new_key(owner: UUID, kind: str = "image/jpeg") -> str:
    """A file's key: random, under the owner's id, never guessable, ending as the file is."""
    return f"{owner}/{uuid.uuid4().hex}.{EXTENSIONS[kind]}"


def kind_of(key: str) -> str:
    """What the file under a key is, by its ending."""
    ending = key.rsplit(".", 1)[-1]
    return next((kind for kind, ext in EXTENSIONS.items() if ext == ending), "image/jpeg")


class DiskStore:
    """The files in a folder of Catalog's own, fetched through Catalog at FILES_PATH with an
    HMAC-SHA256 signature and an expiry. For running locally and the tests. The signing key is
    made at every start, so the addresses from before a restart stop working, as they would
    when they expire: the app reads new ones."""

    def __init__(self, directory: Path, signing_key: bytes) -> None:
        self.directory = directory
        self._signing_key = signing_key

    def __repr__(self) -> str:
        return f"DiskStore({str(self.directory)!r})"

    def path(self, key: str) -> Path | None:
        """The file for a key Catalog made, never anything else."""
        return self.directory / key if _KEY.fullmatch(key) else None

    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        target = self.path(key)
        if target is None:
            raise StoreFailed("Ingen giltig nyckel.")
        partial = target.with_name(f".{target.name}.part")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(data)
            os.replace(partial, target)
        except OSError as error:
            partial.unlink(missing_ok=True)
            LOGGER.warning("Bilden kunde inte sparas på disken: %s", type(error).__name__)
            raise StoreFailed("Bilden kunde inte sparas på disken.") from error

    def get(self, key: str) -> bytes:
        target = self.path(key)
        if target is None:
            raise StoreFailed("Ingen giltig nyckel.")
        try:
            return target.read_bytes()
        except OSError as error:
            LOGGER.warning("Bilden kunde inte läsas från disken: %s", type(error).__name__)
            raise StoreFailed("Bilden kunde inte läsas från disken.") from error

    def size(self, key: str) -> int:
        target = self.path(key)
        if target is None:
            raise StoreFailed("Ingen giltig nyckel.")
        try:
            return target.stat().st_size
        except OSError as error:
            LOGGER.warning("Bilden finns inte på disken: %s", type(error).__name__)
            raise StoreFailed("Bilden finns inte på disken.") from error

    def delete(self, key: str) -> None:
        target = self.path(key)
        if target is None:
            return  # not a file Catalog made: nothing to delete
        try:
            target.unlink(missing_ok=True)
        except OSError as error:
            LOGGER.warning("Bilden kunde inte tas bort från disken: %s", type(error).__name__)
            raise StoreFailed("Bilden kunde inte tas bort från disken.") from error

    def _signature(self, key: str, expires: int) -> str:
        message = f"{key}\n{expires}".encode()
        return hmac.new(self._signing_key, message, hashlib.sha256).hexdigest()

    def url(self, key: str, now: float | None = None) -> str:
        expires = signed_at(time.time() if now is None else now) + LINK_LIFETIME
        return f"{FILES_PATH}{key}?expires={expires}&sig={self._signature(key, expires)}"

    def check(self, key: str, expires: str, signature: str, now: float | None = None) -> int | None:
        """The address's expiry, when the signature is Catalog's and it has not expired; else
        None. The signature is compared in constant time."""
        if self.path(key) is None or not expires.isdigit() or len(expires) > 12:
            return None
        when = int(expires)
        expected = self._signature(key, when).encode()
        if not hmac.compare_digest(expected, signature.encode()):
            return None
        if when < (time.time() if now is None else now):
            return None
        return when


class _PresignedAt(S3SigV4QueryAuth):  # type: ignore[misc]
    """botocore's presigned address, signed at a given time rather than now (signed_at)."""

    def __init__(self, credentials: Credentials, region: str, at: datetime) -> None:
        super().__init__(credentials, "s3", region, expires=LINK_LIFETIME)
        self._at = at

    def _modify_request_before_signing(self, request: AWSRequest) -> None:
        request.context["timestamp"] = self._at.strftime("%Y%m%dT%H%M%SZ")
        super()._modify_request_before_signing(request)


class S3Store:
    """Object Storage, S3 compatible, such as Scaleway's in any of its regions (CAT-130). The
    bucket is private. PUT, GET, HEAD and DELETE are signed with AWS's SigV4 (botocore), sent with
    httpx, as id/meter.py does; the browser fetches with a presigned address. The addresses are
    path-style, so the browser fetches from the endpoint's own origin, which is what the
    Content-Security-Policy allows. The keys are never written to the log."""

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        region: str,
        access_key: str,
        secret_key: str,
        http: httpx.Client,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.region = region
        self._credentials = Credentials(access_key, secret_key)
        self.http = http

    def __repr__(self) -> str:
        return f"S3Store({self.endpoint!r}, bucket={self.bucket!r}, region={self.region!r})"

    def _address(self, key: str) -> str:
        return f"{self.endpoint}/{self.bucket}/{quote(key, safe='/')}"

    def _send(
        self, method: str, key: str, data: bytes = b"", headers: dict[str, str] | None = None
    ) -> httpx.Response:
        signed = AWSRequest(method=method, url=self._address(key), data=data, headers=headers)
        S3SigV4Auth(self._credentials, "s3", self.region).add_auth(signed)
        try:
            return self.http.request(
                method, self._address(key), content=data, headers=dict(signed.headers.items())
            )
        except httpx.HTTPError as error:
            LOGGER.warning("Object Storage svarar inte: %s", type(error).__name__)
            raise StoreFailed("Object Storage svarar inte.") from error

    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        # A key is never reused, so the browser may keep the file as long as it likes.
        headers = {"Content-Type": content_type, "Cache-Control": "private, max-age=86400"}
        answer = self._send("PUT", key, data, headers)
        if answer.status_code != 200:
            LOGGER.warning("Object Storage svarade %s på en uppladdning.", answer.status_code)
            raise StoreFailed("Object Storage tog inte emot bilden.")

    def get(self, key: str) -> bytes:
        answer = self._send("GET", key)
        if answer.status_code != 200:
            LOGGER.warning("Object Storage svarade %s på en hämtning.", answer.status_code)
            raise StoreFailed("Object Storage lämnade inte ut bilden.")
        return answer.content

    def size(self, key: str) -> int:
        answer = self._send("HEAD", key)
        length = answer.headers.get("content-length", "")
        if answer.status_code != 200 or not length.isdigit():
            LOGGER.warning("Object Storage svarade %s om en bilds storlek.", answer.status_code)
            raise StoreFailed("Object Storage visste inte bildens storlek.")
        return int(length)

    def delete(self, key: str) -> None:
        answer = self._send("DELETE", key)
        if answer.status_code not in (200, 204, 404):
            LOGGER.warning("Object Storage svarade %s på en borttagning.", answer.status_code)
            raise StoreFailed("Object Storage tog inte bort bilden.")

    def url(self, key: str, now: float | None = None) -> str:
        at = datetime.fromtimestamp(signed_at(time.time() if now is None else now), UTC)
        request = AWSRequest(method="GET", url=self._address(key))
        _PresignedAt(self._credentials, self.region, at).add_auth(request)
        address: str = request.url
        return address


def store_for(settings: Settings, http: httpx.Client | None = None) -> Store:
    """Object Storage when it is set, else the disk with a signing key made now."""
    s3 = settings.pictures_s3
    if s3 is not None:
        return S3Store(
            s3.endpoint,
            s3.bucket,
            s3.region,
            s3.access_key,
            s3.secret_key,
            http if http is not None else httpx.Client(timeout=30.0),
        )
    return DiskStore(settings.pictures_dir, secrets.token_bytes(32))


# --- The pictures in the database (CAT-125, CAT-131, CAT-133) ----------------------------------


@dataclass(frozen=True)
class PictureLimits:
    """The free level (CAT-17, TOKEN-29). The tests give tiny ones."""

    person: int = PERSON_LIMIT
    club: int = CLUB_LIMIT
    per_vehicle: int = PER_VEHICLE


@dataclass(frozen=True)
class _File:
    """A file to store: its new key, its content and what it is."""

    key: str
    data: bytes
    kind: str


def _file(owner: UUID, data: bytes, kind: str = "image/jpeg") -> _File:
    return _File(new_key(owner, kind), data, kind)


def _opened(data: bytes, mode: str) -> Image.Image:
    """A file Catalog stored itself: the kept photo (JPEG) or its mask (PNG)."""
    try:
        with Image.open(io.BytesIO(data), formats=("JPEG", "PNG")) as image:
            return image.convert(mode)
    except Exception as error:
        LOGGER.warning("En sparad bild kunde inte läsas: %s", type(error).__name__)
        raise _store_down() from error


class Pictures:
    def __init__(
        self,
        db: Database,
        store: Store,
        limits: PictureLimits | None = None,
        segmenter: Segmenter | None = None,
    ) -> None:
        self.db = db
        self.store = store
        self.limits = limits if limits is not None else PictureLimits()
        self.segmenter: Segmenter = segmenter if segmenter is not None else NoSegmenter()

    def _picture(self, row: DictRow, now: float) -> Picture:
        original = row["original_key"]
        return Picture(
            id=row["id"],
            main=row["is_main"],
            position=row["position"],
            width=row["width"],
            height=row["height"],
            bytes=row["bytes"],
            display_url=self.store.url(row["display_key"], now),
            thumb_url=self.store.url(row["thumb_key"], now),
            original_url=self.store.url(original, now) if original else None,
            background=PictureBackground(row["background"]),
        )

    def _pictures(self, conn: Connection[DictRow], vehicle: UUID) -> list[Picture]:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM picture WHERE vehicle_id = %s "
            "ORDER BY position, created_at, id",
            (vehicle,),
        ).fetchall()
        now = time.time()
        return [self._picture(row, now) for row in rows]

    @staticmethod
    def _vehicle(conn: Connection[DictRow], owner: UUID, vehicle: UUID) -> None:
        found = conn.execute(
            "SELECT 1 FROM vehicle WHERE id = %s AND owner_id = %s", (vehicle, owner)
        ).fetchone()
        if found is None:
            raise not_found()

    def _limit(self, club: bool) -> int:
        return self.limits.club if club else self.limits.person

    def _full(self, club: bool) -> Refused:
        whose = "Klubbens fria lagring" if club else "Den fria lagringen"
        return Refused(
            422,
            ProblemCode.STORAGE_FULL,
            f"{whose} på {_size(self._limit(club))} är full. "
            "Ta bort bilder för att få plats med fler.",
        )

    def _check(
        self, conn: Connection[DictRow], owner: UUID, vehicle: UUID, size: int, club: bool
    ) -> None:
        """The vehicle is the owner's, has room for one more, and so has the storage."""
        self._vehicle(conn, owner, vehicle)
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE vehicle_id = %s) AS here, "
            "coalesce(sum(bytes), 0) AS used FROM picture WHERE owner_id = %s",
            (vehicle, owner),
        ).fetchone()
        assert row is not None
        if row["here"] >= self.limits.per_vehicle:
            raise Refused(
                422,
                ProblemCode.TOO_MANY_PICTURES,
                f"Ett fordon kan ha högst {self.limits.per_vehicle} bilder. Ta bort en först.",
            )
        if row["used"] + size > self._limit(club):
            raise self._full(club)

    def _room(
        self, conn: Connection[DictRow], owner: UUID, before: int, after: int, club: bool
    ) -> None:
        """A picture that grows from `before` to `after` bytes needs room for it in the
        storage. One that does not grow is always possible, also over the limit."""
        if after <= before:
            return
        row = conn.execute(
            "SELECT coalesce(sum(bytes), 0) AS used FROM picture WHERE owner_id = %s", (owner,)
        ).fetchone()
        assert row is not None
        if row["used"] - before + after > self._limit(club):
            raise self._full(club)

    def of_vehicle(self, owner: UUID, vehicle: UUID) -> list[Picture]:
        """The vehicle's pictures in order. To look is enough (CAT-46)."""
        with self.db.transaction() as conn:
            self._vehicle(conn, owner, vehicle)
            return self._pictures(conn, vehicle)

    def _keep(
        self,
        owner: UUID,
        files: list[_File],
        save: Callable[[Connection[DictRow]], DictRow],
    ) -> DictRow:
        """Store new files, then save the row that holds them under the owner's lock (CAT-40).
        The keys are marked in picture_trash before the files are stored, and the marks go in
        the transaction that saves: whatever fails, even the process, leaves no file behind."""
        keys = [file.key for file in files]
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO picture_trash (key, due_at) "
                "SELECT k, now() + %s FROM unnest(%s::text[]) k",
                (_UPLOAD_GRACE, keys),
            )
        try:
            for file in files:
                self.store.put(file.key, file.data, file.kind)
            with self.db.owner_transaction(owner) as conn:
                row = save(conn)
                conn.execute("DELETE FROM picture_trash WHERE key = ANY(%s)", (keys,))
        except StoreFailed as error:
            self._discard(keys)
            raise _store_down() from error
        except BaseException:
            self._discard(keys)
            raise
        return row

    def add(
        self,
        owner: UUID,
        vehicle: UUID,
        data: bytes,
        *,
        keep_original: bool,
        uploaded_by: UUID,
        club: bool,
        background: PictureBackground = PictureBackground.ORIGINAL,
    ) -> Picture:
        """A new picture of the owner's vehicle, stored with the owner within the owner's limit
        (CAT-131, CAT-133), on the background chosen (CAT-128). The first picture is the main
        one (CAT-125)."""
        prepared = prepare(data, keep_original, background, self.segmenter)
        # A first look without a lock, so a refused upload stores nothing.
        with self.db.transaction() as conn:
            self._check(conn, owner, vehicle, prepared.size, club)
        display = _file(owner, prepared.display, prepared.kind)
        thumb = _file(owner, prepared.thumb, prepared.kind)
        original = _file(owner, prepared.original) if prepared.original is not None else None
        source = _file(owner, prepared.source) if prepared.source is not None else None
        mask = _file(owner, prepared.mask, "image/png") if prepared.mask is not None else None
        files = [f for f in (display, thumb, original, source, mask) if f is not None]

        def save(conn: Connection[DictRow]) -> DictRow:
            self._check(conn, owner, vehicle, prepared.size, club)
            row = conn.execute(
                "INSERT INTO picture (id, vehicle_id, owner_id, position, is_main, width, "
                "height, display_key, thumb_key, original_key, background, source_key, "
                "mask_key, bytes, uploaded_by) "
                "SELECT %(id)s, %(vehicle)s, %(owner)s, coalesce(max(position) + 1, 0), "
                "NOT coalesce(bool_or(is_main), false), %(width)s, %(height)s, %(display)s, "
                "%(thumb)s, %(original)s, %(background)s, %(source)s, %(mask)s, %(bytes)s, "
                f"%(by)s FROM picture WHERE vehicle_id = %(vehicle)s RETURNING {_COLUMNS}",
                {
                    "id": uuid.uuid4(),
                    "vehicle": vehicle,
                    "owner": owner,
                    "width": prepared.width,
                    "height": prepared.height,
                    "display": display.key,
                    "thumb": thumb.key,
                    "original": original.key if original else None,
                    "background": prepared.background.value,
                    "source": source.key if source else None,
                    "mask": mask.key if mask else None,
                    "bytes": prepared.size,
                    "by": uploaded_by,
                },
            ).fetchone()
            assert row is not None
            return row

        return self._picture(self._keep(owner, files, save), time.time())

    def change_background(
        self,
        owner: UUID,
        vehicle: UUID,
        picture: UUID,
        background: PictureBackground,
        *,
        club: bool,
    ) -> Picture:
        """The picture on another background, made from the photo and the mask kept at the
        upload, without a new upload (CAT-128, CAT-129). The new files are stored first, then
        the keys are swapped in one transaction under the owner's lock, and the old ones go to
        picture_trash by the database's trigger. Refused with 409 when the picture changed in
        the meantime, and its new files are deleted again."""
        with self.db.transaction() as conn:
            self._vehicle(conn, owner, vehicle)
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM picture WHERE id = %s AND vehicle_id = %s",
                (picture, vehicle),
            ).fetchone()
        if row is None:
            raise _no_picture()
        if row["background"] == background.value:
            return self._picture(row, time.time())
        if background is not PictureBackground.ORIGINAL and not self.segmenter.available():
            raise backgrounds_off()
        # The kept photo; with the original background the display picture is the photo.
        photo_key = cast(str, row["source_key"] or row["display_key"])
        try:
            photo_data = self.store.get(photo_key)
            mask_data = self.store.get(row["mask_key"]) if row["mask_key"] else None
            original = self.store.size(row["original_key"]) if row["original_key"] else 0
        except StoreFailed as error:
            raise _store_down() from error
        photo = _opened(photo_data, "RGB")
        new: list[_File] = []
        made_mask: _File | None = None
        files: tuple[bytes | None, ...]
        if background is PictureBackground.ORIGINAL:
            # The kept photo is the display picture again; only its thumbnail is new.
            thumb = _file(owner, _jpeg(fit(photo, _THUMB[0]), _THUMB[1]))
            new.append(thumb)
            keys = {"display": photo_key, "thumb": thumb.key, "source": None}
            shown_size = photo.size
            files = (photo_data, mask_data, thumb.data)
        else:
            if mask_data is None:  # shown as it was uploaded: the mask is made now
                mask = _same_size(self.segmenter.segment(photo), photo)
                mask_data = _png(mask)
                made_mask = _file(owner, mask_data, "image/png")
                new.append(made_mask)
            else:
                mask = _same_size(_opened(mask_data, "L"), photo)
            shown = render(photo, mask, background, limit=_DISPLAY[0])
            display_data, thumb_data, kind = _shown(shown)
            display, thumb = _file(owner, display_data, kind), _file(owner, thumb_data, kind)
            new += [display, thumb]
            keys = {"display": display.key, "thumb": thumb.key, "source": photo_key}
            shown_size = shown.size
            files = (photo_data, mask_data, display.data, thumb.data)
        mask_key = row["mask_key"] or (made_mask.key if made_mask is not None else None)
        size = original + sum(len(data) for data in files if data is not None)
        with self.db.transaction() as conn:
            self._room(conn, owner, row["bytes"], size, club)

        def save(conn: Connection[DictRow]) -> DictRow:
            self._room(conn, owner, row["bytes"], size, club)
            changed = conn.execute(
                "UPDATE picture SET background = %(background)s, display_key = %(display)s, "
                "thumb_key = %(thumb)s, source_key = %(source)s, mask_key = %(mask)s, "
                "width = %(width)s, height = %(height)s, bytes = %(bytes)s "
                "WHERE id = %(id)s AND background = %(was)s AND display_key = %(was_display)s "
                "AND thumb_key = %(was_thumb)s "
                "AND source_key IS NOT DISTINCT FROM %(was_source)s "
                "AND mask_key IS NOT DISTINCT FROM %(was_mask)s "
                f"RETURNING {_COLUMNS}",
                {
                    "background": background.value,
                    **keys,
                    "mask": mask_key,
                    "width": shown_size[0],
                    "height": shown_size[1],
                    "bytes": size,
                    "id": picture,
                    "was": row["background"],
                    "was_display": row["display_key"],
                    "was_thumb": row["thumb_key"],
                    "was_source": row["source_key"],
                    "was_mask": row["mask_key"],
                },
            ).fetchone()
            if changed is None:
                raise _picture_changed()
            return changed

        return self._picture(self._keep(owner, new, save), time.time())

    def _discard(self, keys: list[str]) -> None:
        """New files that were never saved, from an upload or a change of background that
        failed: they go now. What cannot go now stays marked in picture_trash, and the sweep
        deletes it when it is due."""
        gone: list[str] = []
        for key in keys:
            try:
                self.store.delete(key)
            except StoreFailed:
                continue
            gone.append(key)
        if not gone:
            return
        try:
            with self.db.transaction() as conn:
                conn.execute("DELETE FROM picture_trash WHERE key = ANY(%s)", (gone,))
        except Exception as error:  # the marks stay; the sweep finds nothing to delete
            LOGGER.warning("Bildens markeringar finns kvar: %s", type(error).__name__)

    def set_main(self, owner: UUID, vehicle: UUID, picture: UUID) -> list[Picture]:
        """Make the picture the vehicle's main one (CAT-125)."""
        with self.db.owner_transaction(owner) as conn:
            self._vehicle(conn, owner, vehicle)
            found = conn.execute(
                "SELECT is_main FROM picture WHERE id = %s AND vehicle_id = %s",
                (picture, vehicle),
            ).fetchone()
            if found is None:
                raise _no_picture()
            if not found["is_main"]:
                # Two steps: the database never sees two main pictures at once.
                conn.execute(
                    "UPDATE picture SET is_main = false WHERE vehicle_id = %s AND is_main",
                    (vehicle,),
                )
                conn.execute("UPDATE picture SET is_main = true WHERE id = %s", (picture,))
            return self._pictures(conn, vehicle)

    def remove(self, owner: UUID, vehicle: UUID, picture: UUID) -> None:
        """Remove the picture; its files go with the next sweep. When it was the main picture,
        the first of the rest by position becomes the main one (CAT-125)."""
        with self.db.owner_transaction(owner) as conn:
            self._vehicle(conn, owner, vehicle)
            gone = conn.execute(
                "DELETE FROM picture WHERE id = %s AND vehicle_id = %s RETURNING is_main",
                (picture, vehicle),
            ).fetchone()
            if gone is None:
                raise _no_picture()
            if gone["is_main"]:
                conn.execute(
                    "UPDATE picture SET is_main = true WHERE id = (SELECT id FROM picture "
                    "WHERE vehicle_id = %s ORDER BY position, created_at, id LIMIT 1)",
                    (vehicle,),
                )

    def usage(self, owner: UUID, *, club: bool) -> StorageUse:
        """What the owner's pictures take, drafts' included, and the free level (CAT-131)."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT coalesce(sum(bytes), 0) AS used, count(*) AS pictures FROM picture "
                "WHERE owner_id = %s",
                (owner,),
            ).fetchone()
        assert row is not None
        return StorageUse(
            used=row["used"],
            limit=self._limit(club),
            club=club,
            pictures=row["pictures"],
            backgrounds=self.segmenter.available(),
        )

    def main_links(
        self, conn: Connection[DictRow], vehicles: list[UUID]
    ) -> dict[UUID, PictureLinks]:
        """The main picture's addresses for each of the vehicles, in one query."""
        if not vehicles:
            return {}
        rows = conn.execute(
            "SELECT vehicle_id, display_key, thumb_key FROM picture "
            "WHERE vehicle_id = ANY(%s) AND is_main",
            (vehicles,),
        ).fetchall()
        now = time.time()
        return {
            row["vehicle_id"]: PictureLinks(
                thumb_url=self.store.url(row["thumb_key"], now),
                display_url=self.store.url(row["display_key"], now),
            )
            for row in rows
        }

    def sweep(self) -> int:
        """Delete the files that are due in picture_trash: removed pictures', and uploads' that
        failed or stopped halfway. How many went. A store that fails leaves the rest for the
        next sweep."""
        deleted = 0
        while True:
            with self.db.transaction() as conn:
                due = [
                    str(row["key"])
                    for row in conn.execute(
                        "SELECT key FROM picture_trash WHERE due_at <= now() "
                        "ORDER BY due_at LIMIT %s",
                        (_SWEEP_BATCH,),
                    ).fetchall()
                ]
            if not due:
                return deleted
            done: list[str] = []
            for key in due:
                try:
                    self.store.delete(key)
                except StoreFailed:
                    break
                done.append(key)
            if done:
                with self.db.transaction() as conn:
                    conn.execute("DELETE FROM picture_trash WHERE key = ANY(%s)", (done,))
            deleted += len(done)
            if len(done) < len(due):
                LOGGER.warning("%d bildfiler väntar på att tas bort.", len(due) - len(done))
                return deleted
