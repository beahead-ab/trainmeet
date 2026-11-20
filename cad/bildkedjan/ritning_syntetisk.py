"""A synthetic station drawing with a known truth, for the tests, the browser test and the
screenshots (#89 del c4). Nothing here is a real station: the station is made up.

The drawing is a signal plan as owners draw them: blue lines are tracks, short red strokes across
them are track-circuit boundaries, a signal is a grey frame with its lamps beside the track, its
post and foot at its place, or only a text by a boundary stroke ("Hdvsi 21 (201)"), and its text
gives its type, name and address ("13 (103)", or "15" over "(105)"). Two orange lines are
platforms, and green triangles by the tracks are a symbol the standard interlocking does not
know, explained in a legend in the corner, as a panel's route buttons are. The station has a
double track with a crossover, a loop and a siding with a buffer stop.

- pdf(): the drawing as a vector PDF with a text layer (R1), written here by hand: lines,
  rectangles, circles as Bézier curves, filled triangles, and the text in Helvetica.
- picture(): the drawing as pixels on white paper.
- photo(): the paper photographed at an angle, on a darker table, with uneven light and noise,
  as a JPEG (R2).
- ai_answer(): what a careful AI would transcribe from the photo, as the pretend AI answers.

    python -m cad.bildkedjan.ritning_syntetisk pdf ritning.pdf
    python -m cad.bildkedjan.ritning_syntetisk foto ritning.jpg
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from cad.bildkedjan import ritning

Point = tuple[float, float]
RGB = tuple[float, float, float]

WIDTH: Final = 842.0
HEIGHT: Final = 595.0
BLUE: Final = (0.36, 0.61, 0.84)
RED: Final = (1.0, 0.0, 0.0)
GREY: Final = (0.55, 0.55, 0.55)
ORANGE: Final = (0.95, 0.55, 0.1)
GREEN: Final = (0.1, 0.65, 0.3)
LAMP_GREEN: Final = (0.44, 0.68, 0.28)
LAMP_RED: Final = (0.75, 0.0, 0.0)
BLACK: Final = (0.0, 0.0, 0.0)
TEXT_SIZE: Final = 9.0


@dataclass(frozen=True)
class Figure:
    """A signal figure: its foot on the track side, its head the way it applies."""

    foot: Point
    facing: str
    lamps: int
    above: bool


@dataclass
class Scene:
    tracks: list[list[Point]] = field(default_factory=list)
    platforms: list[list[Point]] = field(default_factory=list)
    bars: list[tuple[Point, Point]] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    texts: list[tuple[str, Point]] = field(default_factory=list)
    """The text and its baseline's left end, y down."""
    triangles: list[tuple[Point, str]] = field(default_factory=list)
    truth: dict[str, Any] = field(default_factory=dict)


def _bar(x: float, y: float, half: float = 7.0) -> tuple[Point, Point]:
    return ((x, y - half), (x, y + half))


