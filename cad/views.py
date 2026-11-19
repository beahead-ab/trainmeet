"""What Ritningen and Lås mått show (CAD-03, CAD-24): the working drawing with its Att kolla,
the switch inspector's facts and the numbers under the canvas, and Lås mått's proposal."""

from __future__ import annotations

import math
import statistics
from uuid import UUID

from cad import checks, curves, smoothing, switches
from cad.editor import Drawing, LockPlan
from contracts.cad import (
    NORM_NAMES,
    UNKNOWN_DESIGN,
    Deviation,
    DrawingStats,
    DrawingView,
    GableEnd,
    LockGable,
    LockMeasures,
    LockPart,
    LockProposal,
    ProfileKind,
    SwitchInfo,
)
from contracts.station_model import NodeType


def _end_name(drawing: Drawing, node: str) -> str:
    n = drawing.nodes[node]
    if n.type == NodeType.MODULE_JOINT and n.gable is not None:
        return f"{n.gable.value}{n.track}" if n.track is not None else f"gavel {n.gable.value}"
    if n.type == NodeType.SWITCH:
        sw = drawing.switch_at(node)
        return f"växel {sw.number}" if sw is not None and sw.number else "en växel"
    if n.type == NodeType.BUFFER_STOP:
        return "stoppbocken"
    return "änden"


def _follow(drawing: Drawing, piece: str, start: str) -> str:
    """Where a track leads, from start along piece: through joints, and through switches along
    their through track, to a gable, an end or a switch reached on its diverging leg."""
    seen: set[str] = set()
    current_piece, at = piece, drawing.other(piece, start)
    while current_piece not in seen:
        seen.add(current_piece)
        n = drawing.nodes[at]
        on = [p for p in drawing.on(at) if p != current_piece]
        if n.type == NodeType.JOINT and len(on) == 1:
            current_piece = on[0]
        elif n.type == NodeType.SWITCH:
            sw = drawing.switch_at(at)
            if sw is None:
                break
            if current_piece in (sw.straight, sw.diverging) and sw.trunk:
                current_piece = sw.trunk
            elif current_piece == sw.trunk and sw.straight:
                current_piece = sw.straight
            else:
                break
        else:
            break
        at = drawing.other(current_piece, at)
    return _end_name(drawing, at)


def switch_infos(drawing: Drawing) -> list[SwitchInfo]:
    found: list[SwitchInfo] = []
    for sw in drawing.switches.values():
        node = drawing.nodes[sw.node]
        assert sw.trunk is not None and sw.diverging is not None
        source = _follow(drawing, sw.trunk, sw.node)
        target = _follow(drawing, sw.diverging, sw.node)
        first = drawing.away(sw.diverging, sw.node)[0]
        matched = switches.match(sw.radius, sw.angle, drawing.scale)
        found.append(
            SwitchInfo(
                id=sw.id,
                number=sw.number or sw.id,
                leaves=f"spår från {source} mot {target}",
                from_a=round(drawing.from_a(node.at), 1),
                radius=round(sw.radius, 1) if sw.radius else None,
                angle=round(sw.angle, 2) if sw.angle else None,
                side="right" if curves.turn_of(first) >= 0 else "left",
                toward=sw.toward,
                design=sw.design or UNKNOWN_DESIGN,
                matched=matched.id if matched is not None else None,
                assumed=sw.design is None and matched is None,
                locked=sw.locked,
                at=(round(node.at[0], 1), round(node.at[1], 1)),
                origin=sw.origin,
            )
        )
    return found


def stats(drawing: Drawing) -> DrawingStats:
    total = sum(curves.path_length(p.segs) for p in drawing.pieces.values())
    distances: list[float] = []
    for piece_id, line in drawing.lines.items():
        piece = drawing.pieces.get(piece_id)
        if piece is not None:
            distances.extend(curves.distance(piece.segs, p) for p in line.points)
    deviation = (
        Deviation(
            median=round(statistics.median(distances), 2),
            max=round(max(distances), 2),
            count=len(distances),
        )
        if distances
        else None
    )
    return DrawingStats(
        track_length=round(total, 1), switches=len(drawing.switches), deviation=deviation
    )


def view(module: UUID, base: int, latest: int, drawing: Drawing) -> DrawingView:
    return DrawingView(
        module=module,
        base=base,
        latest=latest,
        scale=drawing.scale,
        shape=drawing.shape,
        gables=drawing.gables,
        graph=drawing.graph(),
        drawing=drawing.state(),
        checks=checks.find(drawing),
        switches=switch_infos(drawing),
        designs=switches.designs(drawing.scale),
        smoothing_levels=smoothing.levels(drawing.scale),
        limits=switches.limits(drawing.scale),
        stats=stats(drawing),
        changed=drawing.changed,
    )


