"""The photo chain's part c5 on synthetic data: the board's edge past a shadow the module casts
on the floor, a rounded corner where the sides cross, a tilted photo's proportions as the
camera model has them, and a curve module's outline put right by its shape (bildkedjan step
4); and on a sketch, a bridge drawn over the tracks, two tracks whose ink runs together into a
wedge, and frames in faint pencil with a corner cut.

The reference photos and sketches (test_referensfoton.py, test_skiss.py) hold the numbers on
real material; these are the parts on their own, fast.
"""

from __future__ import annotations

import math
from functools import cache

import cv2
import numpy as np
from numpy.typing import NDArray

from cad.bildkedjan import chain, intake, skiss, syntetisk
from cad.bildkedjan import corners as corners_
from cad.bildkedjan.camera import focal_from_35mm


def _floor(shape: tuple[int, int], rng: np.random.Generator) -> NDArray[np.float32]:
    """Light wood with grain, BGR."""
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    grain = np.sin(xs / 7 + ys / 90) * 0.5 + np.sin(xs / 2.1) * 0.2
    floor = np.stack([110 + 14 * grain, 160 + 16 * grain, 196 + 16 * grain], axis=-1)
    found: NDArray[np.float32] = floor + rng.normal(0, 2.0, (h, w, 1)).astype(np.float32)
    return found


def shadowed_board() -> tuple[NDArray[np.uint8], np.ndarray, float]:
    """A dark, grassy board on a light wooden floor, with the shadow it casts on the floor
    beside its right side: 26 px of the floor's own colour, darker and warmer, smooth. The
    board's corners, and where the shadow's outer edge lies."""
    rng = np.random.default_rng(5)
    h, w = 700, 900
    image = _floor((h, w), rng)
    x0, y0, x1, y1 = 150, 120, 690, 580
    shadow = 26
    band = image[y0 + 8 : y1 + 8, x1 : x1 + shadow]
    image[y0 + 8 : y1 + 8, x1 : x1 + shadow] = band * np.array([0.22, 0.3, 0.42], np.float32)
    grass = np.array([45, 72, 62], np.float32) + rng.normal(0, 30, (y1 - y0, x1 - x0, 1))
    image[y0:y1, x0:x1] = cv2.GaussianBlur(grass.astype(np.float32), (0, 0), 0.8)
    pixels = np.clip(cv2.GaussianBlur(image, (3, 3), 0), 0, 255).astype(np.uint8)
    board = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float64)
    return pixels, board, float(x1 + shadow)


def test_a_shadow_the_module_casts_is_not_its_edge() -> None:
    """The outline that GrabCut gives takes the dark shadow beside the board for the board:
    the side is moved past it, to where the material changes (the board's grass), and a
    plain search for the strongest edge would have stopped at the shadow's outer edge."""
    pixels, board, outer = shadowed_board()
    seen = board.copy()
    seen[[1, 2], 0] = outer
    found = corners_.settle(pixels, seen)
    off = np.linalg.norm(corners_.clockwise(found.corners) - board, axis=1)
    # Where the shadow ends: a few px out on a step this sharp (the change is measured over 5
    # px either way), under 1 % of the 460 px wide board.
    assert float(off.max()) <= 4.0, off
    # The shadow decided it: without it the side stays at the shadow's outer edge.
    real = corners_.shadowed
    try:
        corners_.shadowed = lambda *args, **kwargs: None
        plain = corners_.settle(pixels, seen)
    finally:
        corners_.shadowed = real
    assert float(np.linalg.norm(corners_.clockwise(plain.corners) - board, axis=1).max()) > 15


FROM_ABOVE = syntetisk.Shot(size=(2000, 1500), tilt=3.0, distortion=0.0, shadow=False)


def test_a_rounded_corner_is_where_the_sides_cross() -> None:
    """The board's corners rounded off 25 mm: the corners are where the sides' lines cross,
    never the outline's own rounded point."""
    scene = syntetisk.SCENES["rak"]()
    shot = syntetisk.take(
        scene,
        syntetisk.Shot(size=(2000, 1500), tilt=3.0, distortion=0.0, shadow=False, rounded=25.0),
    )
    found = corners_.find(shot.pixels, aspect=scene.length / scene.width_a)
    assert found is not None
    truth = corners_.clockwise(np.array(shot.corners, np.float64))
    off = np.linalg.norm(corners_.clockwise(found.corners) - truth, axis=1)
    width = float(np.linalg.norm(truth[1] - truth[2]))
    # The rounded outline's own point lies (√2 - 1)·r from the corner: 10 mm here. The corner
    # found is far nearer, and within 1 % of the width (the reference photos' target).
    inset = (math.sqrt(2) - 1) * 25.0 * width / scene.width_a
    assert float(off.max()) <= min(0.01 * width, 0.2 * inset), (off, inset)


