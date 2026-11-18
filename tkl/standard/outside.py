"""The station's outside, derived from its model (STD-08, TKL92).

Studio writes the model and Ställverket reads it. What the meet sees, the outside
(trainmeet.station-outside/1), is computed from the model's station tracks and line exits; while a
station has a model, nobody writes it by hand. The same model always gives the same outside.

Ids. The outside's ids are stable ids (contracts.common.Id), but the model's names are the owner's
free text, such as an exit called "Väst 1". An item's id in the outside is its `outside_id` when
the model gives one, so that the owner can rename it and keep the id the meets know. Otherwise
it is derived from the name: a name that already is an id stays as it is; any other is folded to
ASCII (å, ä → a, ö → o, é → e), each run of characters an id cannot hold becomes "-", and the
ends are trimmed. Two items that get the same id are told apart with -2, -3 and so on, in the
model's order; an `outside_id` always keeps its own. The owner's text stays as the track's label
and the exit's name, with the neighbouring station after it when the model knows it, so that
the hub can tie the exit to its section by the neighbour's name (H26).

Sides. An exit's side is the end of the station it lies at on the panel, built from the
station's own track plan or else laid out by the engine: west is left and east is right, as
the box shows them (Side). The panel draws every piece from west to east, so the way the exit's
piece leaves the exit node says it: an exit whose piece runs east into the station is at the
west end.

Tracks. An exit's tracks are the station tracks the model gives for it. Where it gives none, or
names something that is not a station track, they are found through the graph: a walk from the
exit into the station that goes through switches and slips only the way a train can (trunk to
leg, along a slip's paths) and stops at the first piece of a station track on each way, at
buffer stops, at other exits and at the turntable. A planned switch is not built, so the walk
does not pass it. The station tracks the walk stops at are the exit's tracks, in the model's
order.

The boxes' sides (`sides`) are left out, as at level 0: neither first start nor the list in
Studio writes them, and Planering works them out when the outside has none (F3).

Pure Python without I/O, using only the contracts and the engine. No code here names a station
(RS13).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Final

from contracts.common import Side
from contracts.station_model import LineExit, StationModel, SwitchControl
from contracts.station_outside import Exit, StationOutside, StationTrack
from contracts.tkl import Panel
from tkl.standard import plan
from tkl.standard.graph import Graph, Step
from tkl.standard.layout import LayoutError, lay_out

ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}")
"""contracts.common.Id."""
ID_LENGTH: Final = 80
TEXT_LENGTH: Final = 500
"""contracts.common.Text."""
NOT_IN_ID: Final = re.compile(r"[^A-Za-z0-9._:-]+")
UNFOLDED: Final = str.maketrans({"æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "ß": "ss"})
"""Letters that Unicode does not split into a letter and a mark."""
TRACKS: Final = "stationsspår"
EXITS: Final = "linjeutfarter"


class OutsideError(Exception):
    """The model gives no outside: the problems say why, in Swedish."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = problems


def outside_id(name: str) -> str:
    """The id a name gives in the outside; empty when nothing of it can be used."""
    if ID.fullmatch(name):
        return name
    split = unicodedata.normalize("NFKD", name.translate(UNFOLDED))
    folded = "".join(c for c in split if not unicodedata.combining(c))
    return _trimmed(NOT_IN_ID.sub("-", folded))


def _trimmed(text: str) -> str:
    """An id starts with a letter or a digit and does not end with "-"."""
    return text[:ID_LENGTH].lstrip("._:-").rstrip("-")


def _numbered(base: str, number: int) -> str:
    suffix = f"-{number}"
    return _trimmed(base[: ID_LENGTH - len(suffix)]) + suffix


def _ids(items: Sequence[tuple[str, str | None]]) -> list[str]:
    """Each item's id in the outside, from its name and its own id, in the model's order."""
    taken = {given for _, given in items if given}
    found: list[str] = []
    for name, given in items:
        if given:
            found.append(given)
            continue
        base = outside_id(name)
        made, number = base, 2
        while made in taken:
            made, number = _numbered(base, number), number + 1
        taken.add(made)
        found.append(made)
    return found


def track_ids(model: StationModel) -> dict[str, str]:
    """Each station track's id in the outside, by its name in the model."""
    found = _ids([(t.id, t.outside_id) for t in model.station_tracks])
    return dict(zip((t.id for t in model.station_tracks), found, strict=True))


def exit_ids(model: StationModel) -> dict[str, str]:
    """Each line exit's id in the outside, by its name in the model."""
    found = _ids([(e.id, e.outside_id) for e in model.line_exits])
    return dict(zip((e.id for e in model.line_exits), found, strict=True))


def _repeated(names: Iterable[str]) -> list[str]:
    return [name for name, count in Counter(names).items() if count > 1]


