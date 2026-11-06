"""The product name in 5×7 dots, as in the header of every TrainMeet product.

Order in the header: the TRAINMEET sign, the product name in dots in the text colour
(never blue, no sign of its own), a thin vertical line, then the page name.
The glyphs are the same as on trainmeet.se (tools/punkter.py in trainmeet-spec).
"""

from __future__ import annotations

PITCH = 3.0
RADIUS = 1.32
DOT_COLOUR = "#c0c5cf"

_GLYPHS = {
    "A": ".###.|#...#|#...#|#####|#...#|#...#|#...#",
    "B": "####.|#...#|#...#|####.|#...#|#...#|####.",
    "C": ".###.|#...#|#....|#....|#....|#...#|.###.",
    "D": "####.|#...#|#...#|#...#|#...#|#...#|####.",
    "E": "#####|#....|#....|####.|#....|#....|#####",
    "F": "#####|#....|#....|####.|#....|#....|#....",
    "G": ".###.|#...#|#....|#.###|#...#|#...#|.####",
    "H": "#...#|#...#|#...#|#####|#...#|#...#|#...#",
    "I": ".###.|..#..|..#..|..#..|..#..|..#..|.###.",
    "J": "..###|...#.|...#.|...#.|...#.|#..#.|.##..",
    "K": "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
    "L": "#....|#....|#....|#....|#....|#....|#####",
    "M": "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#",
    "N": "#...#|#...#|##..#|#.#.#|#..##|#...#|#...#",
    "O": ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
    "P": "####.|#...#|#...#|####.|#....|#....|#....",
    "R": "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
    "S": ".####|#....|#....|.###.|....#|....#|####.",
    "T": "#####|..#..|..#..|..#..|..#..|..#..|..#..",
    "U": "#...#|#...#|#...#|#...#|#...#|#...#|.###.",
    "V": "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
    "X": "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
    "Y": "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..",
    " ": ".....|.....|.....|.....|.....|.....|.....",
}
GLYPHS: dict[str, list[str]] = {char: rows.split("|") for char, rows in _GLYPHS.items()}


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def product_name_svg(name: str, css_class: str = "namn") -> str:
    """Draw a product name (HUB, TKL, CAD ...) as an SVG of lit dots, one circle per dot."""
    text = name.upper()
    unknown = sorted({char for char in text if char not in GLYPHS})
    if unknown:
        raise ValueError(f"No 5×7 glyph for: {''.join(unknown)}")

    circles: list[str] = []
    for index, char in enumerate(text):
        for row, line in enumerate(GLYPHS[char]):
            for col, cell in enumerate(line):
                if cell == "#":
                    cx = (index * 6 + col) * PITCH + PITCH / 2
                    cy = row * PITCH + PITCH / 2
                    circles.append(f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(RADIUS)}"/>')

    width = (len(text) * 6 - 1) * PITCH
    height = 7 * PITCH
    return (
        f'<svg class="{css_class}" viewBox="0 0 {_num(width)} {_num(height)}" '
        f'role="img" aria-label="{name.title()}">'
        f'<g fill="{DOT_COLOUR}">{"".join(circles)}</g></svg>'
    )
