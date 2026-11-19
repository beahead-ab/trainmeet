"""Att kolla (CAD-03, CAD-17): what the code finds in a drawing for the owner to answer before
the track plan is approved. Each item has a kind, a place in mm, a text and answer buttons; the
photo chain's AI questions (part c) are items of the kind question, with their fixed answers.

The rules, with the limits in cad/switches.py:

- short_rail: a free end heading for a gable (within 15° of straight at it) that stops more than
  2 mm and at most SHORT_REACH mm before it, with no joint: "Rälsen slutar 51 mm före gavel A".
  Det är en passbit adds a short piece of its own to the gable; Rälsen går ända fram lengthens the
  track to it.
- open_end: any other free end, not a buffer stop, and a gable track with no track behind it.
- switch_radius: a switch's radius at or below the scale's lower limit.
- switch_assumed: a switch of type Okänd whose radius matches no type within 10 %, antagen
  (AR3), or with no radius.
- tight_radius and kink: the AnyRail import's check (3.3): the tracks sampled every 10 mm, the
  smallest radius over 50 mm against the scale's minimum, and the largest angle jump against
  what the minimum radius turns over one step; also where two pieces meet and through a switch.
- gable_position: a gable track more than 2 mm from its gable's measure (the norm's, when the
  profile fixes it), or at a gable where the gable has no track.

An item's key holds its kind, its parts and its measured value, so an answer stays with the
version and a changed value asks again. Answers whose item is gone are dropped when saved.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator

from cad import curves, switches
from cad.curves import Line, Seg
from cad.editor import Drawing, EditError, Node
from contracts.cad import (
    NORM_NAMES,
    CheckChoice,
    CheckItem,
    CheckKind,
    GableEnd,
    ProfileKind,
)
from contracts.station_model import NodeType, Point

SHORT_GAP = 2.0
"""A rail that stops more than this short of a gable is asked about (the gable tolerance)."""
SHORT_REACH = 100.0
"""How far before a gable a free end is still a rail stopping short of it; a starting value,
as bildkedjan's limits, for a passbit at a module joint."""
SHORT_ANGLE = math.radians(15)
MEET_WITHIN = 5.0
"""A rail taken to a gable meets a free gable track within 5 mm of where it points."""
RADIUS_WINDOW = 5
"""Steps of 10 mm over which the radius is measured: 50 mm, as the AnyRail import."""

CONFIRM = CheckChoice(id="stammer", text="Det stämmer")


def find(drawing: Drawing) -> list[CheckItem]:
    """Every item, the owner's answer on those answered; open ones first, then by place."""
    found: dict[str, CheckItem] = {}
    for item in _all(drawing):
        if item.key not in found:
            answer = drawing.answers.get(item.key)
            found[item.key] = item.model_copy(update={"answer": answer}) if answer else item
    return sorted(found.values(), key=lambda c: (c.answer is not None, c.at[0], c.at[1], c.key))


def open_items(items: list[CheckItem]) -> list[CheckItem]:
    return [c for c in items if c.answer is None]


def _all(drawing: Drawing) -> Iterator[CheckItem]:
    short: set[str] = set()
    for item in _short_rails(drawing):
        short.update(item.refs[:1])
        yield item
    yield from _open_ends(drawing, short)
    yield from _switches(drawing)
    yield from _curvature(drawing)
    yield from _gables(drawing)


def _p(p: Point) -> Point:
    return (round(p[0], 1), round(p[1], 1))


def _free_ends(drawing: Drawing) -> Iterator[Node]:
    for n in drawing.nodes.values():
        if n.type == NodeType.JOINT and drawing.count(n.id) == 1:
            yield n


def _ahead_of(drawing: Drawing, node: Node) -> tuple[GableEnd, float, Point] | None:
    """The gable a free end heads for, the gap to it and where it meets it."""
    head = drawing.outward(node.id)
    if head is None:
        return None
    direction = curves.unit(head)
    for end in (GableEnd.A, GableEnd.B):
        line = drawing.gable_line(end)
        outward = (-line.inward[0], -line.inward[1])
        cos = curves.dot(direction, outward)
        if cos < math.cos(SHORT_ANGLE):
            continue
        gap = line.depth(node.at) / cos
        meet = curves.add(node.at, direction, gap)
        if 0 <= line.offset(meet) <= line.width and SHORT_GAP < gap <= SHORT_REACH:
            return end, gap, meet
    return None


