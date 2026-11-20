"""CAD:s anläggning på utkastet (CAD-11, CAD-30, K4): the places and lengths CAD's assembly gives
Bana, laid on the draft each time it is read again, as the stations are coupled.

What Integrationer read from the assembly (AssemblyLayout) is matched to the plan:

- A place in the assembly is the plan's driftplats with the same name or signature as a station
  in TKL that uses its modules, or coupled to the same station; else the planner says which, and
  the answer is kept. One that is no driftplats of the plan is left out.
- A section of the plan between two matched places gets its length: the assembly's tracks from
  one place to the other, through the matched places along the section (its parts), in the
  model's mm, and in the prototype's metres at the assembly's scale. The length is its own fact,
  trolig, with the assembly as its origin; the planner may confirm it.
- Where the assembly says something else than the plan, it is a question, never a silent change
  (CAD-30): a section the assembly has no tracks for, tracks the plan has no section for, and
  single or double track. The plan's places and sections stay the plan's (CAD-09); the answer on
  single or double track is laid on the section.
- With every place on the map matched, Bana is drawn where the assembly has the places: CAD's
  assembly comes first for the map (import 5).
- The assembly as it came goes with the package as an attachment, to the Pi (CAD-12).
"""

from __future__ import annotations

import heapq
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from contracts.common import Id
from contracts.meet import Attachment, AttachmentKind, MapPoint, Place, Section, TrackKind
from contracts.planning import (
    Alternative,
    AssemblyLayout,
    AssemblyLink,
    Certainty,
    Fact,
    Origin,
    Question,
    SectionLength,
    Source,
)

CAD_PLACE: Final = "cad_place"
CAD_SECTION: Final = "cad_section"
CAD_TRACKS: Final = "cad_tracks"
CAUSES: Final = frozenset({CAD_PLACE, CAD_SECTION, CAD_TRACKS})
NONE: Final = "none"
"""The answer that a place of the assembly is no driftplats of the plan."""
PLAN: Final = "plan"
ATTACHMENT: Final = "cad-anlaggning"
"""The attachment's id in the package: the assembly as CAD gave it."""
MEDIA_TYPE: Final = "application/json"
MAP_SIZE: Final = 220.0
"""How wide the assembly's longer side is drawn on Bana's map, in the map's units."""


MAP: Final = "display:map"
"""The fact that Bana's map stands where the assembly has the places."""


def is_cad_fact(ref: str) -> bool:
    """A fact only the assembly gives: a section's length, a place's modules, and the map."""
    return (
        ref == MAP
        or (ref.startswith("section:") and ref.endswith(".length"))
        or (ref.startswith("place:") and ref.endswith(".modules"))
    )


@dataclass
class Laid:
    """What the assembly gives the draft."""

    sections: dict[Id, Section]
    facts: list[Fact] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    lengths: list[SectionLength] = field(default_factory=list)
    layout: dict[Id, MapPoint] | None = None
    attachment: Attachment | None = None
    matched: dict[Id, Id] = field(default_factory=dict)
    """The plan's driftplats → the assembly's place."""


def _key(text: str) -> str:
    return " ".join(text.casefold().split())


def _question_id(prefix: str, name: str) -> str:
    return (prefix + re.sub(r"[^A-Za-z0-9]+", "-", name))[:80]


def _fmt_mm(mm: float) -> str:
    return f"{round(mm):,}".replace(",", "\N{NO-BREAK SPACE}")


def _metres(mm: float, ratio: float) -> str:
    metres = mm * ratio / 1000
    return f"{metres:.0f}" if metres >= 100 else f"{metres:.1f}".replace(".", ",")