def scene() -> Scene:
    """The made-up station: tracks 1 and 2 through, a crossover west, the loop track 3 and the
    siding 4 off it, in points with y down on an A4 page lying down."""
    s = Scene()
    y1, y2, y3, y4 = 360.0, 330.0, 300.0, 270.0
    s.tracks = [
        [(40.0, y1), (800.0, y1)],  # spår 1, line exits both ends
        [(40.0, y2), (800.0, y2)],  # spår 2
        [(120.0, y1), (150.0, y2)],  # the crossover: switches 1 and 2
        [(220.0, y2), (250.0, y3), (620.0, y3), (650.0, y2)],  # spår 3: switches 3 and 4
        [(540.0, y3), (570.0, y4), (700.0, y4)],  # spår 4: switch 5, a buffer stop at 700
    ]
    s.platforms = [[(300.0, y2 + 12), (560.0, y2 + 12)], [(300.0, y3 - 12), (520.0, y3 - 12)]]
    bars = [(90.0, y1), (200.0, y1), (720.0, y1), (90.0, y2), (200.0, y2), (720.0, y2)]
    bars += [(280.0, y3), (600.0, y3), (620.0, y4)]
    s.bars = [_bar(x, y) for x, y in bars]
    s.figures = [
        Figure((200.0, y2 - 9), "east", 2, True),  # 11 (101)
        Figure((720.0, y2 - 9), "west", 2, True),  # 12 (102)
        Figure((90.0, y1 + 9), "east", 3, False),  # 13 (103)
        Figure((720.0, y1 + 9), "west", 2, False),  # 14 (104)
        Figure((200.0, y1 + 9), "east", 2, False),  # 15 over (105)
    ]
    s.texts = [
        ("11 (101)", (222.0, y2 - 18)),
        ("12 (102)", (668.0, y2 - 18)),
        ("13 (103)", (112.0, y1 + 24)),
        ("14 (104)", (668.0, y1 + 24)),
        ("15", (222.0, y1 + 20)),
        ("(105)", (222.0, y1 + 30)),
        ("Hdvsi 21 (201)", (284.0, y3 - 4)),
        ("Dvsi 22 (202)", (538.0, y3 + 12)),
        ("1", (110.0, y1 + 12)),
        ("2", (152.0, y2 - 5)),
        ("3", (214.0, y2 - 5)),
        ("4", (652.0, y2 - 5)),
        ("5", (532.0, y3 - 5)),
        ("Spår 1", (420.0, y1 - 3)),
        ("Spår 2", (600.0, y2 - 3)),
        ("Spår 3", (420.0, y3 - 3)),
        ("Spår 4", (630.0, y4 - 3)),
        ("Exempelby signaler och spårledningar", (300.0, 120.0)),
        ("Teckenförklaring", (620.0, 470.0)),
        ("Tågvägsknapp", (650.0, 490.0)),
    ]
    s.triangles = [((330.0, y2 + 22), "east"), ((480.0, y2 + 22), "west"), ((636.0, 487.0), "east")]
    s.truth = {
        "switches": {
            "1": (120.0, y1),
            "2": (150.0, y2),
            "3": (220.0, y2),
            "4": (650.0, y2),
            "5": (540.0, y3),
        },
        "line_exits": 4,
        "buffer_stops": 1,
        "pieces": 10,
        "boundaries": 9,
        "signals": {
            "11": ("hsi", 2, 101, "east"),
            "12": ("hsi", 2, 102, "west"),
            "13": ("hsi", 3, 103, "east"),
            "14": ("hsi", 2, 104, "west"),
            "15": ("hsi", 2, 105, "east"),
            "21": ("hdvsi", None, 201, "west"),
            "22": ("dvsi", None, 202, "east"),
        },
        "tracks": ["1", "2", "3", "4"],
    }
    return s


# --- The figures' parts ------------------------------------------------------------------


def _frame(f: Figure) -> tuple[Point, Point, Point, Point, list[Point]]:
    """A signal figure: the post's two ends, the foot's two ends, and its lamps' centres."""
    sign = 1.0 if f.facing == "east" else -1.0
    x, y = f.foot
    post_end = (x + sign * 6.0, y)
    foot = ((x, y - 3.5), (x, y + 3.5))
    lamps = [(x + sign * (9.5 + 5.0 * k), y) for k in range(f.lamps)]
    return (x, y), post_end, foot[0], foot[1], lamps


def _frame_box(f: Figure) -> tuple[float, float, float, float]:
    sign = 1.0 if f.facing == "east" else -1.0
    x, y = f.foot
    a = x + sign * 6.0
    b = x + sign * (6.0 + 5.0 * f.lamps + 2.0)
    return (min(a, b), y - 3.5, max(a, b), y + 3.5)


def _triangle(at: Point, facing: str, size: float = 4.0) -> list[Point]:
    sign = 1.0 if facing == "east" else -1.0
    x, y = at
    return [
        (x + sign * size, y),
        (x - sign * size, y - size * 0.8),
        (x - sign * size, y + size * 0.8),
    ]


