"""Step 2 of the chain: the intake, before anything is stored (bildkedjan, Intag).

- Formats: JPEG, PNG and WebP. HEIC and HEIF are refused with a clear message (export as JPEG),
  as RAW and DNG are; a PDF is not a module photo.
- Orientation: EXIF's orientation is applied to the pixels.
- Colour: an embedded profile (an iPhone's Display P3) is converted to sRGB, 8 bits.
- Integrity: the technical values the camera model can use are read first (the focal length as
  35 mm equivalent, the lens, the size); then all metadata goes: EXIF, GPS, XMP, IPTC and the
  maker's notes. The picture is made anew from its pixels, so nothing of the file survives.
  GPS is never stored, not even in a kept original.
- No recompression before the measuring: the chain measures the decoded pixels. A photo over
  MAX_MEGAPIXELS is made smaller once, by a known factor.
- Checksums (SHA-256) of the file as sent and of the clean pixels: the job's key, so the same
  photo costs once.

The clean original kept until the module is approved (CAD4) is the clean pixels as a JPEG of
ORIGINAL_QUALITY, never the file as sent.
"""

from __future__ import annotations

import hashlib
import io
import math
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

MB = 1024 * 1024
MAX_BYTES = 30 * MB
"""The largest photo the intake takes."""
MAX_MEGAPIXELS = 24
"""A larger photo is made smaller once (bildkedjan step 2)."""
MAX_PIXELS_READ = 120_000_000
"""Pillow refuses anything larger before a pixel is unpacked."""
ORIGINAL_QUALITY = 95
FORMATS = ("JPEG", "PNG", "WEBP")
_SRGB = ImageCms.createProfile("sRGB")


class Refused(Exception):
    """The photo cannot be taken in; the message says why, in Swedish."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Intake:
    """A photo taken in: its pixels (BGR, as OpenCV has them), clean of metadata."""

    pixels: NDArray[Any]
    sent_sha256: str
    clean_sha256: str
    focal_35mm: float | None
    lens: str | None
    scale: float
    """The factor the photo was made smaller by, 1 when it was not."""
    size: tuple[int, int]
    """The size as sent, upright, px."""

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])


def _sniff(data: bytes) -> str | None:
    head = data[:16]
    if head[4:8] == b"ftyp" and head[8:12] in (
        b"heic",
        b"heix",
        b"hevc",
        b"heim",
        b"heis",
        b"mif1",
        b"msf1",
        b"avif",
    ):
        return "heic"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "raw"
    if head[:5] == b"%PDF-":
        return "pdf"
    return None


def _technical(image: Image.Image) -> tuple[float | None, str | None]:
    """The focal length as 35 mm equivalent and the lens, from EXIF, before it is dropped."""
    try:
        exif = image.getexif()
        sub = exif.get_ifd(0x8769)
    except Exception:
        return None, None
    focal: float | None = None
    raw = sub.get(0xA405)  # FocalLengthIn35mmFilm
    try:
        if raw:
            focal = float(raw)
    except (TypeError, ValueError):
        focal = None
    if focal is not None and not 8 <= focal <= 300:
        focal = None
    lens = sub.get(0xA434)  # LensModel
    lens_text = str(lens).strip()[:80] if isinstance(lens, str) and lens.strip() else None
    return focal, lens_text


def _in_srgb(image: Image.Image, icc: object) -> Image.Image:
    if not isinstance(icc, bytes) or not icc:
        return image
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        converted = ImageCms.profileToProfile(image, profile, _SRGB, outputMode="RGB")
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
        return image
    return converted if converted is not None else image


def take(data: bytes) -> Intake:
    """The photo taken in, or Refused with why."""
    if len(data) > MAX_BYTES:
        raise Refused("Fotot är för stort. Högst 30 MB per foto.", 413)
    kind = _sniff(data)
    if kind == "heic":
        raise Refused("HEIC-foton tas inte emot än. Spara fotot som JPEG och ladda upp igen.", 415)
    if kind == "raw":
        raise Refused("RAW- och DNG-foton tas inte emot. Spara fotot som JPEG.", 415)
    if kind == "pdf":
        raise Refused("Det här är en PDF. Ladda upp ett foto i JPEG, PNG eller WebP.", 415)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=FORMATS) as source:
                if source.width * source.height > MAX_PIXELS_READ:
                    raise Refused("Fotot har för hög upplösning.")
                source.load()
                focal, lens = _technical(source)
                icc = source.info.get("icc_profile")
                upright = ImageOps.exif_transpose(source) or source
                flat = upright.convert("RGB")
    except Refused:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise Refused("Fotot har för hög upplösning.") from error
    except UnidentifiedImageError as error:
        raise Refused(
            "Fotot kunde inte läsas. Välj ett foto i JPEG, PNG eller WebP.", 415
        ) from error
    except Exception as error:  # a broken file can fail in many ways inside Pillow
        raise Refused("Fotot kunde inte läsas. Välj ett foto i JPEG, PNG eller WebP.") from error
    flat = _in_srgb(flat, icc)
    size = flat.size
    scale = 1.0
    pixels_count = flat.width * flat.height
    if pixels_count > MAX_MEGAPIXELS * 1_000_000:
        scale = math.sqrt(MAX_MEGAPIXELS * 1_000_000 / pixels_count)
        flat = flat.resize(
            (round(flat.width * scale), round(flat.height * scale)), Image.Resampling.LANCZOS
        )
    # A new picture from the pixels alone: no EXIF, GPS, XMP, IPTC, profile or comment.
    rgb = np.asarray(flat, dtype=np.uint8)
    pixels = np.ascontiguousarray(rgb[..., ::-1])
    return Intake(
        pixels=pixels,
        sent_sha256=hashlib.sha256(data).hexdigest(),
        clean_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
        focal_35mm=focal,
        lens=lens,
        scale=scale,
        size=(int(size[0]), int(size[1])),
    )


def jpeg(pixels: NDArray[Any], quality: int = ORIGINAL_QUALITY) -> bytes:
    """Pixels (BGR) as a JPEG without any metadata."""
    image = Image.fromarray(np.ascontiguousarray(pixels[..., ::-1]))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def png(pixels: NDArray[Any]) -> bytes:
    image = Image.fromarray(np.ascontiguousarray(pixels[..., ::-1]) if pixels.ndim == 3 else pixels)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def read_clean(data: bytes) -> NDArray[Any]:
    """A JPEG or PNG the chain stored itself, back as pixels (BGR)."""
    with Image.open(io.BytesIO(data), formats=("JPEG", "PNG")) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    return np.ascontiguousarray(rgb[..., ::-1])


def has_metadata(data: bytes) -> list[str]:
    """What metadata a stored file still carries: for the tests and the reference photos."""
    found: list[str] = []
    with Image.open(io.BytesIO(data)) as image:
        exif = image.getexif()
        if len(exif):
            found.append("EXIF")
        if exif.get_ifd(0x8825):
            found.append("GPS")
        for key in ("icc_profile", "xmp", "XML:com.adobe.xmp", "comment", "photoshop", "exif"):
            if image.info.get(key):
                found.append(key)
    return found
