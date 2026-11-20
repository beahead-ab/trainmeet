"""Anläggningen as pure geometry (CAD-06, CAD9, CAD-10, CAD-20): placing modules gable to gable,
the joint checks, the angles, and the track graph of the whole with its stable ids."""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest

from cad import assembly, assembly_example, geometry, graph
from contracts.cad import (
    JOINT_TOLERANCE,
    Curve,
    Gable,
    GableEnd,
    Joint,
    JointCheck,
    JointEnd,
    Norm,
    Scale,
    Shape,
    Straight,
    StudioGraph,
)
from contracts.station_model import NodeType

EXAMPLE = (
    Path(__file__).resolve().parents[2] / "contracts" / "examples" / "exempel.studio-graph.json"
)

A, B = GableEnd.A, GableEnd.B


def member(
    shape: Shape,
    a: list[float],
    b: list[float] | None = None,
    *,
    norm_a: Norm | None = None,
    norm_b: Norm | None = None,
    name: str = "Linje",
) -> assembly.Member:
    gables = (
        Gable(end=A, tracks=a, norm=norm_a),
        Gable(end=B, tracks=a if b is None else b, norm=norm_b),
    )
    return assembly.Member(
        module=uuid.uuid4(),
        version=1,
        number="M-001",
        name=name,
        scale=Scale.H0,
        shape=shape,
        gables=gables,
        graph=graph.from_measures(shape, gables),
    )


def straight(a: list[float], b: list[float] | None = None, **extra: object) -> assembly.Member:
    return member(Straight(length=1000, width=500), a, b, **extra)  # type: ignore[arg-type]


def joint(
    first: assembly.Member,
    end_a: GableEnd,
    second: assembly.Member,
    end_b: GableEnd,
    angle: float = 0,
) -> Joint:
    return Joint(
        a=JointEnd(module=first.module, gable=end_a),
        b=JointEnd(module=second.module, gable=end_b),
        angle=angle,
    )


def placed(
    members: Sequence[assembly.Member], joints: Sequence[Joint]
) -> tuple[assembly.Placement, list[JointCheck]]:
    found = assembly.place(members, [assembly.Pose()] * len(members), joints)
    by_id = {m.module: m for m in members}
    return found, [assembly.check(k, j, by_id, found) for k, j in enumerate(joints)]


def close(p: tuple[float, float], q: tuple[float, float], within: float = 1e-6) -> bool:
    return math.dist(p, q) <= within


def test_a_module_meets_the_next_gable_to_gable_and_the_joint_fits() -> None:
    first, second = straight([140]), straight([140])
    found, (result,) = placed([first, second], [joint(first, B, second, A)])
    assert found.placed == {first.module: "first", second.module: "joint"}
    pose = found.poses[second.module]
    assert close(pose.at, (1000, 0)) and pose.angle == 0
    assert result.fits and result.problems == [] and result.gap == 0 and not result.closing


def test_a_to_a_turns_the_second_module_round_and_measures_its_tracks_from_the_far_edge() -> None:
    first = straight([140])
    # Turned round, its Kant 1 lies on the other side: its track 360 from Kant 1 is 140 from
    # the first's Kant 1 in a gable 500 wide.
    turned = straight([360])
    found, (result,) = placed([first, turned], [joint(first, B, turned, B)])
    pose = found.poses[turned.module]
    assert abs(abs(pose.angle) - 180) < 1e-9
    assert close(pose.point((1000, 360)), (1000, 140), 1e-6)
    assert result.fits
    wrong = straight([140])
    _, (refused,) = placed([first, wrong], [joint(first, B, wrong, B)])
    assert not refused.fits and refused.gap == pytest.approx(220)
    assert refused.problems == ["Spår 1 möts inte: 220,0 mm isär, högst 1,0 mm."]


def test_gables_that_do_not_fit_are_a_problem_with_the_reason() -> None:
    first = straight([140], norm_b=Norm.FREMO)
    two = straight([140, 197], norm_a=Norm.MMM)
    _, (result,) = placed([first, two], [joint(first, B, two, A)])
    assert not result.fits
    assert result.problems == [
        "Gavel B på M-001 Linje har ett spår och gavel A på M-001 Linje har 2 spår.",
        "Gavlarna följer olika normer: FREMO och MMM.",
    ]
    # Within the tolerance: two gables each 0,5 mm from the norm meet.
    near = straight([140 + JOINT_TOLERANCE])
    _, (fits,) = placed([first, near], [joint(first, B, near, A)])
    assert fits.fits and fits.gap == pytest.approx(JOINT_TOLERANCE)
    beyond = straight([141.2])
    _, (off,) = placed([first, beyond], [joint(first, B, beyond, A)])
    assert not off.fits and off.problems == ["Spår 1 möts inte: 1,2 mm isär, högst 1,0 mm."]