# --- The vector PDF (R1) ------------------------------------------------------------------


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def pdf(s: Scene | None = None) -> bytes:
    """The drawing as a one-page vector PDF with a text layer, written by hand."""
    s = s or scene()
    ops: list[str] = []

    def y(v: float) -> float:
        return HEIGHT - v

    def colour(c: RGB, fill: bool = False) -> str:
        return f"{c[0]:.3f} {c[1]:.3f} {c[2]:.3f} {'rg' if fill else 'RG'}"

    def line(points: list[Point], c: RGB, width: float) -> None:
        ops.append(f"{colour(c)} {width:.2f} w")
        ops.append(
            " ".join(
                f"{x:.2f} {y(v):.2f} {'m' if i == 0 else 'l'}" for i, (x, v) in enumerate(points)
            )
            + " S"
        )

    def circle(centre: Point, r: float, fill: RGB, stroke: RGB) -> None:
        k = 0.5523 * r
        cx, cy = centre[0], y(centre[1])
        ops.append(f"{colour(fill, True)} {colour(stroke)} 0.6 w")
        ops.append(
            f"{cx + r:.2f} {cy:.2f} m "
            f"{cx + r:.2f} {cy + k:.2f} {cx + k:.2f} {cy + r:.2f} {cx:.2f} {cy + r:.2f} c "
            f"{cx - k:.2f} {cy + r:.2f} {cx - r:.2f} {cy + k:.2f} {cx - r:.2f} {cy:.2f} c "
            f"{cx - r:.2f} {cy - k:.2f} {cx - k:.2f} {cy - r:.2f} {cx:.2f} {cy - r:.2f} c "
            f"{cx + k:.2f} {cy - r:.2f} {cx + r:.2f} {cy - k:.2f} {cx + r:.2f} {cy:.2f} c h B"
        )

    for track in s.tracks:
        line(track, BLUE, 1.0)
    for platform in s.platforms:
        line(platform, ORANGE, 1.0)
    for a, b in s.bars:
        line([a, b], RED, 2.6)
    for f in s.figures:
        foot, post_end, foot_a, foot_b, lamps = _frame(f)
        line([foot, post_end], GREY, 0.8)
        line([foot_a, foot_b], GREY, 0.8)
        x0, y0, x1, y1 = _frame_box(f)
        ops.append(
            f"1 1 1 rg {colour(GREY)} 0.8 w {x0:.2f} {y(y1):.2f} {x1 - x0:.2f} {y1 - y0:.2f} re B"
        )
        for k, lamp in enumerate(lamps):
            circle(lamp, 1.8, LAMP_GREEN if k % 2 == 0 else LAMP_RED, GREY)
    for at, facing in s.triangles:
        points = _triangle(at, facing)
        ops.append(
            f"{colour(GREEN, True)} "
            + " ".join(
                f"{x:.2f} {y(v):.2f} {'m' if i == 0 else 'l'}" for i, (x, v) in enumerate(points)
            )
            + " h f"
        )
    content = "\n".join(ops).encode("ascii")
    texts = b"\n".join(
        b"BT /F1 %.1f Tf 0 0 0 rg %.2f %.2f Td (" % (TEXT_SIZE, x, y(v))
        + _escape(text)
        + b") Tj ET"
        for text, (x, v) in s.texts
    )
    stream = content + b"\n" + texts
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 5 0 R >> "
        b">> /Contents 4 0 R >>" % (int(WIDTH), int(HEIGHT)),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    )
    return out.getvalue()


# --- The raster: the paper, and the photo of it (R2) -------------------------------------


def picture(s: Scene | None = None, scale: float = 3.0) -> NDArray[Any]:
    """The drawing on white paper, BGR, at scale px per point."""
    s = s or scene()
    width, height = round(WIDTH * scale), round(HEIGHT * scale)
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    def px(p: Point) -> tuple[float, float]:
        return (p[0] * scale, p[1] * scale)

    def rgb(c: RGB) -> tuple[int, int, int]:
        return (round(c[0] * 255), round(c[1] * 255), round(c[2] * 255))

    for track in s.tracks:
        draw.line([px(p) for p in track], fill=rgb(BLUE), width=round(1.0 * scale), joint="curve")
    for platform in s.platforms:
        draw.line([px(p) for p in platform], fill=rgb(ORANGE), width=round(1.0 * scale))
    for a, b in s.bars:
        draw.line([px(a), px(b)], fill=rgb(RED), width=round(2.6 * scale))
    for f in s.figures:
        foot, post_end, foot_a, foot_b, lamps = _frame(f)
        draw.line([px(foot), px(post_end)], fill=rgb(GREY), width=round(0.8 * scale))
        draw.line([px(foot_a), px(foot_b)], fill=rgb(GREY), width=round(0.8 * scale))
        x0, y0, x1, y1 = _frame_box(f)
        draw.rectangle(
            [px((x0, y0)), px((x1, y1))],
            fill=(255, 255, 255),
            outline=rgb(GREY),
            width=round(0.8 * scale),
        )
        for k, lamp in enumerate(lamps):
            cx, cy = px(lamp)
            r = 1.8 * scale
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                fill=rgb(LAMP_GREEN if k % 2 == 0 else LAMP_RED),
                outline=rgb(GREY),
            )
    for at, facing in s.triangles:
        draw.polygon([px(p) for p in _triangle(at, facing)], fill=rgb(GREEN))
    font = ritning.font(round(TEXT_SIZE * scale))
    for text, (x, v) in s.texts:
        draw.text((x * scale, v * scale), text, fill=(0, 0, 0), font=font, anchor="ls")
    return np.asarray(image)[:, :, ::-1].copy()