def _says(drawing: Drawing, end: GableEnd, track: int) -> tuple[str, str | None]:
    """Who says where the track goes: the norm when its profile fixes it, else the gable."""
    gable = drawing.gable(end)
    profile = drawing.known.get(gable.profile) if gable.profile else None
    if (
        profile is not None
        and profile.kind == ProfileKind.NORM
        and profile.norm is not None
        and profile.first is not None
        and track == 1
    ):
        return f"{NORM_NAMES[profile.norm]}-normen säger", profile.name
    return "Gaveln säger", profile.name if profile is not None else None


def _mm(value: float) -> str:
    return f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}".replace(".", ",")


def lock_proposal(drawing: Drawing, op: LockMeasures, plan: LockPlan) -> LockProposal:
    ga, gb = drawing.gable(GableEnd.A), drawing.gable(GableEnd.B)
    says_a, profile_a = _says(drawing, GableEnd.A, plan.track_a)
    _, profile_b = _says(drawing, GableEnd.B, plan.track_b)
    gables = [
        LockGable(
            gable=GableEnd.A,
            track=plan.track_a,
            value=plan.a,
            line=round(plan.a_line, 1),
            norm=ga.norm,
            profile=profile_a,
        ),
        LockGable(
            gable=GableEnd.B,
            track=plan.track_b,
            value=plan.b,
            line=round(plan.b_line, 1),
            norm=gb.norm,
            profile=profile_b,
        ),
    ]
    old = [(round(x, 1), round(y, 1)) for x, y in plan.old]
    if plan.solution is None:
        return LockProposal(
            solved=False, why=plan.why, radii=plan.radii, gables=gables, old=old, lock=op
        )
    solution = plan.solution
    t = solution.template
    if t.r1 == 0:
        parts = [
            LockPart(kind="straight", label="Rakt från gavel A till gavel B", length=t.s1, angle=0)
        ]
    else:
        turn_b = math.degrees(abs(t.t1 + t.t2))
        parts = [
            LockPart(kind="straight", label="Rakt från gavel A", length=t.s1, angle=0),
            LockPart(
                kind="arc",
                label="Båge",
                length=t.r1 * abs(t.t1),
                radius=t.r1,
                angle=math.degrees(abs(t.t1)),
            ),
            LockPart(kind="straight", label="Rakt", length=t.s2, angle=math.degrees(abs(t.t1))),
            LockPart(
                kind="arc",
                label="Båge",
                length=t.r2 * abs(t.t2),
                radius=t.r2,
                angle=math.degrees(abs(t.t2)),
            ),
            LockPart(kind="straight", label="Rakt till gavel B", length=t.s3, angle=turn_b),
        ]
    parts = [
        p.model_copy(
            update={
                "length": round(max(0.0, p.length), 1),
                "radius": round(p.radius, 1) if p.radius else None,
                "angle": round(p.angle, 2),
            }
        )
        for p in parts
    ]
    off = max(abs(plan.a_line - plan.a), abs(plan.b_line - plan.b))
    if off < 0.05:
        why = (
            f"Linjen ligger redan {_mm(plan.a)} och {_mm(plan.b)} mm från Kant 1. Kurvan räknas "
            "om till raka bitar och bågar."
        )
    elif plan.a == plan.b:
        why = (
            f"{says_a} {_mm(plan.a)} mm från Kant 1. Linjen låg {_mm(off)} mm ifrån, så måttet "
            "låses och kurvan räknas om."
        )
    else:
        why = (
            f"Gavel A låses på {_mm(plan.a)} mm och gavel B på {_mm(plan.b)} mm från Kant 1. "
            f"Linjen låg {_mm(off)} mm ifrån, så kurvan räknas om."
        )
    deviation = Deviation(
        median=round(solution.median, 2),
        max=round(solution.worst, 2),
        count=len(solution.deviation),
    )
    return LockProposal(
        solved=True,
        why=why,
        radii=plan.radii,
        gables=gables,
        parts=parts,
        old=old,
        new=[curves.segment(s) for s in solution.segs],
        tangents=[(round(s.start[0], 1), round(s.start[1], 1)) for s in solution.segs[1:]],
        deviation=deviation,
        lock=op,
    )
