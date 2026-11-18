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
removed, and sweep() deletes the files. An upload marks its keys there before it stores them,
due an hour later, and takes the marks away when the picture is saved: an upload that stops
halfway, even with the process, leaves no files behind for long.

Background removal (CAT-127–CAT-129) and paid storage over the free level (CAT-132) come later.
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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from botocore.auth import S3SigV4Auth, S3SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
from psycopg import Connection
from psycopg.rows import DictRow

from catalog.db import Database
from catalog.fleet import Refused, not_found
from catalog.settings import Settings
from contracts.catalog import Picture, PictureLinks, ProblemCode, StorageUse

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
_KEY: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[0-9a-f]{32}\.jpg"
)
_UPLOAD_GRACE: Final = timedelta(hours=1)
_SWEEP_BATCH: Final = 200
_SRGB: Final = ImageCms.createProfile("sRGB")
_COLUMNS: Final = (
    "id, is_main, position, width, height, bytes, display_key, thumb_key, original_key"
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
    """A picture ready to be stored: JPEG files without metadata."""

    display: bytes
    thumb: bytes
    original: bytes | None
    width: int
    height: int
    """The display picture's size in pixels."""

    @property
    def size(self) -> int:
        """What the picture takes of the owner's storage (CAT-131)."""
        return len(self.display) + len(self.thumb) + len(self.original or b"")


def _fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    """The picture within the box, never larger than it was."""
    width, height = image.size
    scale = min(box[0] / width, box[1] / height)
    if scale >= 1:
        return image
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS, reducing_gap=2.0)


def _jpeg(image: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality, optimize=True)
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


def prepare(data: bytes, keep_original: bool = False) -> Prepared:
    """Check the upload and make its files: the display picture and the thumbnail, and the
    original only with keep_original (Spara original, CAT-17). Refused with a Swedish message
    when it is too large, too many megapixels, or not a JPEG, PNG or WebP."""
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
                clean = _clean(source)
    except Refused:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise _too_many_pixels() from error
    except UnidentifiedImageError as error:
        raise wrong_kind() from error
    except Exception as error:  # a broken file can fail in many ways inside Pillow
        raise _unreadable() from error
    display = _fit(clean, _DISPLAY[0])
    thumb = _fit(display, _THUMB[0])
    return Prepared(
        display=_jpeg(display, _DISPLAY[1]),
        thumb=_jpeg(thumb, _THUMB[1]),
        original=_jpeg(clean, _ORIGINAL_QUALITY) if keep_original else None,
        width=display.width,
        height=display.height,
    )


# --- Where the files lie (CAT-130) -----------------------------------------------------------


class StoreFailed(Exception):
    """The store did not do what was asked. Never holds a key or a secret."""


class Store(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        """Store the file under the key. Raises StoreFailed."""
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


def new_key(owner: UUID) -> str:
    """A file's key: random, under the owner's id, never guessable."""
    return f"{owner}/{uuid.uuid4().hex}.jpg"


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
    bucket is private. PUT and DELETE are signed with AWS's own SigV4 (botocore) and sent with
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


class Pictures:
    def __init__(self, db: Database, store: Store, limits: PictureLimits | None = None) -> None:
        self.db = db
        self.store = store
        self.limits = limits if limits is not None else PictureLimits()

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
        limit = self._limit(club)
        if row["used"] + size > limit:
            whose = "Klubbens fria lagring" if club else "Den fria lagringen"
            raise Refused(
                422,
                ProblemCode.STORAGE_FULL,
                f"{whose} på {_size(limit)} är full. Ta bort bilder för att få plats med fler.",
            )

    def of_vehicle(self, owner: UUID, vehicle: UUID) -> list[Picture]:
        """The vehicle's pictures in order. To look is enough (CAT-46)."""
        with self.db.transaction() as conn:
            self._vehicle(conn, owner, vehicle)
            return self._pictures(conn, vehicle)

    def add(
        self,
        owner: UUID,
        vehicle: UUID,
        data: bytes,
        *,
        keep_original: bool,
        uploaded_by: UUID,
        club: bool,
    ) -> Picture:
        """A new picture of the owner's vehicle, stored with the owner within the owner's limit
        (CAT-131, CAT-133). The first picture is the main one (CAT-125)."""
        prepared = prepare(data, keep_original)
        # A first look without a lock, so a refused upload stores nothing.
        with self.db.transaction() as conn:
            self._check(conn, owner, vehicle, prepared.size, club)
        files = [(new_key(owner), prepared.display), (new_key(owner), prepared.thumb)]
        if prepared.original is not None:
            files.append((new_key(owner), prepared.original))
        keys = [key for key, _ in files]
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO picture_trash (key, due_at) "
                "SELECT k, now() + %s FROM unnest(%s::text[]) k",
                (_UPLOAD_GRACE, keys),
            )
        try:
            for key, content in files:
                self.store.put(key, content)
            with self.db.owner_transaction(owner) as conn:
                self._check(conn, owner, vehicle, prepared.size, club)
                row = conn.execute(
                    "INSERT INTO picture (id, vehicle_id, owner_id, position, is_main, width, "
                    "height, display_key, thumb_key, original_key, bytes, uploaded_by) "
                    "SELECT %(id)s, %(vehicle)s, %(owner)s, coalesce(max(position) + 1, 0), "
                    "NOT coalesce(bool_or(is_main), false), %(width)s, %(height)s, %(display)s, "
                    "%(thumb)s, %(original)s, %(bytes)s, %(by)s "
                    f"FROM picture WHERE vehicle_id = %(vehicle)s RETURNING {_COLUMNS}",
                    {
                        "id": uuid.uuid4(),
                        "vehicle": vehicle,
                        "owner": owner,
                        "width": prepared.width,
                        "height": prepared.height,
                        "display": keys[0],
                        "thumb": keys[1],
                        "original": keys[2] if len(keys) > 2 else None,
                        "bytes": prepared.size,
                        "by": uploaded_by,
                    },
                ).fetchone()
                assert row is not None
                conn.execute("DELETE FROM picture_trash WHERE key = ANY(%s)", (keys,))
        except StoreFailed as error:
            self._discard(keys)
            raise _store_down() from error
        except BaseException:
            self._discard(keys)
            raise
        return self._picture(row, time.time())

    def _discard(self, keys: list[str]) -> None:
        """An upload that failed: its files go now. What cannot go now stays marked in
        picture_trash, and the sweep deletes it when it is due."""
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
            used=row["used"], limit=self._limit(club), club=club, pictures=row["pictures"]
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
