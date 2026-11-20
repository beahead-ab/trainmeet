"""A synthetic assembly for the tests of Studio's Från CAD (#89 del d2): what CAD's Till TKL Studio
sends, made by CAD's own code, before and after a change.

    python -m cad.assembly_example <before.json> <after.json>

Before: a straight module with a switch at 400 mm whose diverging leg ends inside the module, and
a straight line module joined at its gable B, whose track the owner numbered 1 in CAD. After: the
line module at its next version, 300 mm shorter with its ids kept (CAD-20), and a third module
joined behind it. Studio's re-import shows the line's piece moved and the third module's piece
added. Nothing here is a real station.
"""

from __future__ import annotations

import itertools
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from cad import assembly, editor, graph
from contracts.cad import (
    DrawingState,
    EditOp,
    Gable,
    GableEnd,
    Joint,
    JointEnd,
    Scale,
    Straight,
    StudioGraph,
    StudioModule,
    StudioSource,
    StudioSourceKind,
)

NAMESPACE = uuid.UUID("6f1d3c2a-9b8e-4f70-a1b2-c3d4e5f60718")
ASSEMBLY = uuid.uuid5(NAMESPACE, "exempelanlaggning")
TRACK = 140.0


def _gables() -> tuple[Gable, Gable]:
    return (Gable(end=GableEnd.A, tracks=[TRACK]), Gable(end=GableEnd.B, tracks=[TRACK]))


def _line(name: str, number: int, length: float, version: int = 1) -> assembly.Member:
    shape = Straight(length=length, width=500)
    gables = _gables()
    previous = graph.from_measures(Straight(length=1500, width=500), gables)
    made = graph.from_measures(shape, gables, (previous, gables))
    # The owner numbered the line's track in CAD: Studio makes it a station track.
    made = made.model_copy(
        update={"pieces": [p.model_copy(update={"track": "1"}) for p in made.pieces]}
    )
    return assembly.Member(
        module=uuid.uuid5(NAMESPACE, name),
        version=version,
        number=f"M-{number:03d}",
        name=name,
        scale=Scale.H0,
        shape=shape,
        gables=gables,
        graph=made,
    )


def _with_switch() -> assembly.Member:
    shape = Straight(length=1500, width=500)
    gables = _gables()
    drawn = editor.Drawing.of(
        Scale.H0, shape, list(gables), graph.from_measures(shape, gables), DrawingState()
    )
    piece = next(iter(drawn.pieces))
    ops = [
        {
            "op": "switch",
            "piece": piece,
            "from_a": 400,
            "radius": 830,
            "angle": 11.4,
            "side": "right",
        }
    ]
    drawn.apply_all(TypeAdapter(list[EditOp]).validate_python(ops))
    return assembly.Member(
        module=uuid.uuid5(NAMESPACE, "Infart"),
        version=1,
        number="M-001",
        name="Infart",
        scale=Scale.H0,
        shape=shape,
        gables=gables,
        graph=drawn.graph(),
    )


def _joint(a: assembly.Member, b: assembly.Member) -> Joint:
    return Joint(
        a=JointEnd(module=a.module, gable=GableEnd.B), b=JointEnd(module=b.module, gable=GableEnd.A)
    )


def example(after: bool = False) -> StudioGraph:
    """What Till TKL Studio sends for the synthetic assembly, before or after the change."""
    members = [_with_switch(), _line("Linje", 2, 1200 if after else 1500, 2 if after else 1)]
    if after:
        members.append(_line("Linje bortom", 3, 1000))
    joints = [_joint(a, b) for a, b in itertools.pairwise(members)]
    placement = assembly.place(members, [assembly.Pose()] * len(members), joints)
    by_id = {m.module: m for m in members}
    checks = [assembly.check(k, j, by_id, placement) for k, j in enumerate(joints)]
    assert all(c.fits for c in checks)
    source = StudioSource(
        kind=StudioSourceKind.ASSEMBLY,
        id=ASSEMBLY,
        name="Exempelanläggning",
        scale=Scale.H0,
        owner="Provkonto A",
        revision=3 if after else 2,
        modules=[
            StudioModule(id=m.module, number=m.number, name=m.name, version=m.version)
            for m in members
        ],
        ready=True,
        changed_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
    )
    return StudioGraph(source=source, graph=assembly.graph(members, placement, joints, checks))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    for path, after in ((argv[1], False), (argv[2], True)):
        Path(path).write_text(example(after).model_dump_json(indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
