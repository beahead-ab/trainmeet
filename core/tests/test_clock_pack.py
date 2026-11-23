"""Klockpaket (F13, H75): bilder och clock.json, ingen kod. Reglerna är de gamla Servers.

Ett paket nekas om det kan köra något, hämta något eller inte är kvadratiskt. Varningar
stoppar inte. Högst det gamla taket gäller när Planering tar emot paketen; här provas
formatet, varningarna, den mörka varianten och kommandona example, check, build och preview.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import re
import struct
import tempfile
import zipfile
import zlib
from pathlib import Path

import pytest

from core import clock_pack
from core.clock_pack import ClockPackError, read_pack

SQUARE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">{}</svg>'
HAND = SQUARE.format('<rect x="99" y="20" width="2" height="80"/>')


def manifest(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "format": 1,
        "name": "Mitt ur",
        "version": "1.0",
        "layers": {
            "dial": "dial.svg",
            "hour": "hour.svg",
            "minute": "minute.svg",
            "second": "second.svg",
        },
        "motion": {
            "minute": "jump",
            "minute_bounce": True,
            "second": "sweep",
            "sweep_seconds": 58.5,
        },
    }
    value.update(changes)
    return value


def pack(
    files: dict[str, str | bytes | None] | None = None, *, prefix: str = "", **changes: object
) -> bytes:
    contents: dict[str, str | bytes | None] = {
        "clock.json": json.dumps(manifest(**changes)),
        "dial.svg": SQUARE.format('<circle cx="100" cy="100" r="96" fill="#fff"/>'),
        "hour.svg": HAND,
        "minute.svg": HAND,
        "second.svg": HAND,
    }
    contents.update(files or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in contents.items():
            if text is not None:
                archive.writestr(prefix + name, text)
    return buffer.getvalue()


def bundle(packs: dict[str, bytes], *, folder: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in packs.items():
            archive.writestr(folder + name, data)
    return buffer.getvalue()


def png(width: int, height: int, *, alpha: bool = True) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    channels = 4 if alpha else 3
    rows = b"".join(b"\x00" + b"\x00" * width * channels for _ in range(height))
    color = 6 if alpha else 2
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


PNG_LAYERS = {"dial": "dial.png", "hour": "hour.svg", "minute": "minute.svg"}


def rejected(data: bytes, message: str) -> None:
    with pytest.raises(ClockPackError, match=re.escape(message)):
        read_pack(data)


def test_a_pack_gives_its_layers_and_how_the_hands_move() -> None:
    result = read_pack(pack())
    assert (result.id, result.name, result.version) == ("mitt-ur", "Mitt ur", "1.0")
    assert list(result.layers) == ["dial", "hour", "minute", "second"]
    assert result.layers["dial"].content_type == "image/svg+xml"
    assert result.motion == {
        "hour": "smooth",
        "minute": "jump",
        "minute_bounce": True,
        "second": "sweep",
        "sweep_seconds": 58.5,
    }


def test_the_example_pack_is_a_neutral_face_and_builds_the_same_way_every_time() -> None:
    """H75: ingen färdig tavla från den gamla koden. Exemplet ritas här och är giltigt."""
    result = read_pack(clock_pack.example_pack())
    assert (result.id, sorted(result.layers)) == (
        "exempelur",
        ["dial", "hour", "minute", "second", "top"],
    )
    assert result.warnings == ()
    assert clock_pack.example_pack() == clock_pack.example_pack()


def test_a_pack_zipped_as_a_folder_on_a_mac_is_read() -> None:
    data = pack({"__MACOSX/._clock.json": "x", ".DS_Store": "x"}, prefix="mitt-ur/")
    assert read_pack(data).name == "Mitt ur"


def test_svg_that_could_run_or_fetch_something_is_refused() -> None:
    cases = {
        "<script>": SQUARE.format("<script>alert(1)</script>"),
        "onload": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" onload="alert(1)"/>'
        ),
        "<foreignObject>": SQUARE.format("<foreignObject><div/></foreignObject>"),
        "länkar till andra filer": SQUARE.format(
            '<image href="https://example.com/x.png" width="10" height="10"/>'
        ),
        "skriptlänk": SQUARE.format('<use href="#a" fill="javascript:alert(1)"/>'),
        "DOCTYPE": '<!DOCTYPE svg [<!ENTITY a "aaaa">]>' + SQUARE.format("&a;"),
        "stilen hämtar": SQUARE.format("<style>@import url(https://example.com/a.css);</style>"),
        "<animate>": SQUARE.format('<rect><animate attributeName="x" to="5"/></rect>'),
    }
    for message, svg in cases.items():
        rejected(pack({"hour.svg": svg}), message)


def test_inline_pictures_and_internal_references_are_allowed() -> None:
    tiny = base64.b64encode(png(64, 64)).decode()
    svg = SQUARE.format(
        f'<defs><linearGradient id="g"/></defs><rect fill="url(#g)" width="10" height="10"/>'
        f'<image href="data:image/png;base64,{tiny}" width="10" height="10"/><use href="#g"/>'
    )
    assert "dial" in read_pack(pack({"dial.svg": svg})).layers


def test_layers_must_be_square_so_the_hands_turn_about_the_centre() -> None:
    rejected(
        pack({"dial.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"/>'}),
        "kvadratisk",
    )
    rejected(pack({"dial.svg": '<svg xmlns="http://www.w3.org/2000/svg"/>'}), "viewBox saknas")
    rejected(pack({"dial.png": png(512, 256)}, layers=PNG_LAYERS), "kvadratisk")
    seen = read_pack(pack({"dial.png": png(1024, 1024)}, layers=PNG_LAYERS))
    assert seen.layers["dial"].content_type == "image/png"


def test_a_small_png_is_refused_and_one_too_small_for_4k_is_warned_about() -> None:
    rejected(pack({"dial.png": png(256, 256)}, layers=PNG_LAYERS), "mellan 512 och 4096 px")
    warned = read_pack(pack({"dial.png": png(512, 512)}, layers=PNG_LAYERS))
    assert len(warned.warnings) == 1
    assert "blir mjuk på en 4K-TV" in warned.warnings[0]
    assert read_pack(pack({"dial.png": png(1024, 1024)}, layers=PNG_LAYERS)).warnings == ()


def test_a_broken_or_incomplete_pack_says_what_is_wrong() -> None:
    rejected(b"not a zip", "zip")
    rejected(pack({"clock.json": None}), "clock.json saknas")
    rejected(pack(layers={"dial": "dial.svg", "hour": "hour.svg"}), "minute saknas")
    rejected(pack({"minute.svg": None}), "minute.svg finns inte")
    rejected(
        pack(layers={"dial": "../dial.svg", "hour": "hour.svg", "minute": "minute.svg"}),
        "utan mappar",
    )
    rejected(pack(format=2), "format")
    rejected(pack(motion={"second": "spin"}), "motion.second")
    rejected(pack(motion={"secnd": "tick"}), "okänd inställning")
    rejected(pack(motion={"second": "sweep", "sweep_seconds": 10}), "sweep_seconds")
    rejected(pack(motion={"minute_bounce": True}), "minute_bounce")
    rejected(pack(id="Mitt Ur!"), "id")


def test_size_limits_hold_even_when_the_zip_lies_about_sizes() -> None:
    rejected(b"x" * (clock_pack.MAX_PACKAGE_BYTES + 1), "större än 2 MB")
    big = SQUARE.format("<g>" + " " * (clock_pack.MAX_LAYER_BYTES + 10) + "</g>")
    rejected(pack({"dial.svg": big}), "större än 1024 kB")


def test_the_command_line_builds_and_checks_a_pack_from_the_example() -> None:
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory) / "mitt-ur"
        with contextlib.redirect_stdout(io.StringIO()) as output:
            assert clock_pack.main(["example", str(folder)]) == 0
            assert clock_pack.main(["check", str(folder)]) == 0
            assert clock_pack.main(["build", str(folder)]) == 0
        assert "OK: Exempelur 1.0 (id exempelur)" in output.getvalue()
        with contextlib.redirect_stdout(io.StringIO()):
            preview_path = str(Path(directory) / "se.html")
            assert clock_pack.main(["preview", str(folder), "-o", preview_path]) == 0
        page = (Path(directory) / "se.html").read_text(encoding="utf-8")
        assert "Exempelur" in page
        assert read_pack((Path(directory) / "mitt-ur.tmclock").read_bytes()).id == "exempelur"
        (folder / "hour.svg").write_text(SQUARE.format("<script/>"), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            assert clock_pack.main(["check", str(folder)]) == 1
        assert "<script>" in errors.getvalue()


def test_text_filters_thin_lines_and_a_covering_background_warn_but_do_not_stop() -> None:
    assert read_pack(pack()).warnings == ()
    (text,) = read_pack(
        pack({"dial.svg": SQUARE.format('<text x="100" y="30">12</text>')})
    ).warnings
    assert "dial.svg: text ritas med det typsnitt" in text
    filtered = SQUARE.format(
        '<defs><filter id="f"><feGaussianBlur stdDeviation="2"/></filter></defs>'
        '<rect width="2" height="80" filter="url(#f)"/>'
    )
    (warning,) = read_pack(pack({"hour.svg": filtered})).warnings
    assert "filter" in warning
    thin = SQUARE.format(
        '<line x1="100" y1="10" x2="100" y2="20" stroke="#000" stroke-width="0.6"/>'
    )
    (warning,) = read_pack(pack({"dial.svg": thin})).warnings
    assert "den tunnaste linjen (0.6) är under 0.5 % av sidan (1)" in warning
    thick = SQUARE.format('<line x1="100" y1="10" x2="100" y2="20" stroke-width="1"/>')
    assert read_pack(pack({"dial.svg": thick})).warnings == ()
    big = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">'
        '<line x1="1" y1="1" x2="9" y2="9" style="stroke-width: 3"/></svg>'
    )
    assert len(read_pack(pack({"dial.svg": big})).warnings) == 1
    covered = SQUARE.format(
        '<rect width="100%" height="100%" fill="#fff"/><rect x="99" y="20" width="2" height="80"/>'
    )
    (warning,) = read_pack(pack({"minute.svg": covered})).warnings
    assert "minute.svg: lagret har en bakgrund som täcker hela ytan" in warning
    clear = SQUARE.format('<rect width="200" height="200" fill="none"/>')
    assert read_pack(pack({"minute.svg": clear})).warnings == ()
    square = SQUARE.format('<rect width="200" height="200" fill="#fff"/>')
    (warning,) = read_pack(pack({"dial.svg": square})).warnings
    assert "hörnen syns som en fyrkant" in warning
    round_dial = SQUARE.format('<circle cx="100" cy="100" r="98" fill="#fff"/>')
    assert read_pack(pack({"dial.svg": round_dial})).warnings == ()
    opaque = read_pack(
        pack(
            {"hour.png": png(1024, 1024, alpha=False)},
            layers={"dial": "dial.svg", "hour": "hour.png", "minute": "minute.svg"},
        )
    )
    (warning,) = opaque.warnings
    assert "hour.png: bilden saknar genomskinlighet" in warning
    heavy = SQUARE.format("<g>" + '<rect width="1" height="1"/>' * 8000 + "</g>")
    assert any("kB" in warning for warning in read_pack(pack({"dial.svg": heavy})).warnings)


def test_the_preview_shows_every_pack_at_every_size_on_dark_and_light() -> None:
    page = clock_pack.preview(
        [
            read_pack(pack(name="Ur ett")),
            read_pack(
                pack({"dial.svg": SQUARE.format("<text>1</text>")}, id="ur-tva", name="Ur två")
            ),
        ]
    )
    for size in (44, 52, 84, 347, 683, 960):
        assert f"width:{size}px;height:{size}px" in page
    assert page.count('data-face="ur-ett"') == 12
    assert "Ur två" in page
    assert "text ritas med det typsnitt" in page
    assert "data:image/svg+xml;base64," in page
    assert "<script>alert" not in page


def test_a_dark_variant_is_read_and_checked_the_same_way() -> None:
    dark = SQUARE.format('<circle cx="100" cy="100" r="96" fill="#15181e"/>')
    result = read_pack(
        pack(
            {"dial-dark.svg": dark, "hour-dark.svg": HAND},
            dark={"dial": "dial-dark.svg", "hour": "hour-dark.svg"},
        )
    )
    assert sorted(result.dark) == ["dial", "hour"]
    assert result.manifest()["dark"]["dial"] == {"file": "dial-dark.svg", "type": "image/svg+xml"}
    assert sorted(result.stored_layers()) == [
        "dark-dial",
        "dark-hour",
        "dial",
        "hour",
        "minute",
        "second",
    ]
    assert "mörk variant: dial, hour" in clock_pack.describe(result)
    with pytest.raises(ClockPackError, match="inget lager top"):
        read_pack(pack({"top-dark.svg": HAND}, dark={"top": "top-dark.svg"}))
    with pytest.raises(ClockPackError, match="finns inte"):
        read_pack(pack(dark={"dial": "saknas.svg"}))
    with pytest.raises(ClockPackError, match="ska vara ett objekt"):
        read_pack(pack(dark=["dial-dark.svg"]))
    with pytest.raises(ClockPackError):
        read_pack(
            pack({"dial-dark.svg": SQUARE.format("<script/>")}, dark={"dial": "dial-dark.svg"})
        )
    (warning,) = read_pack(
        pack(
            {"hour-dark.svg": SQUARE.format('<rect width="200" height="200" fill="#000"/>')},
            dark={"hour": "hour-dark.svg"},
        )
    ).warnings
    assert "hour-dark.svg: lagret har en bakgrund" in warning
    assert read_pack(pack({"dial-dark.svg": dark}, dark={"dial": "dial-dark.svg"})).warnings == ()


def test_build_packs_the_dark_files_and_the_preview_shows_them_on_dark() -> None:
    dark = SQUARE.format('<circle cx="100" cy="100" r="96" fill="#15181e"/>')
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory) / "ur"
        with contextlib.redirect_stdout(io.StringIO()):
            clock_pack.main(["example", str(folder)])
        (folder / "dial-dark.svg").write_text(dark, encoding="utf-8")
        body = json.loads((folder / "clock.json").read_text(encoding="utf-8"))
        body["dark"] = {"dial": "dial-dark.svg"}
        (folder / "clock.json").write_text(json.dumps(body), encoding="utf-8")
        result = read_pack(clock_pack.build(folder))
    assert list(result.dark) == ["dial"]
    page = clock_pack.preview([result])
    assert page.count(base64.b64encode(dark.encode()).decode()) == 6


def test_a_zip_of_several_packs_is_read_and_one_bad_pack_names_itself() -> None:
    files = bundle(
        {"a.tmclock": pack(id="ur-a", name="Ur A"), "b.tmclock": pack(id="ur-b", name="Ur B")}
    )
    assert [found.id for _data, found in clock_pack.split_packs(files)] == ["ur-a", "ur-b"]
    nested = bundle({"a.tmclock": pack(id="ur-a")}, folder="klockor/")
    assert clock_pack.read_packs(nested)[0].id == "ur-a"
    with pytest.raises(ClockPackError, match=re.escape("dalig.tmclock: hour.svg")):
        clock_pack.read_packs(
            bundle(
                {
                    "bra.tmclock": pack(id="bra"),
                    "dalig.tmclock": pack({"hour.svg": SQUARE.format("<script/>")}, id="dalig"),
                }
            )
        )
    with pytest.raises(ClockPackError, match="samma id"):
        clock_pack.read_packs(
            bundle({"a.tmclock": pack(id="samma"), "b.tmclock": pack(id="samma")})
        )


def test_the_chosen_style_is_the_first_custom_face_the_meet_has() -> None:
    assert clock_pack.chosen_face(["analog"], {"mitt-ur"}) is None
    assert clock_pack.chosen_face(["custom:mitt-ur", "digital"], {"mitt-ur"}) == "mitt-ur"
    assert clock_pack.chosen_face(["custom:borta"], {"mitt-ur"}) is None
    assert clock_pack.style_id("digital") is None