def _match(
    places: Mapping[Id, Place], layout: AssemblyLayout, answers: Mapping[str, str]
) -> tuple[dict[Id, Id], list[Question]]:
    """The plan's driftplats for each place of the assembly: the planner's answer first, then by
    a station's name, signature or id; the rest are asked about."""
    matched: dict[Id, Id] = {}
    taken: set[Id] = set()
    ids = {p.id: _question_id("cad-plats-", p.id) for p in layout.places}
    for place in layout.places:
        answer = answers.get(ids[place.id])
        if answer is not None and answer != NONE and answer in places and answer not in taken:
            matched[place.id] = answer
            taken.add(answer)
    for place in layout.places:
        if place.id in matched or answers.get(ids[place.id]) == NONE:
            continue
        names = {_key(s) for s in place.stations}
        found = [
            p.id
            for p in places.values()
            if p.id not in taken
            and (
                _key(p.name) in names
                or _key(p.code) in names
                or (
                    p.station is not None
                    and (
                        p.station.station_id in place.station_ids
                        or _key(p.station.outside.name) in names
                    )
                )
            )
        ]
        if len(found) == 1:
            matched[place.id] = found[0]
            taken.add(found[0])
    questions: list[Question] = []
    free = [p for p in places.values() if p.id not in taken]
    for place in layout.places:
        answer = answers.get(ids[place.id])
        if place.id in matched and answer is None:
            continue
        if not free and answer is None:
            continue
        options = [p for p in places.values() if p.id not in taken or matched.get(place.id) == p.id]
        questions.append(
            Question(
                id=ids[place.id],
                cause=CAD_PLACE,
                message=f"Vilken driftplats i planen är {place.name} i anläggningen "
                f"{layout.name} ({', '.join(place.modules)[:200]})?",
                refs=[f"place:{matched[place.id]}"] if place.id in matched else [],
                alternatives=[
                    *[Alternative(value=p.id, label=f"{p.code} · {p.name}") for p in options],
                    Alternative(value=NONE, label="Ingen driftplats i planen"),
                ],
                answer=answer if answer in {*places, NONE} else None,
            )
        )
    return matched, questions


def _chain(section: Section) -> list[Id]:
    """The section's places in order: its ends, with the places of its parts between."""
    if not section.parts:
        return [section.place_a, section.place_b]
    return [section.parts[0].from_place, *[part.to_place for part in section.parts]]


