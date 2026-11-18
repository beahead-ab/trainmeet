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
storage. With the original background the display picture is itself the kept photo. The
background removal itself is free (TOKEN-17).

Over the free level the storage is paid in tokens from the owner's balance in TrainMeet ID, 20
tokens per started GB and month (CAT-132, catalog/storage.py). A change that grows the storage
past what is paid this month pays the next GB first, outside any transaction, before its files
are stored; the decisive check is made again when the picture is saved under the owner's lock,
and what another upload took meanwhile is paid then. So two uploads never both get in unpaid,
and the same GB is never paid twice. When it cannot be paid, nothing is stored, the pictures
that are there stay, and removing them always works. A daily round (charge_round) charges the
owners who are still over the free level when a new month begins. Without ID's API, Catalog
refuses over the free level as before.
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
from collections.abc import Callable, Sequence
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
from catalog.storage import GB, PRICE_PER_GB, NotPaid, Payer, Why, storage_key
from contracts.catalog import (
    Picture,
    PictureBackground,
    PictureLinks,
    ProblemCode,
    StorageUse,
)
from contracts.tokens import TokenOwner, TokenOwnerKind

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
_SAVE_ATTEMPTS: Final = 3
"""How many times a save may pay what another upload took meanwhile before it gives up."""
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