def test_a_curve_gives_the_angle_and_a_joint_may_add_one() -> None:
    bend = geometry.from_chord(1035, 68)
    curve = member(Curve(radius=bend.radius, angle=bend.angle, width=500), [140], name="Kurva")
    first, after = straight([140]), straight([140])
    found, checks = placed(
        [first, curve, after], [joint(first, B, curve, A), joint(curve, B, after, A)]
    )
    assert all(c.fits for c in checks)
    # Kant 1 is the outer edge: the curve turns right seen from gable A, clockwise on screen.
    assert found.poses[after.module].angle == pytest.approx(-bend.angle)
    kinked, (check,) = placed([first, after], [joint(first, B, after, A, angle=5)])
    assert kinked.poses[after.module].angle == pytest.approx(5)
    # It turns about the track in the joint, which still meets.
    assert close(kinked.poses[after.module].point((0, 140)), (1000, 140), 1e-6)
    assert check.fits


def test_a_joint_that_closes_a_loop_is_checked_as_it_lies() -> None:
    curves = [
        member(Curve(radius=2000, angle=30, width=500), [140], name=f"Kurva {n}") for n in range(12)
    ]
    joints = [joint(curves[n], B, curves[(n + 1) % 12], A) for n in range(12)]
    found, checks = placed(curves, joints)
    assert found.closing == frozenset({11})
    assert all(c.fits for c in checks) and checks[11].closing and checks[11].gap < 1e-6
    # Eleven curves and a joint back to the first do not close.
    short = curves[:11]
    gap = [*joints[:10], joint(short[10], B, short[0], A)]
    _, open_ = placed(short, gap)
    assert not open_[-1].fits and open_[-1].turn == pytest.approx(30, abs=1e-6)
    assert any(p.startswith("Skarven sluter inte") for p in open_[-1].problems)


def test_a_module_no_joint_reaches_lies_where_the_owner_put_it() -> None:
    first, alone = straight([140]), straight([140])
    found = assembly.place(
        [first, alone], [assembly.Pose(), assembly.Pose(at=(0, 900), angle=90)], []
    )
    assert found.placed[alone.module] == "free"
    assert found.poses[alone.module] == assembly.Pose(at=(0, 900), angle=90)


def test_the_graph_joins_the_modules_with_stable_ids_and_placed_geometry() -> None:
    first, second = straight([140, 197]), straight([140, 197])
    joints = [joint(first, B, second, A)]
    found, checks = placed([first, second], joints)
    made = assembly.graph([first, second], found, joints, checks)
    assert made.geometry == "mm" and made.complete
    # Four gable tracks at the joint are two nodes; every id is the module's id and its own.
    assert len(made.nodes) == 6 and len(made.pieces) == 4
    for piece in made.pieces:
        module, _, own = piece.id.partition(":")
        assert own in {p.id for p in first.graph.pieces} and uuid.UUID(module)
    joined = [n for n in made.nodes if sum(n.id in (p.start, p.end) for p in made.pieces) == 2]
    assert len(joined) == 2 and all(n.type == NodeType.MODULE_JOINT for n in joined)
    ends = {n.id: n.at for n in made.nodes}
    second_pieces = [p for p in made.pieces if p.id.startswith(str(second.module))]
    assert {ends[p.start] for p in second_pieces} == {(1000, 140), (1000, 197)}
    assert {p.segments[-1].end for p in second_pieces} == {(2000, 140), (2000, 197)}
    # The same assembly again, or with the modules listed the other way, has the same ids.
    other, other_checks = placed([second, first], joints)
    again = assembly.graph([second, first], other, joints, other_checks)
    assert {n.id for n in again.nodes} == {n.id for n in made.nodes}
    assert {p.id for p in again.pieces} == {p.id for p in made.pieces}


def test_a_joint_that_does_not_fit_is_not_joined_in_the_graph() -> None:
    first, second = straight([140]), straight([150])
    joints = [joint(first, B, second, A)]
    found, checks = placed([first, second], joints)
    made = assembly.graph([first, second], found, joints, checks)
    assert len(made.nodes) == 4


def test_tracks_a_little_apart_meet_in_the_middle_and_the_pieces_end_there() -> None:
    bend = geometry.from_chord(1035, 68)
    curve = member(Curve(radius=bend.radius, angle=bend.angle, width=500), [140, 197])
    first = straight([140, 197.8])
    joints = [joint(first, B, curve, A)]
    found, checks = placed([first, curve], joints)
    assert checks[0].fits and checks[0].gap == pytest.approx(0.8)
    made = assembly.graph([first, curve], found, joints, checks)
    middle = next(n for n in made.nodes if abs(n.at[1] - 197.4) < 1e-6)
    touching = [p for p in made.pieces if middle.id in (p.start, p.end)]
    assert len(touching) == 2
    for piece in touching:
        at = piece.segments[0].start if piece.start == middle.id else piece.segments[-1].end
        assert at == middle.at


def test_the_contracts_example_is_what_till_tkl_studio_sends() -> None:
    """contracts/examples/exempel.studio-graph.json is made by CAD's own code, and Studio's tests
    and browser test read it; after the change the line is shorter with its ids kept (CAD-20)."""
    before = assembly_example.example()
    assert StudioGraph.model_validate_json(EXAMPLE.read_text(encoding="utf-8")) == before
    after = assembly_example.example(after=True)
    old = {p.id: p for p in before.graph.pieces}
    new = {p.id: p for p in after.graph.pieces}
    assert set(old) < set(new) and len(new) == len(old) + 1
    moved = [i for i in old if old[i].segments != new[i].segments]
    assert len(moved) == 1 and new[moved[0]].track == "1"