def photo(s: Scene | None = None, seed: int = 11) -> bytes:
    """The paper photographed at an angle on a darker table, with uneven light and noise, as a
    JPEG."""
    paper = picture(s, 2.4)
    h, w = paper.shape[:2]
    out_w, out_h = round(w * 1.25), round(h * 1.3)
    source = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
    target = np.array(
        [
            [0.12 * out_w, 0.08 * out_h],
            [0.9 * out_w, 0.13 * out_h],
            [0.95 * out_w, 0.9 * out_h],
            [0.06 * out_w, 0.86 * out_h],
        ],
        np.float32,
    )
    matrix = cv2.getPerspectiveTransform(source, target)
    table = np.full((out_h, out_w, 3), (70, 85, 95), np.uint8)
    warped = cv2.warpPerspective(
        paper, matrix, (out_w, out_h), borderMode=cv2.BORDER_TRANSPARENT, dst=table
    )
    yy, xx = np.mgrid[0:out_h, 0:out_w].astype(np.float32)
    light = 0.62 + 0.38 * (xx / out_w) * (0.7 + 0.3 * yy / out_h)
    rng = np.random.default_rng(seed)
    noisy = warped.astype(np.float32) * light[..., None] + rng.normal(0, 3.0, warped.shape)
    made = np.clip(cv2.GaussianBlur(noisy, (3, 3), 0.7), 0, 255).astype(np.uint8)
    ok, data = cv2.imencode(".jpg", made, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    return bytes(data.tobytes())


def ai_answer(s: Scene | None = None) -> str:
    """The transcription a careful AI gives of the photo straightened: every text with its box,
    in 0–1000 of the page."""
    s = s or scene()
    texts = []
    for text, (x, v) in s.texts:
        width = 0.52 * TEXT_SIZE * len(text)
        texts.append(
            {
                "text": text,
                "x": round(x / WIDTH * 1000, 1),
                "y": round((v - 0.75 * TEXT_SIZE) / HEIGHT * 1000, 1),
                "b": round(width / WIDTH * 1000, 1),
                "h": round(TEXT_SIZE / HEIGHT * 1000, 1),
            }
        )
    return json.dumps({"texter": texts}, ensure_ascii=False)


EXAMPLE_JOB: Final = "5e1c0a4d-7b2f-4c89-9d3e-0c4a1b2c3d4e"
"""The example read's job: contracts/examples/exempelby.drawing-read.json."""


def example_read() -> str:
    """The drawing as a vector PDF read by the chain, as the contract's example: what Studio's
    tests and the browser test's pretend CAD answer with."""
    from cad.bildkedjan import ritning_in
    from contracts.cad import DrawingPageKind, DrawingPrice, DrawingRead, DrawingUnderlay

    page = ritning_in.take(pdf()).pages[0]
    made = ritning.assemble(ritning.read(page), page)
    pixels, transform = ritning.render(page)
    read = DrawingRead(
        job=UUID(EXAMPLE_JOB),
        page=1,
        kind=DrawingPageKind.VECTOR,
        graph=made.graph,
        boundaries=made.boundaries,
        questions=made.questions,
        underlay=DrawingUnderlay(
            url=f"/api/cad/1/drawings/{EXAMPLE_JOB}/underlay",
            width=int(pixels.shape[1]),
            height=int(pixels.shape[0]),
            transform=transform,
        ),
        summary=made.summary,
        price=DrawingPrice(
            tokens=0,
            why="vector",
            text="Gratis: sidan har ritade linjer och text, som koden läser utan AI.",
        ),
        cost=0,
        notes=made.notes,
    )
    return json.dumps(read.model_dump(mode="json"), ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("pdf", "foto", "bild", "avlasning"):
        print(
            "python -m cad.bildkedjan.ritning_syntetisk pdf|foto|bild|avlasning <fil>",
            file=sys.stderr,
        )
        return 2
    if argv[1] == "avlasning":
        data = example_read().encode()
    elif argv[1] == "pdf":
        data = pdf()
    elif argv[1] == "foto":
        data = photo()
    else:
        ok, encoded = cv2.imencode(".png", picture())
        assert ok
        data = bytes(encoded.tobytes())
    with open(argv[2], "wb") as out:
        out.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
