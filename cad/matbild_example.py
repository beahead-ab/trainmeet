"""Synthetic measuring images for the example assembly (cad/assembly_example.py), for the browser
test of Mätbilden under in TKL's Foto (#89 del d4): what CAD's Mätbilden i Foto sends for it,
made by CAD's own code (cad/matbilder.py), before and after the assembly's change.

    python -m cad.matbild_example <folder>

writes bilder-fore.json and bilder-efter.json (StudioImages) and one JPEG per module version,
<module>-<version>.jpg: the display copy at 1 px per mm as the photo chain keeps it, with a margin
of grass round the board, and the module's own tracks with ballast, sleepers and rails, drawn from
its graph as a straightened photo shows them. Nothing here is a real station.
"""

from __future__ import annotations

import itertools
import sys
import uuid
from pathlib import Path
from typing import Final

import cv2
import numpy as np
from numpy.typing import NDArray

from cad import assembly, geometry, landskap, matbilder, switches
from cad.assembly_example import ASSEMBLY, NAMESPACE, _joint, _line, _with_switch
from cad.bildkedjan.rectify import MEASURE_PPM
from contracts.cad import Scale, StudioImage, StudioImages, StudioSourceKind

MARGIN: Final = 20
"""mm of grass round the board, as the measuring image has a margin."""
GAUGE: Final = switches.limits(Scale.H0).gauge
SEED: Final = 89


def members(after: bool) -> list[assembly.Member]:
    """The example assembly's modules, as cad.assembly_example.example puts them together."""
    found = [_with_switch(), _line("Linje", 2, 1200 if after else 1500, 2 if after else 1)]
    if after:
        found.append(_line("Linje bortom", 3, 1000))
    return found


def picture(member: assembly.Member) -> NDArray[np.uint8]:
    """The module from above at 1 px per mm, pixel (0, 0)'s corner at (-MARGIN, -MARGIN) mm."""
    board = geometry.outline(member.shape, geometry.track1_of(member.gables[0].tracks))
    xs, ys = [p[0] for p in board], [p[1] for p in board]
    width, height = round(max(xs)) + 2 * MARGIN, round(max(ys)) + 2 * MARGIN
    grid = landskap.Grid(-MARGIN, -MARGIN, 1.0, width, height)
    gx, gy = grid.centres()
    rng = np.random.default_rng(SEED)
    noise = rng.standard_normal((height, width)).astype(np.float32)
    picture = np.empty((height, width, 3), np.float32)
    picture[:] = (58, 104, 76)
    on_board = (gx >= 0) & (gx <= max(xs)) & (gy >= 0) & (gy <= max(ys))
    picture[on_board] = (84, 138, 112)
    picture[(gy >= max(ys) - 90) & on_board] = (126, 150, 160)
    distance = landskap.track_distance(grid, member.graph)
    picture[distance <= 23] = (158, 164, 170)
    picture[(distance <= 14) & ((gx % 7.1) < 2.6)] = (186, 192, 198)
    picture[np.abs(distance - GAUGE / 2) <= 0.9] = (60, 62, 66)
    picture += noise[..., None] * 6
    return np.clip(picture, 0, 255).astype(np.uint8)


def images(after: bool, folder: Path) -> StudioImages:
    """What Mätbilden i Foto sends for the example assembly, its JPEGs written to folder."""
    found = members(after)
    joints = [_joint(a, b) for a, b in itertools.pairwise(found)]
    placement = assembly.place(found, [assembly.Pose()] * len(found), joints)
    listed: list[StudioImage] = []
    for member in found:
        pixels = picture(member)
        ok, data = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, matbilder.JPEG_QUALITY])
        assert ok
        (folder / f"{member.module}-{member.version}.jpg").write_bytes(data.tobytes())
        height, width = pixels.shape[:2]
        x0 = -MARGIN + 0.5 / MEASURE_PPM
        grid = [x0, x0, MEASURE_PPM, width * MEASURE_PPM, height * MEASURE_PPM]
        frame = matbilder.frame_of(grid, width, height, None)
        pose = placement.poses[member.module]
        listed.append(
            StudioImage(
                module=member.module,
                version=member.version,
                number=member.number,
                name=member.name,
                job=uuid.uuid5(NAMESPACE, f"foto {member.name} {member.version}"),
                at=pose.at,
                angle=pose.angle,
                frame=frame,
                to_source=list(
                    matbilder.compose(matbilder.pose(pose.at, pose.angle), frame.matrix)
                ),
                outline=assembly.outline(member, pose),
            )
        )
    return StudioImages(
        kind=StudioSourceKind.ASSEMBLY,
        source=ASSEMBLY,
        revision=3 if after else 2,
        gauge=GAUGE,
        images=listed,
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    folder = Path(argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    for name, after in (("bilder-fore.json", False), ("bilder-efter.json", True)):
        text = images(after, folder).model_dump_json(indent=1) + "\n"
        (folder / name).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
