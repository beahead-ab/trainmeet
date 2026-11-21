"""AnyRail's files as a Layout (trainmeet-cad-anyrail-import.md, 1. Filformatet and 7. AnyRails egen
fil): the parts with their drawing, the endpoints and the connections, in mm with y down.

Two formats, one Layout:

- AnyRail 2.0's XML export (ANYRAIL-09): the root <layout> with workAreaLengthCm and
  workAreaWidthCm, and parts, endpoints and connections. Only the cm variants are read (lineCm,
  arcCm, bezierCm), never the pixels, and never a bezier's approximation.
- AnyRail's own file (.any, ANYRAIL-01, section 7): a Boost binary archive, read by anyfile.py.
- A ZIP holding exactly one of them, as such files are often sent.

Directions are AnyRail's degrees: the vector (sin d, cos d) with y down. An endpoint's direction
points into its part; an arc's direction is its tangent at p1, pointing out of the arc.

The reader is hardened, as everything an owner uploads is (cad/photos_api.py): at most MAX_BYTES
unpacked, at most MAX_PARTS parts, MAX_ENDPOINTS endpoints and MAX_CONNECTIONS connections, no
DOCTYPE and no entity declaration at all (so no external entity and no entity expansion), every
number finite and within MAX_COORDINATE, and a refusal in Swedish that names what is wrong
(Unreadable). The XML is parsed by expat with handlers that keep only what is read.
"""

from __future__ import annotations

import io
import math
import re
import struct
import zipfile
from dataclasses import dataclass, field
from typing import Final, Literal
from xml.parsers import expat

from contracts.station_model import Point

MB: Final = 1024 * 1024
MAX_BYTES: Final = 20 * MB
"""The largest file read, unpacked (a reference station's XML export is 0.5 MB)."""
MAX_PARTS: Final = 20_000
MAX_ENDPOINTS: Final = 80_000
MAX_CONNECTIONS: Final = 80_000
MAX_ELEMENTS: Final = 2_000_000
"""XML elements in all, approximations included (a reference export has about 9 000)."""
MAX_DEPTH: Final = 32
MAX_COORDINATE: Final = 1_000_000.0
"""cm: ten kilometres either way."""
NOT_ANYRAIL: Final = "Filen gick inte att läsa som AnyRail"


class Unreadable(ValueError):
    """The file is not one AnyRail wrote, or breaks a limit; the message says why, in Swedish."""


Kind = Literal["line", "arc", "bezier"]


@dataclass(frozen=True)
class Element:
    """One drawn element of a part, in mm. line: (p1, p2); arc: (p1, p2) with radius, angle and
    direction; bezier: (cp1, cp2, cp3, cp4)."""

    kind: Kind
    points: tuple[Point, ...]
    width: float
    """The drawn width, mm: 16.5 for H0 track, 3.2 for AnyRail's thin lines."""
    radius: float | None = None
    angle: float | None = None
    direction: float | None = None


@dataclass(frozen=True)
class Part:
    """A part: its type (Flex, LeftRegularTurnout, RightRegularTurnout, Crossing …), its
    endpoints by number and its drawing. track says what the file says it is, when it says it:
    AnyRail's own file knows its track parts from its drawing objects; the XML export does not,
    and the width decides (rule 1)."""

    id: str
    type: str
    endpoints: tuple[int, ...]
    elements: tuple[Element, ...]
    hidden: bool = False
    bridge: bool = False
    track: bool | None = None
    article: str | None = None
    """AnyRail's article number in its track library (.any only): 7056, 7025 …"""


@dataclass(frozen=True)
class Endpoint:
    nr: int
    at: Point
    direction: float
    """Degrees, into the part."""


@dataclass(frozen=True)
class Layout:
    """What an AnyRail file holds, in mm with y down."""

    format: Literal["xml", "any"]
    length: float
    """The work area along x, mm."""
    width: float
    """The work area along y, mm."""
    parts: tuple[Part, ...]
    endpoints: dict[int, Endpoint]
    connections: tuple[tuple[int, int], ...]
    library: str | None = None
    """The track library (.any): ATL02R …"""
    notes: tuple[str, ...] = field(default_factory=tuple)
    """What the reader left out, for the owner."""


def read(data: bytes, name: str = "") -> Layout:
    """The layout in the file: XML, AnyRail's own file, or a ZIP with one of them."""
    if len(data) > MAX_BYTES:
        raise Unreadable(f"{NOT_ANYRAIL}: den är större än {MAX_BYTES // MB} MB.")
    if data[:4] == b"PK\x03\x04":
        data, name = _unzipped(data)
    if _is_boost(data):
        from cad.anyrail import anyfile  # the binary reader only when it is one

        try:
            return anyfile.read_any(data)
        except Unreadable:
            raise
        except (struct.error, IndexError, ValueError, OverflowError, KeyError) as error:
            raise Unreadable(f"{NOT_ANYRAIL}: filen är trasig.") from error
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<"):
        return read_xml(data)
    if name.lower().endswith(".any"):
        raise Unreadable(f"{NOT_ANYRAIL}: den är inte AnyRails egen fil.")
    raise Unreadable(
        f"{NOT_ANYRAIL}. Välj AnyRails egen fil (.any) eller exporten som XML (Arkiv, Exportera)."
    )