def _short_rails(drawing: Drawing) -> Iterator[CheckItem]:
    for node in _free_ends(drawing):
        found = _ahead_of(drawing, node)
        if found is None:
            continue
        end, gap, _ = found
        piece = drawing.on(node.id)[0]
        yield CheckItem(
            key=f"short_rail:{node.id}:{end.value}:{gap:.0f}",
            kind=CheckKind.SHORT_RAIL,
            at=_p(node.at),
            title=f"Rälsen slutar {gap:.0f} mm före gavel {end.value}",
            text=(
                f"{drawing.name(piece).capitalize()} når inte fram till gaveln och har ingen "
                "skarv där. Är det plats för en passbit?"
            ),
            refs=[node.id, piece],
            choices=[
                CheckChoice(id="passbit", text="Det är en passbit"),
                CheckChoice(id="hela-vagen", text="Rälsen går ända fram"),
            ],
        )


def _open_ends(drawing: Drawing, short: set[str]) -> Iterator[CheckItem]:
    for node in _free_ends(drawing):
        if node.id in short:
            continue
        yield CheckItem(
            key=f"open_end:{node.id}",
            kind=CheckKind.OPEN_END,
            at=_p(node.at),
            title="Spåret slutar utan att mötas",
            text="Änden är inte ihopkopplad med något spår, och den är ingen stoppbock.",
            refs=[node.id, *drawing.on(node.id)],
            choices=[
                CheckChoice(id="stoppbock", text="Det är en stoppbock"),
                CheckChoice(id="slutar", text="Spåret slutar här"),
            ],
        )
    if not drawing.pieces:
        return  # A module from measures whose tracks wait for the photo: nothing drawn yet.
    for node in drawing.nodes.values():
        if node.type == NodeType.MODULE_JOINT and drawing.count(node.id) == 0:
            assert node.gable is not None
            yield CheckItem(
                key=f"open_end:{node.id}",
                kind=CheckKind.OPEN_END,
                at=_p(node.at),
                title=f"Gavel {node.gable.value} · spår {node.track or '?'} går inte in i modulen",
                text="Gavelspåret har inget spår i ritningen. Rita det, eller svara att det "
                "slutar vid gaveln.",
                refs=[node.id],
                choices=[CheckChoice(id="slutar", text="Spåret slutar vid gaveln")],
            )


def _switches(drawing: Drawing) -> Iterator[CheckItem]:
    limits = switches.limits(drawing.scale)
    choose = CheckChoice(id="valj-typ", text="Välj växeltyp", closes=False, action="design")
    right = CheckChoice(id="radien-stammer", text="Radien stämmer")
    for sw in drawing.switches.values():
        at = _p(drawing.nodes[sw.node].at)
        name = f"Växel {sw.number or sw.id}"
        if sw.radius is not None and sw.radius <= limits.switch_min_radius + 0.5:
            where = "vid" if sw.radius >= limits.switch_min_radius - 0.5 else "under"
            yield CheckItem(
                key=f"switch_radius:{sw.id}:{sw.radius:.0f}",
                kind=CheckKind.SWITCH_RADIUS,
                at=at,
                title=f"{name}: radien blev {sw.radius:.0f} mm",
                text=(
                    f"Det är {where} nedre gränsen, {limits.switch_min_radius:.0f} mm i "
                    f"{drawing.scale.value}. Välj växeltyp så används rätt radie."
                ),
                refs=[sw.id, sw.node],
                choices=[choose, right],
                assumed=True,
            )
            continue
        if sw.design is not None:
            continue
        if switches.match(sw.radius, sw.angle, drawing.scale) is not None:
            continue
        radius = f"R {sw.radius:.0f} mm" if sw.radius is not None else "radien okänd"
        yield CheckItem(
            key=f"switch_assumed:{sw.id}:{sw.radius or 0:.0f}",
            kind=CheckKind.SWITCH_ASSUMED,
            at=at,
            title=f"{name} är antagen, {radius}",
            text=(
                "Radien passar ingen känd växeltyp inom 10 %. Välj växeltyp, eller bekräfta radien."
            ),
            refs=[sw.id, sw.node],
            choices=[choose, right],
            assumed=True,
        )