@cache
def tilted_photo() -> syntetisk.Photo:
    return syntetisk.take(
        syntetisk.SCENES["rak"](),
        syntetisk.Shot(
            size=(2000, 1500), tilt=10.0, tilt_toward=45.0, distortion=0.0, shadow=False
        ),
    )


def test_a_tilted_photo_keeps_the_modules_proportions() -> None:
    """Taken 10° from above, the module's opposite sides differ by some 13 %: an outline with a
    long side on something inside the module can look right by its plain proportions. The
    camera model (Zhang and He's rectangle) sees the module's own, and the side is found again
    where it makes them the module's."""
    scene = syntetisk.SCENES["rak"]()
    shot = tilted_photo()
    truth = corners_.clockwise(np.array(shot.corners, np.float64))
    h, w = shot.pixels.shape[:2]
    factor = corners_.WORK_SIZE / max(h, w)
    small = cv2.resize(
        shot.pixels, (round(w * factor), round(h * factor)), interpolation=cv2.INTER_AREA
    )
    outline = truth * factor
    aspect = scene.length / scene.width_a
    view = (focal_from_35mm((w, h), 26.0) * factor, (w * factor / 2, h * factor / 2))
    assert corners_.tilted(outline) > 0.1
    assert corners_._off(outline, aspect, view) <= 0.005
    sides = np.linalg.norm(np.roll(outline, -1, axis=0) - outline, axis=1)
    i = int(np.argmax(sides))
    j = (i + 1) % 4
    inward = outline.mean(axis=0) - (outline[i] + outline[j]) / 2
    inward /= np.linalg.norm(inward)
    short = float(np.linalg.norm(outline[(i + 2) % 4] - outline[j]))
    wrong = outline.copy()
    wrong[i] += inward * 0.15 * short
    wrong[j] += inward * 0.15 * short
    width = float(np.linalg.norm(truth[1] - truth[2]))
    lab, full = corners_._lab(small), corners_._lab(shot.pixels, 3)
    reach = max(4.0, corners_.SHARPEN_PX / factor)

    def off(view_: corners_.View | None) -> float:
        found = corners_.proportioned(lab, wrong, aspect, view_)
        sharp = corners_.sharpen(full, found / factor, reach)
        return float(np.linalg.norm(corners_.clockwise(sharp.corners) - truth, axis=1).max())

    # With the camera model within 1 % of the module's width; as from above, not.
    assert off(view) <= 0.01 * width, (off(view), width)
    assert off(None) > 0.01 * width


def test_a_curve_outline_missing_a_corner_is_put_right_by_its_shape() -> None:
    """A curve module whose outline missed a corner (GrabCut took scenery for the floor),
    photographed from nearly above: its shape, from the radii and the angle (the owner's chord
    and sagitta), put through the other three corners, and its sides found again along it,
    gives the corner back."""
    scene = syntetisk.SCENES["kurvmodul"]()
    shot = syntetisk.take(
        scene, syntetisk.Shot(distortion=0.0, size=(2000, 1500), shadow=False, tilt=3.0)
    )
    truth = corners_.clockwise(np.array(shot.corners, np.float64))
    assert scene.curve is not None
    radius, angle = scene.curve
    bend = corners_.Bend(radius, radius - scene.width_a, angle)
    h, w = shot.pixels.shape[:2]
    factor = corners_.WORK_SIZE / max(h, w)
    small = cv2.resize(
        shot.pixels, (round(w * factor), round(h * factor)), interpolation=cv2.INTER_AREA
    )
    wrong = truth.copy() * factor
    wrong[0] += 0.25 * (wrong.mean(axis=0) - wrong[0])
    assert corners_.bent_outline(corners_._lab(small), truth * factor, bend) is None
    outline = corners_.bent_outline(corners_._lab(small), wrong, bend)
    assert outline is not None
    placed, paths, arcs = outline
    assert sum(arcs) == 2
    found = corners_.settle(
        shot.pixels,
        placed / factor,
        [p / factor for p in paths],
        arcs,
        [corners_.SETTLE_REACH if a else corners_.GABLE_REACH for a in arcs],
    )
    off = np.linalg.norm(corners_.clockwise(found.corners) - truth, axis=1)
    width = float(np.linalg.norm(truth[0] - truth[3]))
    assert float(off.max()) <= 0.01 * width, (off, width)


# --- Sketches ---------------------------------------------------------------------------------


@cache
def depot() -> tuple[syntetisk.DepotSketch, skiss.Sheet]:
    drawn = syntetisk.depot_sketch()
    return drawn, skiss.prepare(intake.take(drawn.jpeg).pixels)