def _is_boost(data: bytes) -> bool:
    return data[8:30] == b"serialization::archive"


def _unzipped(data: bytes) -> tuple[bytes, str]:
    """The one AnyRail file in a ZIP, never more than MAX_BYTES of it."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [
                info
                for info in archive.infolist()
                if not info.is_dir() and not info.filename.startswith("__MACOSX/")
            ]
            if len(members) != 1:
                raise Unreadable(f"{NOT_ANYRAIL}: ZIP-filen ska innehålla en enda AnyRail-fil.")
            info = members[0]
            if info.flag_bits & 0x1:
                raise Unreadable(f"{NOT_ANYRAIL}: ZIP-filen är krypterad.")
            if info.file_size > MAX_BYTES:
                raise Unreadable(f"{NOT_ANYRAIL}: den packade filen är större än 20 MB.")
            with archive.open(info) as packed:
                found = packed.read(MAX_BYTES + 1)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, RuntimeError) as error:
        raise Unreadable(f"{NOT_ANYRAIL}: ZIP-filen är trasig.") from error
    if len(found) > MAX_BYTES:
        raise Unreadable(f"{NOT_ANYRAIL}: den packade filen är större än 20 MB.")
    return found, info.filename


# --- The XML export ------------------------------------------------------------------------

_NUMBER = re.compile(r"^\s*-?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?\s*$")


def _number(text: str | None, what: str) -> float:
    if text is None or not _NUMBER.match(text):
        raise Unreadable(f"{NOT_ANYRAIL}: {what} är inget tal.")
    value = float(text)
    if not math.isfinite(value) or abs(value) > MAX_COORDINATE:
        raise Unreadable(f"{NOT_ANYRAIL}: {what} är utanför ritytan.")
    return value


def _point(text: str | None, what: str) -> Point:
    """'1120.7897, 72.9676, 0' in cm, as mm."""
    if text is None:
        raise Unreadable(f"{NOT_ANYRAIL}: {what} saknas.")
    values = text.split(",")
    if len(values) not in (2, 3):
        raise Unreadable(f"{NOT_ANYRAIL}: {what} är ingen punkt.")
    return (_number(values[0], what) * 10, _number(values[1], what) * 10)


def _width(attrs: dict[str, str], what: str) -> float:
    raw = attrs.get("width", "")
    return _number(raw.removesuffix("cm"), what) * 10 if raw else 0.0


class _Xml:
    """expat's handlers: the layout, kept as it is read, never the whole tree."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.count = 0
        self.layout: dict[str, str] | None = None
        self.parts: list[Part] = []
        self.endpoints: dict[int, Endpoint] = {}
        self.connections: list[tuple[int, int]] = []
        self.part: dict[str, str] | None = None
        self.part_endpoints: list[int] = []
        self.elements: list[Element] = []
        self.text: list[str] = []

    def start(self, tag: str, attrs: dict[str, str]) -> None:
        self.count += 1
        if self.count > MAX_ELEMENTS or len(self.stack) >= MAX_DEPTH:
            raise Unreadable(f"{NOT_ANYRAIL}: den är för stor.")
        parent = self.stack[-1] if self.stack else None
        self.stack.append(tag)
        if parent is None:
            if tag != "layout":
                raise Unreadable(f"{NOT_ANYRAIL}: den börjar inte med <layout>.")
            self.layout = attrs
        elif tag == "part" and parent == "parts":
            if len(self.parts) >= MAX_PARTS:
                raise Unreadable(f"{NOT_ANYRAIL}: den har fler än {MAX_PARTS} delar.")
            self.part = attrs
            self.part_endpoints = []
            self.elements = []
        elif tag == "endpointNr" and parent == "endpointNrs":
            self.text = []
        elif parent == "drawing" and self.part is not None:
            self._element(tag, attrs)
        elif tag == "endpoint" and parent == "endpoints":
            if len(self.endpoints) >= MAX_ENDPOINTS:
                raise Unreadable(f"{NOT_ANYRAIL}: den har fler än {MAX_ENDPOINTS} ändpunkter.")
            nr = int(_number(attrs.get("nr"), "En ändpunkts nummer"))
            self.endpoints[nr] = Endpoint(
                nr=nr,
                at=_point(attrs.get("coordCm"), "En ändpunkt"),
                direction=_number(attrs.get("direction", "0"), "En ändpunkts riktning"),
            )
        elif tag == "connection" and parent == "connections":
            if len(self.connections) >= MAX_CONNECTIONS:
                raise Unreadable(f"{NOT_ANYRAIL}: den har för många förbindelser.")
            self.connections.append(
                (
                    int(_number(attrs.get("endpoint1"), "En förbindelse")),
                    int(_number(attrs.get("endpoint2"), "En förbindelse")),
                )
            )

    def _element(self, tag: str, attrs: dict[str, str]) -> None:
        width = _width(attrs, "En linjes bredd")
        if tag == "lineCm":
            points = (_point(attrs.get("p1"), "En linje"), _point(attrs.get("p2"), "En linje"))
            self.elements.append(Element("line", points, width))
        elif tag == "arcCm":
            points = (_point(attrs.get("p1"), "En båge"), _point(attrs.get("p2"), "En båge"))
            radius = _number(attrs.get("radius"), "En båges radie") * 10
            if radius <= 0:
                raise Unreadable(f"{NOT_ANYRAIL}: en båge har ingen radie.")
            self.elements.append(
                Element(
                    "arc",
                    points,
                    width,
                    radius=radius,
                    angle=_number(attrs.get("angle", "0"), "En båges vinkel"),
                    direction=_number(attrs.get("direction"), "En båges riktning"),
                )
            )
        elif tag == "bezierCm":
            controls = tuple(_point(attrs.get(f"cp{k}"), "En bézierkurva") for k in range(1, 5))
            self.elements.append(Element("bezier", controls, width))

    def end(self, tag: str) -> None:
        self.stack.pop()
        if tag == "endpointNr" and self.part is not None:
            self.part_endpoints.append(int(_number("".join(self.text), "En dels ändpunkt")))
            self.text = []
        elif tag == "part" and self.part is not None:
            attrs = self.part
            self.parts.append(
                Part(
                    id=attrs.get("id", "").strip() or str(len(self.parts) + 1),
                    type=attrs.get("type", "").strip() or "Okänd",
                    endpoints=tuple(self.part_endpoints),
                    elements=tuple(self.elements),
                    hidden=attrs.get("hidden") == "true",
                    bridge=attrs.get("bridge") == "true",
                )
            )
            self.part = None

    def characters(self, data: str) -> None:
        if self.stack and self.stack[-1] == "endpointNr":
            self.text.append(data)
            if sum(len(t) for t in self.text) > 32:
                raise Unreadable(f"{NOT_ANYRAIL}: en ändpunkts nummer är för långt.")