def _turns(segs: list[Seg]) -> tuple[list[Point], list[float]]:
    """The track every 10 mm, and the heading of each step between."""
    points = curves.sample_path(segs, switches.SAMPLE_STEP)
    heads = [curves.heading(a, b) for a, b in itertools.pairwise(points)]
    return points, heads


def _curvature(drawing: Drawing) -> Iterator[CheckItem]:
    limits = switches.limits(drawing.scale)
    track_kink = math.radians(limits.kink + 0.05)
    legs = {s.diverging for s in drawing.switches.values()}
    for piece in drawing.pieces.values():
        # A switch's diverging leg is held to the switches' lower limit, which has its own item.
        minimum = limits.switch_min_radius if piece.id in legs else limits.min_radius
        kink = math.radians(math.degrees(switches.SAMPLE_STEP / minimum) + 0.05)
        points, heads = _turns(piece.segs)
        if len(heads) < 2:
            continue
        jumps = [abs(curves.wrap(b - a)) for a, b in itertools.pairwise(heads)]
        tightest, tight_at = math.inf, points[0]
        for k in range(len(heads) - RADIUS_WINDOW):
            turn = abs(curves.wrap(heads[k + RADIUS_WINDOW] - heads[k]))
            run = math.dist(points[k], points[k + 1]) * RADIUS_WINDOW
            if turn > 1e-9 and run / turn < tightest:
                tightest, tight_at = run / turn, points[k + RADIUS_WINDOW // 2 + 1]
        if tightest < minimum - 1:
            rounded = round(tightest / 10) * 10
            yield CheckItem(
                key=f"tight_radius:{piece.id}:{rounded:.0f}",
                kind=CheckKind.TIGHT_RADIUS,
                at=_p(tight_at),
                title=f"Snäv radie: R {tightest:.0f} mm",
                text=(
                    f"Under minsta radien {minimum:.0f} mm i {drawing.scale.value}, mätt över "
                    "50 mm."
                ),
                refs=[piece.id],
                choices=[CONFIRM],
            )
            continue
        worst = max(range(len(jumps)), key=lambda k: jumps[k])
        if jumps[worst] > kink:
            yield _kink(piece.id, points[worst + 1], jumps[worst], [piece.id])
    for node in drawing.nodes.values():
        for a, b in _through(drawing, node):
            jump = abs(curves.wrap(curves.start_heading(b[0]) - curves.end_heading(a[-1])))
            if jump > track_kink:
                yield _kink(node.id, node.at, jump, [node.id])


def _through(drawing: Drawing, node: Node) -> Iterator[tuple[list[Seg], list[Seg]]]:
    """The ways a train runs through the node: into it on one piece, out on another."""
    on = drawing.on(node.id)
    if node.type == NodeType.JOINT and len(on) == 2:
        yield curves.reverse_path(drawing.away(on[0], node.id)), drawing.away(on[1], node.id)
    sw = drawing.switch_at(node.id)
    if sw is not None and sw.trunk and sw.straight and sw.diverging:
        into = curves.reverse_path(drawing.away(sw.trunk, node.id))
        yield into, drawing.away(sw.straight, node.id)
        yield into, drawing.away(sw.diverging, node.id)


def _kink(ref: str, at: Point, jump: float, refs: list[str]) -> CheckItem:
    degrees = math.degrees(jump)
    return CheckItem(
        key=f"kink:{ref}:{degrees:.1f}",
        kind=CheckKind.KINK,
        at=_p(at),
        title=f"Knyck {degrees:.1f}°".replace(".", ","),
        text="Spåret byter riktning mer än minsta radien tillåter på 10 mm.",
        refs=refs,
        choices=[CONFIRM],
    )


def _gables(drawing: Drawing) -> Iterator[CheckItem]:
    tolerance = switches.GABLE_TOLERANCE
    for node in drawing.nodes.values():
        if node.type != NodeType.MODULE_JOINT or node.gable is None:
            continue
        line = drawing.gable_line(node.gable)
        offset = line.offset(node.at)
        gable = drawing.gable(node.gable)
        lock_it = CheckChoice(id="las", text="Lås måttet", closes=False, action="lock")
        keep = CheckChoice(id="behall", text="Behåll läget")
        if node.track is None or node.track > len(gable.tracks):
            yield CheckItem(
                key=f"gable_position:{node.id}:{offset:.1f}",
                kind=CheckKind.GABLE_POSITION,
                at=_p(node.at),
                title=(
                    f"Gavel {node.gable.value}: ett spår {offset:.0f} mm från Kant 1 som gaveln "
                    "inte har"
                ),
                text="Gavelns mått har inget spår här. Ändra gavelns mått, eller behåll läget.",
                refs=[node.id],
                choices=[keep],
            )
            continue
        expected = gable.tracks[node.track - 1]
        if abs(offset - expected) <= tolerance:
            continue
        profile = drawing.known.get(gable.profile) if gable.profile else None
        says = "Gavelns mått"
        if profile is not None and profile.kind == ProfileKind.NORM and profile.norm is not None:
            says = f"{NORM_NAMES[profile.norm]}-normen"
        yield CheckItem(
            key=f"gable_position:{node.id}:{offset:.1f}",
            kind=CheckKind.GABLE_POSITION,
            at=_p(node.at),
            title=(
                f"Gavel {node.gable.value} · spår {node.track} ligger {offset:.0f} mm från Kant 1"
            ),
            text=f"{says} säger {expected:g} mm. Lås måttet så räknas kurvan om.",
            refs=[node.id],
            choices=[lock_it, keep],
        )


# --- What an answer does --------------------------------------------------------------------


def effect(drawing: Drawing, item: CheckItem, answer: str) -> None:
    """What the answer changes in the drawing; most only settle the item."""
    if item.kind == CheckKind.OPEN_END and answer == "stoppbock":
        drawing.nodes[item.refs[0]].type = NodeType.BUFFER_STOP
    elif item.kind == CheckKind.SHORT_RAIL and answer in ("passbit", "hela-vagen"):
        _to_gable(drawing, item.refs[0], separate=answer == "passbit")


def _to_gable(drawing: Drawing, node_id: str, *, separate: bool) -> None:
    """The rail taken to the gable: a passbit of its own, or the track itself lengthened."""
    node = drawing.nodes[node_id]
    found = _ahead_of(drawing, node)
    if found is None:
        raise EditError("Änden går inte mot en gavel.")
    end, _, meet = found
    line = drawing.gable_line(end)
    # A gable track within a few mm of where the rail would meet the gable is the one it meets.
    near = [
        (math.dist(n.at, meet), n.id)
        for n in drawing.nodes.values()
        if n.type == NodeType.MODULE_JOINT
        and n.gable == end
        and drawing.count(n.id) == 0
        and math.dist(n.at, meet) <= MEET_WITHIN
    ]
    target = min(near)[1] if near else None
    if target is not None:
        meet = drawing.nodes[target].at
    if separate:
        piece = drawing.add_piece([Line(node.at, meet)], node_id, target)
        piece.track = "passbit"
        return
    piece_id = drawing.on(node_id)[0]
    piece = drawing.pieces[piece_id]
    toward = drawing.away(piece_id, drawing.other(piece_id, node_id))
    toward.append(Line(node.at, meet))
    piece.segs = toward if piece.end == node_id else curves.reverse_path(toward)
    drawing.lines.pop(piece_id, None)
    if target is not None:
        if piece.start == node_id:
            piece.start = target
        else:
            piece.end = target
        del drawing.nodes[node_id]
        return
    node.at = meet
    node.type = NodeType.MODULE_JOINT
    node.gable = end
    node.track = drawing.gable_track(end, line.offset(meet))
