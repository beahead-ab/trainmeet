"""The monospace typeface is TrainMeet Mono everywhere: JetBrains Mono with a plain zero, since a
dotted zero is read as an eight from a distance (S7, Casper 18 November).

The font itself is made by apps/design/typsnitt/trainmeet_mono.py, which checks the zero's
contours as it builds. Here: no app or page asks for the dotted original any more, and every
place that serves the font has it, with its license.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID_THEME = ROOT / "id/email-code/src/main/resources/theme/trainmeet/login/resources"
FONT_FOLDERS = [ROOT / "apps/design/src/fonts", ID_THEME / "fonts"]
STYLES = [
    *(ROOT / "apps").glob("*/src/**/*.css"),
    *(ROOT / "apps").glob("*/src/**/*.ts"),
    *(ROOT / "apps").glob("*/src/**/*.tsx"),
    *ID_THEME.glob("**/*.css"),
]
# A declaration that picks a typeface: font-family, the font shorthand, or a canvas's ctx.font.
CHOOSES = re.compile(r"font(?:-family)?\s*[:=][^;\n]*JetBrains", re.IGNORECASE)


def test_no_style_asks_for_the_dotted_zero() -> None:
    asking = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in STYLES
        if "node_modules" not in path.parts
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if CHOOSES.search(line)
    ]
    assert asking == []


def test_every_place_that_serves_the_font_has_it_with_its_license() -> None:
    for folder in FONT_FOLDERS:
        assert (folder / "trainmeet-mono.woff2").stat().st_size > 30_000, folder
        license_text = (folder / "LICENSE-trainmeet-mono.txt").read_text(encoding="utf-8")
        assert "SIL Open Font License" in license_text
        assert "JetBrains Mono Project Authors" in license_text
        assert not (folder / "jetbrains-mono.woff2").exists(), folder
    served = (ROOT / "apps/design/src/fonts.css").read_text(encoding="utf-8")
    assert 'font-family: "TrainMeet Mono"' in served
    assert "./fonts/trainmeet-mono.woff2" in served
    login = (ID_THEME / "css/trainmeet.css").read_text(encoding="utf-8")
    assert "../fonts/trainmeet-mono.woff2" in login
    assert (ROOT / "apps/design/src/fonts/trainmeet-mono.woff2").read_bytes() == (
        ID_THEME / "fonts/trainmeet-mono.woff2"
    ).read_bytes()