def test_a_frame_in_faint_pencil_with_a_corner_cut_is_found() -> None:
    """The frame drawn in faint pencil, under coloured pencil in places, with its corner cut:
    the lines are found and the corners are where they cross, the cut one too."""
    drawn, sheet = depot()
    truth = np.array(drawn.frame, np.float64)
    near = min(sheet.frames, key=lambda q: float(np.linalg.norm(q.mean(0) - truth.mean(0))))
    off = np.linalg.norm(skiss._clockwise(near) - skiss._clockwise(truth), axis=1)
    mm = off / syntetisk.SKETCH_PX
    assert float(mm.max()) <= skiss.SKETCH_MM, mm


def test_a_track_parting_under_a_bridge_is_a_switch_hidden_there() -> None:
    """Track 3 runs into track 2 just before a bridge drawn over the tracks (its ink a wedge, a
    switch), and under the bridge a track parts from track 2: the bridge is found from its two
    parallel lines, the tracks are joined under it by direction and place, and the end left
    over is a switch hidden under the bridge. Code is not sure of it: it is a question, and
    answered that the track ends at the bridge, it does."""
    drawn, sheet = depot()
    truth = np.array(drawn.frame, np.float64)
    corners = chain.ordered(truth, 0, 3)
    found = skiss.read(sheet.pixels, sheet.paper, corners, 1500.0, 700.0, 700.0)
    assert skiss.counts(found) == (drawn.switches, 0)
    assert {k: (q.kind, q.options) for k, q in found.asked.items()} == {
        "B1": ("bridge", ["grenar", "slutar", "vet-inte"])
    }
    marks = found.asked["B1"].marks
    assert sorted(marks) == ["A", "B", "C", "D", "E"]
    ends = skiss.read(
        sheet.pixels, sheet.paper, corners, 1500.0, 700.0, 700.0, answers={"B1": "slutar"}
    )
    assert skiss.counts(ends) == (drawn.switches - 1, 0)
    again = skiss.from_json(skiss.to_json(found), found.image)
    assert again.asked["B1"].options == found.asked["B1"].options


def _hairpin_graph() -> skiss.Graph:
    """Two tracks from gable A whose ink ran together into a wedge: thinned, one piece that
    turns back at the wedge's tip (at x 600)."""
    upper = [(float(x), 300.0 + 120.0 * ((600 - x) / 600) ** 2 * 0) for x in range(0, 601, 4)]
    lower = [(float(x), 300.0 + 40.0 * ((600 - x) / 600) ** 1.5) for x in range(600, -1, -4)]
    graph = skiss.Graph()
    graph.nodes["a"] = skiss.GNode("a", upper[0], 1)
    graph.nodes["b"] = skiss.GNode("b", lower[-1], 1)
    graph.edges["u"] = skiss.GEdge("u", "a", "b", [*upper, *lower[1:]])
    return graph


def test_a_wedge_is_a_switch_or_as_answered_two_tracks() -> None:
    """The piece that turns back at a wedge's tip is cut there into a switch with a short leg
    on, the way the two tracks were going; answered two tracks side by side, each ends where
    its own ink does; answered something else, it is left as drawn. A wedge away from a bridge
    is a question of its own (K1)."""
    graph = _hairpin_graph()
    pins = skiss.hairpins(graph, 1.0, 16.0)
    assert len(pins) == 1 and pins[0].band is None
    assert abs(pins[0].tip[0] - 600.0) <= 4.0 and pins[0].heading[0] > 0.9
    assert sorted(n.ends for n in graph.nodes.values()) == [1, 1, 1, 3]
    apart = _hairpin_graph()
    skiss.hairpins(apart, 1.0, 16.0, answers={"K1": "tva-spar"})
    assert sorted(n.ends for n in apart.nodes.values()) == [1, 1, 1, 1]
    assert all(n.at[0] < 590.0 for n in apart.nodes.values())
    left = _hairpin_graph()
    skiss.hairpins(left, 1.0, 16.0, answers={"K1": "annat"})
    assert list(left.edges) == ["u"]


def test_the_owner_is_asked_only_where_the_ai_does_not_say_what_code_reads() -> None:
    """A bridge the AI reads as code does is no question; read otherwise, or with no AI, it
    is, with both answers and the ends marked."""
    from cad import sketches

    drawn, sheet = depot()
    corners = chain.ordered(np.array(drawn.frame, np.float64), 0, 3)
    found = skiss.read(sheet.pixels, sheet.paper, corners, 1500.0, 700.0, 700.0)
    assert sketches.part_questions(found, {"B1": "grenar"}, {}) == []
    asked = sketches.part_questions(found, {"B1": "slutar"}, {})
    assert [(q.key, q.code, q.ai) for q in asked] == [("skiss:b1", "grenar", "slutar")]
    assert sketches.part_questions(found, {}, {})[0].source.value == "code"
    assert sketches.parts_decided(found, {"B1": "vet-inte"}, {}) == {"B1": "grenar"}
    assert sketches.parts_decided(found, {"B1": "slutar"}, {"skiss:b1": "grenar"}) == {
        "B1": "grenar"
    }