def lay(
    places: Mapping[Id, Place],
    sections: Mapping[Id, Section],
    layout: AssemblyLayout,
    answers: Mapping[str, str],
    source: Source | None,
) -> Laid:
    """The assembly on the plan's places and sections."""
    origin = source.id if source is not None else layout.source
    matched, questions = _match(places, layout, answers)
    to_plan = dict(matched)
    of_plan = {plan: cad for cad, plan in matched.items()}
    cad_places = {p.id: p for p in layout.places}
    through = {(t.place, frozenset((t.a, t.b))): t.length for t in layout.through if t.a != t.b}
    laid = Laid(sections=dict(sections), questions=questions, matched=dict(of_plan))
    used: set[Id] = set()
    at = f"Anläggningen {layout.name}, revision {layout.revision}"
    for plan_id, cad_id in sorted(of_plan.items()):
        laid.facts.append(
            Fact(
                ref=f"place:{plan_id}.modules",
                certainty=Certainty.LIKELY,
                origins=[
                    Origin(source=origin, at=f"{at}: {', '.join(cad_places[cad_id].modules)}"[:500])
                ],
            )
        )

    def name(place: Id) -> str:
        found = places.get(place)
        return found.name if found is not None else place

    by_place: dict[Id, list[AssemblyLink]] = {}
    for link in layout.links:
        by_place.setdefault(link.a, []).append(link)
        if link.b != link.a:
            by_place.setdefault(link.b, []).append(link)

    def shortest(start: Id, goal: Id, passable: set[Id]) -> tuple[float, list[AssemblyLink]] | None:
        """The shortest way along the assembly's tracks between two of its places, through
        places that are passable, each taken from one link to another by its own tracks."""
        count = 0
        queue: list[tuple[float, int, Id, str | None, list[AssemblyLink]]] = [
            (0.0, count, start, None, [])
        ]
        best: dict[tuple[Id, str | None], float] = {}
        while queue:
            far, _, place, came, way = heapq.heappop(queue)
            if place == goal and came is not None:
                return far, way
            if best.get((place, came), math.inf) <= far:
                continue
            best[(place, came)] = far
            for link in by_place.get(place, []):
                if link.id == came:
                    continue
                step = 0.0
                if came is not None:
                    found = through.get((place, frozenset((came, link.id))))
                    if found is None:
                        continue
                    step = found
                onward = link.b if link.a == place else link.a
                if onward != goal and onward not in passable:
                    continue
                count += 1
                heapq.heappush(
                    queue, (far + step + link.length, count, onward, link.id, [*way, link])
                )
        return None

    for section in sections.values():
        chain = _chain(section)
        if chain[0] not in of_plan or chain[-1] not in of_plan or chain[0] == chain[-1]:
            continue
        # Through the places of the assembly that are no other driftplats of the plan.
        elsewhere = {cad for plan, cad in of_plan.items() if plan not in chain}
        passable = {p.id for p in layout.places} - elsewhere
        found = shortest(of_plan[chain[0]], of_plan[chain[-1]], passable)
        length, way = found if found is not None else (None, [])
        title = f"{name(section.place_a)} – {name(section.place_b)}"
        if length is not None and length <= 0:
            continue  # the places meet gable to gable: no line between them
        if length is None:
            question_id = _question_id("cad-stracka-", section.id)
            questions.append(
                Question(
                    id=question_id,
                    cause=CAD_SECTION,
                    message=f"Anläggningen {layout.name} har inga spår mellan {title}, men planen "
                    "har sträckan. Planen gäller; rätta anläggningen i CAD om banan har spåren.",
                    refs=[f"section:{section.id}"],
                    alternatives=[Alternative(value=PLAN, label="Planen gäller")],
                    answer=answers.get(question_id) if answers.get(question_id) == PLAN else None,
                )
            )
            continue
        used.update(link.id for link in way)
        tracks = min(link.tracks for link in way)
        modules = [m for link in way for m in link.modules]
        laid.lengths.append(
            SectionLength(
                section=section.id,
                length=round(length, 1),
                prototype=round(length * layout.ratio / 1000, 1),
                tracks=tracks,
                links=[link.id for link in way],
            )
        )
        laid.facts.append(
            Fact(
                ref=f"section:{section.id}.length",
                certainty=Certainty.LIKELY,
                origins=[
                    Origin(
                        source=origin,
                        at=(f"{at}: " + (", ".join(modules) or "gavel mot gavel"))[:500],
                    )
                ],
                note=f"{_fmt_mm(length)} mm längs spåret i modellen, "
                f"{_metres(length, layout.ratio)} m i {layout.scale}.",
            )
        )
        cad_double = tracks >= 2
        question_id = _question_id("cad-spar-", section.id)
        answer = answers.get(question_id)
        if cad_double != (section.tracks == TrackKind.DOUBLE) or answer is not None:
            questions.append(
                Question(
                    id=question_id,
                    cause=CAD_TRACKS,
                    message=f"Anläggningen {layout.name} har "
                    f"{'dubbelspår' if cad_double else 'enkelspår'} mellan {title}. Planen har "
                    f"{'dubbelspår' if section.tracks == TrackKind.DOUBLE else 'enkelspår'}.",
                    refs=[f"section:{section.id}"],
                    alternatives=[
                        Alternative(value=TrackKind.SINGLE.value, label="Enkelspår"),
                        Alternative(value=TrackKind.DOUBLE.value, label="Dubbelspår"),
                    ],
                    answer=answer if answer in {k.value for k in TrackKind} else None,
                )
            )
            if answer in {k.value for k in TrackKind}:
                laid.sections[section.id] = section.model_copy(update={"tracks": TrackKind(answer)})
    for link in layout.links:
        one, two = to_plan.get(link.a), to_plan.get(link.b)
        if link.id in used or one is None or two is None or one == two:
            continue
        question_id = _question_id("cad-spar-utan-stracka-", f"{min(one, two)}-{max(one, two)}")
        if any(q.id == question_id for q in questions):
            continue
        questions.append(
            Question(
                id=question_id,
                cause=CAD_SECTION,
                message=f"Anläggningen {layout.name} har spår mellan {name(one)} och {name(two)}, "
                "men planen har ingen sträcka där. Planen gäller; lägg till sträckan i planen om "
                "tågen ska köra där.",
                refs=[f"place:{one}", f"place:{two}"],
                alternatives=[Alternative(value=PLAN, label="Planen gäller")],
                answer=answers.get(question_id) if answers.get(question_id) == PLAN else None,
            )
        )
    drawn = {s.place_a for s in sections.values()} | {s.place_b for s in sections.values()}
    drawn |= {
        p for s in sections.values() for part in s.parts for p in (part.from_place, part.to_place)
    }
    if len(drawn) > 1 and drawn <= set(of_plan):
        spots = {plan: cad_places[cad].at for plan, cad in of_plan.items()}
        left = min(p.x for p in spots.values())
        top = min(p.y for p in spots.values())
        wide = max(max(p.x for p in spots.values()) - left, max(p.y for p in spots.values()) - top)
        scale = MAP_SIZE / wide if wide > 0 else 1.0
        laid.layout = {
            plan: MapPoint(x=round((p.x - left) * scale, 2), y=round((p.y - top) * scale, 2))
            for plan, p in sorted(spots.items())
        }
        laid.facts.append(
            Fact(
                ref=MAP,
                certainty=Certainty.LIKELY,
                origins=[Origin(source=origin, at=f"{at}: platsernas lägen")],
                note="Kartan i Bana står där anläggningen har driftplatserna.",
            )
        )
    if source is not None:
        laid.attachment = Attachment(
            id=ATTACHMENT,
            kind=AttachmentKind.OTHER,
            filename=source.filename,
            media_type=MEDIA_TYPE,
            size=source.size,
            sha256=source.sha256,
        )
    return laid