def problems(model: StationModel) -> list[str]:
    """Why the model gives no outside, before the panel is made; empty when it may."""
    found: list[str] = []
    if not model.station_tracks:
        found.append(
            "Stationsmodellen har inga stationsspår. Stationens utsida räknas fram ur "
            "stationsspåren och linjeutfarterna (TKL92)."
        )
    if not model.line_exits:
        found.append(
            "Stationsmodellen har inga linjeutfarter. Stationens utsida räknas fram ur "
            "stationsspåren och linjeutfarterna (TKL92)."
        )
    for word, own in (
        (TRACKS, [t.outside_id for t in model.station_tracks if t.outside_id]),
        (EXITS, [e.outside_id for e in model.line_exits if e.outside_id]),
    ):
        found += [f"Två {word} har samma id i utsidan: {x}." for x in _repeated(own)]
    for line in model.line_exits:
        if not line.outside_id and not outside_id(line.id):
            found.append(
                f"Linjeutfarten {line.id} ger inget id i utsidan: namnet har inga bokstäver "
                "eller siffror som går att använda. Ge den ett eget id för utsidan."
            )
    return found


def outside_of(
    model: StationModel, station_id: str, name: str, *, panel: Panel | None = None
) -> StationOutside:
    """The station's outside from its model, under the station's own id and name.

    panel: the station's panel, when the caller has made it already. Raises OutsideError when
    the model gives no outside.
    """
    found = problems(model)
    if found:
        raise OutsideError(found)
    if panel is None:
        panel = _panel(model)
    graph = Graph(model)
    tracks = _ids([(t.id, t.outside_id) for t in model.station_tracks])
    outside_of_track = dict(zip((t.id for t in model.station_tracks), tracks, strict=True))
    exits: list[Exit] = []
    trouble: list[str] = []
    for line, exit_id in zip(
        model.line_exits, _ids([(e.id, e.outside_id) for e in model.line_exits]), strict=True
    ):
        try:
            side = _side(line, graph, panel)
        except OutsideError as error:
            trouble += error.problems
            continue
        exits.append(
            Exit(
                id=exit_id,
                side=side,
                name=_name(line),
                tracks=[outside_of_track[t] for t in _tracks(model, graph, line)],
                signals=list(line.signals),
            )
        )
    if trouble:
        raise OutsideError(trouble)
    return StationOutside(
        station_id=station_id,
        name=name,
        tracks=[
            StationTrack(id=track_id, label=track.label)
            for track, track_id in zip(model.station_tracks, tracks, strict=True)
        ],
        exits=exits,
    )


def _name(line: LineExit) -> str:
    """The owner's name of the exit, with the neighbour after it when the model knows it."""
    said = f"{line.id} mot {line.neighbour}" if line.neighbour else line.id
    return said[:TEXT_LENGTH]


def _panel(model: StationModel) -> Panel:
    """The panel the sides are read from: the station's own track plan, else the engine's."""
    try:
        return plan.build(model) if model.panel is not None else lay_out(model)
    except plan.PlanError as error:
        raise OutsideError(error.problems) from error
    except LayoutError as error:
        raise OutsideError([f"Motorn kan inte lägga ut panelen. {error}"]) from error


def _side(line: LineExit, graph: Graph, panel: Panel) -> Side:
    """West (left) or east (right) on the panel; OutsideError when it cannot be told."""
    pieces = graph.touching.get(line.node, [])
    if len(pieces) != 1:
        raise OutsideError([f"Linjeutfarten {line.id} ska ha en spårbit men har {len(pieces)}."])
    piece = graph.pieces[pieces[0]]
    drawn = next((p for p in panel.lines if p.piece == piece.id), None)
    if drawn is None:
        raise OutsideError(
            [
                f"Linjeutfarten {line.id} syns inte på panelen, så det går inte att säga om den "
                "ligger åt väster eller öster."
            ]
        )
    cells = drawn.cells if piece.start == line.node else list(reversed(drawn.cells))
    x = cells[0][0]
    for cell in cells[1:]:
        if abs(cell[0] - x) > 1e-9:
            return Side.LEFT if cell[0] > x else Side.RIGHT
    raise OutsideError(
        [
            f"Linjeutfarten {line.id} går rakt upp eller ner på panelen, så det går inte att "
            "säga om den ligger åt väster eller öster."
        ]
    )


def _tracks(model: StationModel, graph: Graph, line: LineExit) -> list[str]:
    """The station tracks that reach the exit, by their names in the model."""
    names = [t.id for t in model.station_tracks]
    if line.tracks and set(line.tracks) <= set(names):
        return [t for t in names if t in line.tracks]
    track_of = {piece: t.id for t in model.station_tracks for piece in t.pieces}
    reached: set[str] = set()
    seen: set[Step] = set()
    stack = [graph.leaving(piece, line.node) for piece in graph.touching.get(line.node, [])]
    while stack:
        step = stack.pop()
        if step in seen:
            continue
        seen.add(step)
        track = track_of.get(step.piece)
        if track is not None:
            reached.add(track)
            continue
        for move in graph.moves(step):
            if move.switch is None or move.switch.control != SwitchControl.PLANNED:
                stack.append(move.step)
    return [t for t in names if t in reached]
