"""TrainMeet Mono: JetBrains Mono with a plain zero, without the dot in it (Casper, 18 November).

A dotted zero is read as an eight from a distance (S7), and neither JetBrains Mono nor any open
monospace typeface close to it has a plain zero at full size. So TrainMeet Mono is JetBrains
Mono 2.211, the same Latin subset the apps used, with the inner dot taken out of the zero and
nothing else changed. JetBrains Mono is under the SIL Open Font License 1.1 with no Reserved
Font Name; the modified font keeps that license and has a name of its own, so it is never
mistaken for the original.

Run from the repository's root, with fontTools only for this:

    uv run --no-project --with fonttools --with brotli python apps/design/typsnitt/trainmeet_mono.py

It writes apps/design/src/fonts/trainmeet-mono.woff2 and the copy in ID's login theme.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import ttProgram

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).with_name("jetbrains-mono-2.211.woff2")
TARGET = ROOT / "apps/design/src/fonts/trainmeet-mono.woff2"
COPIES = [ROOT / "id/email-code/src/main/resources/theme/trainmeet/login/resources/fonts"]


def contours(font: TTFont, glyph: str) -> int:
    glyphs = font.getGlyphSet()
    pen = DecomposingRecordingPen(glyphs)
    glyphs[glyph].draw(pen)
    return sum(1 for operator, _ in pen.value if operator == "closePath")


def without_the_dot(font: TTFont) -> None:
    """Take the smallest contour, the dot, out of the zero, in every master of the font."""
    glyf = font["glyf"]
    # The deltas are read before the outline changes: gvar reads them by the zero's points.
    variations = list(font["gvar"].variations["zero"]) if "gvar" in font else []
    zero = glyf["zero"]
    assert not zero.isComposite(), "the zero is drawn as one glyph"
    ends = list(zero.endPtsOfContours)
    starts = [0, *[end + 1 for end in ends[:-1]]]

    def area(index: int) -> float:
        points = zero.coordinates[starts[index] : ends[index] + 1]
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        return float((max(xs) - min(xs)) * (max(ys) - min(ys)))

    dot = min(range(len(ends)), key=area)
    first, last = starts[dot], ends[dot]
    removed = last - first + 1
    keep = [i for i in range(len(zero.coordinates)) if not first <= i <= last]

    zero.coordinates = type(zero.coordinates)([zero.coordinates[i] for i in keep])
    zero.flags = bytearray(zero.flags[i] for i in keep)
    zero.endPtsOfContours = [
        end - (removed if end > last else 0) for i, end in enumerate(ends) if i != dot
    ]
    zero.numberOfContours = len(zero.endPtsOfContours)
    # The hints point at the dot's points; the zero renders well without them.
    zero.program = ttProgram.Program()
    zero.program.fromBytecode(b"")
    zero.recalcBounds(glyf)

    points = ends[-1] + 1
    for variation in variations:
        deltas = variation.coordinates
        assert len(deltas) == points + 4, "every point and the four phantom points"
        variation.coordinates = [deltas[i] for i in keep] + deltas[points:]
    if variations:
        font["gvar"].variations["zero"] = variations


NAMES = {1, 3, 4, 6, 16, 17, 21, 22, 25}
"""The name records that name the font; the copyright, the trademark and the links stay."""


def renamed(font: TTFont) -> None:
    """A name of its own (OFL: a modified version is not presented as the original)."""
    instance_names = (
        {i.postscriptNameID for i in font["fvar"].instances} if "fvar" in font else set()
    )
    for record in font["name"].names:
        text = record.toUnicode()
        new = text
        if record.nameID in NAMES or record.nameID in instance_names:
            new = text.replace("JetBrains Mono", "TrainMeet Mono").replace(
                "JetBrainsMono", "TrainMeetMono"
            )
        elif record.nameID == 5:
            new = f"{text}; TrainMeet Mono, the zero without its dot"
        elif record.nameID == 0:
            new = f"{text} TrainMeet Mono: the dot taken out of the zero, 2026."
        if new != text:
            record.string = new


def main() -> None:
    font = TTFont(SOURCE)
    assert contours(font, "zero") == 3, "the source's zero has its dot"
    without_the_dot(font)
    assert contours(font, "zero") == 2, "the zero is plain"
    assert contours(font, "O") == 2
    renamed(font)
    font.flavor = "woff2"
    font.save(TARGET)
    for folder in COPIES:
        shutil.copyfile(TARGET, folder / TARGET.name)
    print(f"Skrev {TARGET.relative_to(ROOT)} och {len(COPIES)} kopia.")


if __name__ == "__main__":
    main()