def _refuse_declaration(*_: object) -> None:
    raise Unreadable(
        f"{NOT_ANYRAIL}: den har en DOCTYPE eller en ENTITY, som AnyRail aldrig skriver."
    )


def read_xml(data: bytes) -> Layout:
    """AnyRail 2.0's XML export, hardened: no DOCTYPE, no entities, within the limits."""
    if len(data) > MAX_BYTES:
        raise Unreadable(f"{NOT_ANYRAIL}: den är större än {MAX_BYTES // MB} MB.")
    found = _Xml()
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _refuse_declaration
    parser.EntityDeclHandler = _refuse_declaration
    parser.UnparsedEntityDeclHandler = _refuse_declaration
    parser.ExternalEntityRefHandler = _refuse_declaration  # type: ignore[assignment]
    parser.StartElementHandler = found.start
    parser.EndElementHandler = found.end
    parser.CharacterDataHandler = found.characters
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise Unreadable(f"{NOT_ANYRAIL}: XML-filen är trasig ({error.code}).") from error
    except (ValueError, RecursionError) as error:
        if isinstance(error, Unreadable):
            raise
        raise Unreadable(f"{NOT_ANYRAIL}: XML-filen är trasig.") from error
    layout = found.layout
    if layout is None:
        raise Unreadable(f"{NOT_ANYRAIL}: den har ingen <layout>.")
    if not found.parts:
        raise Unreadable(f"{NOT_ANYRAIL}: den har inga delar.")
    length = _number(layout.get("workAreaLengthCm", "0"), "Ritytans längd") * 10
    width = _number(layout.get("workAreaWidthCm", "0"), "Ritytans bredd") * 10
    known = found.endpoints
    for part in found.parts:
        for nr in part.endpoints:
            if nr not in known:
                raise Unreadable(f"{NOT_ANYRAIL}: del {part.id} har en ändpunkt som saknas.")
    connections = tuple(
        (a, b) for a, b in found.connections if a in known and b in known and a != b
    )
    return Layout(
        format="xml",
        length=length,
        width=width,
        parts=tuple(found.parts),
        endpoints=known,
        connections=connections,
    )
