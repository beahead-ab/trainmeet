"""The photo chain's part c3 on synthetic data: the chat's red marks painted out, the module's
proportions finding a side the outline missed (bildkedjan step 4), and a switch placed from its
legs' separation by the library's types, with its blade tips (steps 10–12).

The reference photos (test_referensfoton.py) hold the numbers on real photos; these are the
parts on their own, fast.
"""

from __future__ import annotations

from functools import cache

import cv2
import numpy as np

from cad import switches
from cad.bildkedjan import corners as corners_
from cad.bildkedjan import network, syntetisk
from contracts.cad import Scale

FROM_ABOVE = syntetisk.Shot(size=(2000, 1500), tilt=3.0, distortion=0.0)
"""A phone held over the module, as the reference photos were taken (tilt about 2°)."""


@cache
def photo() -> syntetisk.Photo:
    return syntetisk.take(syntetisk.SCENES["rak"](), FROM_ABOVE)


def test_the_chats_red_numbers_are_painted_out() -> None:
    """Thin saturated red strokes (a number drawn in the chat) are marked and painted out; a
    photo without them is left as it is."""
    pixels = photo().pixels.copy()
    assert not corners_.marks(pixels).any()
    assert corners_.unmarked(pixels) is pixels
    h, w = pixels.shape[:2]
    at = (int(0.04 * w), int(0.95 * h))
    cv2.putText(pixels, "2", at, cv2.FONT_HERSHEY_SIMPLEX, 3.0, (40, 40, 230), 7)
    drawn = corners_.marks(pixels)
    ys, xs = np.nonzero(drawn)
    assert len(xs) and xs.min() >= at[0] - 20 and ys.max() <= at[1] + 20
    clean = corners_.unmarked(pixels)
    hsv = cv2.cvtColor(clean, cv2.COLOR_BGR2HSV)
    red = ((hsv[..., 0] <= 8) | (hsv[..., 0] >= 172)) & (hsv[..., 1] >= 150)
    assert not red[drawn > 0].any()


def test_the_proportions_find_a_side_the_outline_missed() -> None:
    """An outline whose long side lies on something inside the module (as GrabCut can, where
    the scenery looks like the floor) is put right by the module's length over its width."""
    shot = photo()
    scene = syntetisk.SCENES["rak"]()
    truth = corners_.clockwise(np.array(shot.corners, np.float64))
    h, w = shot.pixels.shape[:2]
    factor = corners_.WORK_SIZE / max(h, w)
    small = cv2.resize(
        shot.pixels, (round(w * factor), round(h * factor)), interpolation=cv2.INTER_AREA
    )
    outline = truth * factor
    # One long side moved 15 % of the width into the module.
    sides = np.linalg.norm(np.roll(outline, -1, axis=0) - outline, axis=1)
    i = int(np.argmax(sides))
    j = (i + 1) % 4
    inward = outline.mean(axis=0) - (outline[i] + outline[j]) / 2
    inward /= np.linalg.norm(inward)
    short = float(np.linalg.norm(outline[(i + 2) % 4] - outline[j]))
    wrong = outline.copy()
    wrong[i] += inward * 0.15 * short
    wrong[j] += inward * 0.15 * short
    aspect = float(scene.length) / float(scene.width_a)
    assert corners_.proportion(wrong) / aspect > 1.1
    found = corners_.proportioned(corners_._lab(small), wrong, aspect)
    sharp = corners_.sharpen(
        corners_._lab(shot.pixels, 3), found / factor, max(4.0, corners_.SHARPEN_PX / factor)
    )
    off = np.linalg.norm(corners_.clockwise(sharp.corners) - truth, axis=1)
    assert float(off.max()) <= 3.0, off


def test_a_switch_is_placed_by_its_library_type_and_its_blade_tips_after() -> None:
    """d(s) of a type's diverging leg, seen from 3 mm on (as the rails are told apart at low
    resolution): the type is found, its node where the arc leaves the straight, and the blade
    tips between that and where the leg's visible slope meets the straight."""
    known = next(d for d in switches.designs(Scale.H0) if d.id == "h0-r2200-94")
    assert known.radius is not None and known.angle is not None
    rng = np.random.default_rng(3)
    s0 = 460.0
    xs = np.arange(s0 + 120.0, s0 + 300.0, 2.0)
    ds = network.design_offsets(xs - s0, known.radius, known.angle)
    ds = ds + rng.normal(0, 0.15, len(ds))
    data = np.stack([xs, ds], axis=1)
    data = data[data[:, 1] >= 3.0]
    fitted = network.fit_design(data, 1.0, switches.designs(Scale.H0)[1:])
    assert fitted is not None
    design, points, deviation = fitted
    assert design.id == known.id and abs(points - s0) <= 3.0 and deviation <= 0.3
    tips = network.fit_tips(data, 1.0)
    assert tips is not None and points - 1.0 <= tips <= float(data[0, 0])
    # The same leg toward gable A: mirrored.
    mirrored = np.stack([2 * s0 - xs, ds], axis=1)
    mirrored = mirrored[mirrored[:, 1] >= 3.0]
    fitted = network.fit_design(mirrored, -1.0, switches.designs(Scale.H0)[1:])
    assert fitted is not None and abs(fitted[1] - s0) <= 3.0