def _storage_changed() -> Refused:
    return Refused(
        409, ProblemCode.CHANGED, "Lagringen ändrades under tiden. Försök igen om en stund."
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
    """The free level (CAT-17, TOKEN-29), and what is paid over it at a time: a started GB
    (CAT-132). The tests give tiny ones."""

    person: int = PERSON_LIMIT
    club: int = CLUB_LIMIT
    per_vehicle: int = PER_VEHICLE
    block: int = GB


@dataclass(frozen=True)
class Room:
    """The owner's storage for a change, in the month it is made (CAT-131, CAT-132)."""

    month: str
    """The month in Swedish time, as ID counts it: YYYY-MM."""
    used: int
    """Bytes stored now."""
    grow: int
    """Bytes the change adds; zero or less for one that does not grow."""
    paid: int
    """Started GB over the free level that are paid this month."""
    needed: int
    """Started GB over the free level after the change."""
    now_needed: int
    """Started GB over the free level for what is stored now."""

    @property
    def short(self) -> bool:
        """The change grows the storage past the free level and what is paid this month."""
        return self.grow > 0 and self.needed > self.paid


class _Unpaid(Exception):
    """A save under the owner's lock found more to pay than is paid: another upload took it
    meanwhile, or a new month began. It is paid outside the transaction, and the save is tried
    again."""

    def __init__(self, room: Room) -> None:
        super().__init__("unpaid")
        self.room = room


@dataclass(frozen=True)
class _File:
    """A file to store: its new key, its content and what it is."""

    key: str
    data: bytes
    kind: str


def _file(owner: UUID, data: bytes, kind: str = "image/jpeg") -> _File:
    return _File(new_key(owner, kind), data, kind)


@dataclass(frozen=True)
class Kept:
    """A draft's picture in a batch (#52 del b), stored before it is a vehicle's: its files'
    keys, the display picture's size in pixels, and what the two take."""

    display_key: str
    thumb_key: str
    width: int
    height: int
    bytes: int


def _now() -> datetime:
    return datetime.now(UTC)


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
        payer: Payer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """payer draws the storage over the free level from the owner's balance in ID
        (CAT-132); without it Catalog refuses over the free level. clock says which month it
        is; the tests move it."""
        self.db = db
        self.store = store
        self.limits = limits if limits is not None else PictureLimits()
        self.segmenter: Segmenter = segmenter if segmenter is not None else NoSegmenter()
        self.payer = payer
        self.clock: Callable[[], datetime] = clock if clock is not None else _now

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

    def _not_paid(self, why: Why, club: bool) -> Refused:
        """Why the storage over the free level could not be paid (CAT-132, TK15)."""
        if why == "account":
            return self._full(club)
        if why == "cap":
            return Refused(
                429,
                ProblemCode.TOO_MANY,
                "Taket för tokens per dygn är nått, så mer lagring kan inte betalas i dag. "
                "Försök i morgon, eller ta bort bilder.",
            )
        whose = "Klubbens fria lagring" if club else "Den fria lagringen"
        balance = "klubbens saldo" if club else "saldot"
        return Refused(
            402,
            ProblemCode.NO_TOKENS,
            f"{whose} på {_size(self._limit(club))} är full, och {balance} räcker inte till "
            f"mer: {PRICE_PER_GB} tokens per påbörjad GB och månad. Köp tokens i TrainMeet ID, "
            "eller ta bort bilder.",
        )

    def _blocks(self, used: int, club: bool) -> int:
        """Started blocks, GB, over the free level (CAT-132)."""
        over = used - self._limit(club)
        return -(-over // self.limits.block) if over > 0 else 0

    def _month(self, conn: Connection[DictRow]) -> str:
        """The month in Swedish time, from the database, which always has the time zones, as
        ID counts its months (id/tokens.py)."""
        row = conn.execute(
            "SELECT to_char(%s::timestamptz AT TIME ZONE 'Europe/Stockholm', 'YYYY-MM') AS m",
            (self.clock(),),
        ).fetchone()
        assert row is not None
        return str(row["m"])

    def _space(self, conn: Connection[DictRow], owner: UUID, grow: int, club: bool) -> Room:
        """What the owner's storage needs for `grow` more bytes this month (CAT-131)."""
        row = conn.execute(
            "SELECT coalesce(sum(bytes), 0) AS used FROM picture WHERE owner_id = %s", (owner,)
        ).fetchone()
        assert row is not None
        used = int(row["used"])
        month = self._month(conn)
        charge = conn.execute(
            "SELECT blocks FROM storage_charge WHERE owner_id = %s AND month = %s", (owner, month)
        ).fetchone()
        return Room(
            month=month,
            used=used,
            grow=grow,
            paid=int(charge["blocks"]) if charge is not None else 0,
            needed=self._blocks(used + grow, club),
            now_needed=self._blocks(used, club),
        )

    def _enough(self, room: Room, club: bool) -> bool:
        """Does the change fit within the free level and what is paid this month? One that does
        not grow always does, also over the limit. Without paid storage, refused when it does
        not fit."""
        if not room.short:
            return True
        if self.payer is None:
            raise self._full(club)
        return False

    def _check(
        self, conn: Connection[DictRow], owner: UUID, vehicle: UUID, size: int, club: bool
    ) -> Room:
        """The vehicle is the owner's and has room for one more; what the storage needs for
        it."""
        self._vehicle(conn, owner, vehicle)
        row = conn.execute(
            "SELECT count(*) AS here FROM picture WHERE vehicle_id = %s", (vehicle,)
        ).fetchone()
        assert row is not None
        if row["here"] >= self.limits.per_vehicle:
            raise Refused(
                422,
                ProblemCode.TOO_MANY_PICTURES,
                f"Ett fordon kan ha högst {self.limits.per_vehicle} bilder. Ta bort en först.",
            )
        return self._space(conn, owner, size, club)

    def _pay_first(self, owner: UUID, club: bool, room: Room) -> None:
        """What a change needs this month is paid before anything is stored, so a change that
        cannot be paid stores nothing (CAT-132)."""
        if not self._enough(room, club):
            self._settle(owner, club, room)

    def _settle(self, owner: UUID, club: bool, room: Room) -> int:
        """Pay the month's started GB that the room needs, one by one in order, each with its
        own key in ID, outside any transaction (catalog/storage.py). What was paid is recorded,
        also when ID says no halfway. Refused with no_tokens, too_many or storage_full when it
        cannot be paid, and unavailable when ID does not answer. How many GB were paid now."""
        payer = self.payer
        assert payer is not None
        kind = TokenOwnerKind.CLUB if club else TokenOwnerKind.PERSON
        account = TokenOwner(kind=kind, id=owner)
        paid, why, done = room.paid, None, False
        try:
            for block in range(room.paid + 1, room.needed + 1):
                what = (
                    f"Bildlagring i Catalog {room.month}, påbörjad GB {block} över den fria nivån"
                )
                payer.pay(account, storage_key(owner, room.month, block), PRICE_PER_GB, what)
                paid = block
            done = True
        except NotPaid as refused:
            why = refused.why
        finally:
            # Paid: the month is no longer unpaid. Short of tokens: unpaid if what is stored
            # now is not paid, whatever the change wanted. Otherwise as it was.
            unpaid = (
                False if done else (paid < room.now_needed if why in ("balance", "cap") else None)
            )
            if paid > room.paid or unpaid is not None:
                self._record(owner, room.month, paid, club, unpaid)
        if why is not None:
            raise self._not_paid(why, club)
        return paid - room.paid

    def _record(self, owner: UUID, month: str, paid: int, club: bool, unpaid: bool | None) -> None:
        """What is paid this month, under the owner's lock (CAT-40); it never goes down.
        unpaid None leaves it as it was."""
        with self.db.owner_transaction(owner) as conn:
            conn.execute(
                "INSERT INTO storage_charge (owner_id, month, blocks, club, unpaid) "
                "VALUES (%(owner)s, %(month)s, %(blocks)s, %(club)s, coalesce(%(unpaid)s, false)) "
                "ON CONFLICT (owner_id, month) DO UPDATE SET "
                "blocks = greatest(storage_charge.blocks, excluded.blocks), club = excluded.club, "
                "unpaid = coalesce(%(unpaid)s, storage_charge.unpaid), changed_at = now()",
                {"owner": owner, "month": month, "blocks": paid, "club": club, "unpaid": unpaid},
            )

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
        club: bool,
    ) -> DictRow:
        """Store new files, then save the row that holds them under the owner's lock (CAT-40).
        The keys are marked in picture_trash before the files are stored, and the marks go in
        the transaction that saves: whatever fails, even the process, leaves no file behind.
        A save that finds more storage to pay (_Unpaid) pays it outside the transaction and is
        tried again; when it cannot be paid, the files go."""
        keys = [file.key for file in files]
        self._mark(keys)
        try:
            for file in files:
                self.store.put(file.key, file.data, file.kind)
            attempt = 1
            while True:
                try:
                    with self.db.owner_transaction(owner) as conn:
                        row = save(conn)
                        conn.execute("DELETE FROM picture_trash WHERE key = ANY(%s)", (keys,))
                    break
                except _Unpaid as unpaid:
                    if attempt == _SAVE_ATTEMPTS:
                        raise _storage_changed() from None
                    attempt += 1
                    self._settle(owner, club, unpaid.room)
        except StoreFailed as error:
            self._discard(keys)
            raise _store_down() from error
        except BaseException:
            self._discard(keys)
            raise
        return row

    def _mark(self, keys: list[str]) -> None:
        """New files' keys, marked in picture_trash before the files are stored, due an hour
        later: the transaction that saves them takes the marks away."""
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO picture_trash (key, due_at) "
                "SELECT k, now() + %s FROM unnest(%s::text[]) k",
                (_UPLOAD_GRACE, keys),
            )

    def keep_drafts[T](
        self,
        owner: UUID,
        prepared: Sequence[Prepared],
        save: Callable[[Connection[DictRow], list[Kept]], tuple[T, set[str]]],
    ) -> T:
        """A batch's photos (#52 del b): store each one's display picture and thumbnail, then
        save what holds them under the owner's lock (CAT-40). save gives its result and the keys
        it holds now; the others, of a photo that another request saved first, are deleted
        again. As for an upload, the keys are marked before the files are stored, so whatever
        fails leaves no file behind. The drafts' files count in the storage only when they are
        a vehicle's (adopt())."""
        files: list[_File] = []
        kept: list[Kept] = []
        for picture in prepared:
            display = _file(owner, picture.display, picture.kind)
            thumb = _file(owner, picture.thumb, picture.kind)
            files += [display, thumb]
            size = len(picture.display) + len(picture.thumb)
            kept.append(Kept(display.key, thumb.key, picture.width, picture.height, size))
        keys = [file.key for file in files]
        self._mark(keys)
        try:
            for file in files:
                self.store.put(file.key, file.data, file.kind)
            with self.db.owner_transaction(owner) as conn:
                result, held = save(conn, kept)
                conn.execute("DELETE FROM picture_trash WHERE key = ANY(%s)", (sorted(held),))
        except StoreFailed as error:
            self._discard(keys)
            raise _store_down() from error
        except BaseException:
            self._discard(keys)
            raise
        self._discard([key for key in keys if key not in held])
        return result

    def links(self, display_key: str, thumb_key: str) -> PictureLinks:
        """A draft's picture's signed addresses (CAT-130)."""
        now = time.time()
        return PictureLinks(
            thumb_url=self.store.url(thumb_key, now), display_url=self.store.url(display_key, now)
        )

    def fetch(self, key: str) -> bytes:
        """A file Catalog stored, such as a draft's picture to be read by the AI."""
        try:
            return self.store.get(key)
        except StoreFailed as error:
            raise _store_down() from error

    def save_within[T](
        self, owner: UUID, grow: int, club: bool, save: Callable[[Connection[DictRow]], T]
    ) -> T:
        """Run save under the owner's lock (CAT-40) when the owner's storage has room for grow
        more bytes (CAT-131), as Godkänn alla needs for its pictures. What that needs over the
        free level this month is paid first, outside any transaction, and what another change
        took meanwhile is paid before save is tried again (CAT-132)."""
        with self.db.transaction() as conn:
            room = self._space(conn, owner, grow, club)
        self._pay_first(owner, club, room)
        attempt = 1
        while True:
            try:
                with self.db.owner_transaction(owner) as conn:
                    room = self._space(conn, owner, grow, club)
                    if not self._enough(room, club):
                        raise _Unpaid(room)
                    return save(conn)
            except _Unpaid as unpaid:
                if attempt == _SAVE_ATTEMPTS:
                    raise _storage_changed() from None
                attempt += 1
                self._settle(owner, club, unpaid.room)

    @staticmethod
    def adopt(
        conn: Connection[DictRow], owner: UUID, vehicle: UUID, kept: Kept, uploaded_by: UUID
    ) -> None:
        """A draft's picture becomes the new vehicle's first and main picture (CAT-125), in the
        caller's transaction under the owner's lock. From now on it counts in the owner's
        storage (CAT-131), and goes with the vehicle."""
        conn.execute(
            "INSERT INTO picture (id, vehicle_id, owner_id, position, is_main, width, height, "
            "display_key, thumb_key, bytes, uploaded_by) "
            "VALUES (%s, %s, %s, 0, true, %s, %s, %s, %s, %s, %s)",
            (
                uuid.uuid4(),
                vehicle,
                owner,
                kept.width,
                kept.height,
                kept.display_key,
                kept.thumb_key,
                kept.bytes,
                uploaded_by,
            ),
        )

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
        # A first look without a lock, so a refused upload stores nothing. What it needs this
        # month over the free level is paid now, before anything is stored (CAT-132).
        with self.db.transaction() as conn:
            room = self._check(conn, owner, vehicle, prepared.size, club)
        self._pay_first(owner, club, room)
        display = _file(owner, prepared.display, prepared.kind)
        thumb = _file(owner, prepared.thumb, prepared.kind)
        original = _file(owner, prepared.original) if prepared.original is not None else None
        source = _file(owner, prepared.source) if prepared.source is not None else None
        mask = _file(owner, prepared.mask, "image/png") if prepared.mask is not None else None
        files = [f for f in (display, thumb, original, source, mask) if f is not None]

        def save(conn: Connection[DictRow]) -> DictRow:
            # The decisive check, under the owner's lock (CAT-131).
            room = self._check(conn, owner, vehicle, prepared.size, club)
            if not self._enough(room, club):
                raise _Unpaid(room)
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

        return self._picture(self._keep(owner, files, save, club), time.time())

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
        # A picture that grows needs room in the storage, paid first over the free level; one
        # that does not grow is always possible, also over it (CAT-132).
        grow = size - int(row["bytes"])
        with self.db.transaction() as conn:
            room = self._space(conn, owner, grow, club)
        self._pay_first(owner, club, room)

        def save(conn: Connection[DictRow]) -> DictRow:
            room = self._space(conn, owner, grow, club)
            if not self._enough(room, club):
                raise _Unpaid(room)
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

        return self._picture(self._keep(owner, new, save, club), time.time())

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
        """What the owner's pictures take, drafts' included, the free level, and what is paid
        over it this month (CAT-131, CAT-132)."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT coalesce(sum(bytes), 0) AS used, count(*) AS pictures FROM picture "
                "WHERE owner_id = %s",
                (owner,),
            ).fetchone()
            charge = conn.execute(
                "SELECT blocks, unpaid FROM storage_charge WHERE owner_id = %s AND month = %s",
                (owner, self._month(conn)),
            ).fetchone()
        assert row is not None
        used = int(row["used"])
        paid = int(charge["blocks"]) if charge is not None else 0
        return StorageUse(
            used=used,
            limit=self._limit(club),
            club=club,
            pictures=row["pictures"],
            backgrounds=self.segmenter.available(),
            over_free=used > self._limit(club),
            paid_blocks=paid,
            price_per_gb=PRICE_PER_GB,
            unpaid=charge is not None and charge["unpaid"] and self._blocks(used, club) > paid,
        )

    def charge_round(self) -> int:
        """The daily round (CAT-132): every owner still over the free level is charged for this
        month's storage, the first time it is needed, also when no one uploads. Idempotent per
        month: an owner whose month is paid is not asked again, and a GB that is paid is never
        drawn again. An owner whose balance is short is marked unpaid; the pictures stay.

        Only owners that have paid before are in the round: whose balance pays, the person's or
        the club's (TOKEN-29), is as ID said at that charge, since the round has no person to
        ask with. An owner over the free level has always paid before. How many GB were paid."""
        if self.payer is None:
            return 0
        with self.db.transaction() as conn:
            month = self._month(conn)
            rows = conn.execute(
                "WITH used AS (SELECT owner_id, sum(bytes) AS used FROM picture "
                "GROUP BY owner_id HAVING sum(bytes) > %(least)s), "
                "known AS (SELECT DISTINCT ON (owner_id) owner_id, club FROM storage_charge "
                "ORDER BY owner_id, month DESC) "
                "SELECT u.owner_id, u.used, k.club, coalesce(c.blocks, 0) AS paid "
                "FROM used u JOIN known k USING (owner_id) LEFT JOIN storage_charge c "
                "ON c.owner_id = u.owner_id AND c.month = %(month)s ORDER BY u.owner_id",
                {"least": min(self.limits.person, self.limits.club), "month": month},
            ).fetchall()
        paid = 0
        for row in rows:
            used, club = int(row["used"]), bool(row["club"])
            needed = self._blocks(used, club)
            if needed <= row["paid"]:
                continue
            room = Room(month, used, 0, int(row["paid"]), needed, needed)
            try:
                paid += self._settle(row["owner_id"], club, room)
            except Refused as refused:
                if refused.code is ProblemCode.UNAVAILABLE:
                    LOGGER.warning("Lagringens runda avbröts: TrainMeet ID svarar inte.")
                    break
                # Short of tokens, or the day's cap: marked unpaid, and the pictures stay.
        return paid

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
