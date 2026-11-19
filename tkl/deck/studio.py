"""Studio, Inställningar, Stream Deck, the tab Sidor (#86 del c, SD38–SD45), as data for the page.

For one size: the owner's profile (the default with the deviations laid on), every page's keys
drawn as the deck on the screen draws them against an empty interlocking, Att kolla, Studio's
checks (SD44), and the list Knappar (SD41): what the station model has, by group, each with where
it is on the deck now, or that it is not reached. The sizes to choose from each say how many
decks on this computer have that size and how many changes and Att kolla the owner has there.

A part's deck, Bangård (#87 del d), has its own sizes, without the pedal (TKL122), its own
deviations and its own Knappar: the part's tracks with their streets, its routes out and the
shunter's functions. The checks are the part's (tkl.deck.checks.yard_check).

Pure Python without I/O. No code here names a station (RS13).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from contracts.station_model import PartSide
from contracts.tkl import (
    DeckAction,
    DeckButtonGroup,
    DeckDial,
    DeckFaceType,
    DeckKeyType,
    DeckModelId,
    Panel,
    RouteKind,
    TklDeckButton,
    TklDeckDeviation,
    TklDeckFace,
    TklDeckKey,
    TklDeckProfile,
    TklDeckRole,
    TklDeckRoute,
    TklDeckSettings,
    TklDeckSize,
    TklDeckStudio,
    TklDeckStudioPage,
)
from tkl.deck import checks, logic
from tkl.deck.deviations import (
    ACTION_NAMES,
    ARROW,
    TYPE_NAMES,
    Applied,
    Known,
    identity,
    known_of,
    owned,
    ref_key,
    ref_of,
)
from tkl.deck.models import BY_ID
from tkl.deck.places import Geography
from tkl.deck.profile import build, frame, geography_of, yard_tracks
from tkl.stallverk import Interlocking, Plant
from tkl.standard import RouteKind as EngineKind

K = DeckKeyType
A = DeckAction
G = DeckButtonGroup
M = DeckModelId
SIZES: Final = (M.MINI, M.NEO, M.FIFTEEN, M.XL, M.PLUS, M.PLUS_XL, M.STUDIO, M.PEDAL)
"""The sizes with a profile of their own (SD54): the Modules and the older editions get theirs."""
FUNCTIONS: Final = (
    A.RELEASE,
    A.ARRIVED,
    A.RUN,
    A.CANCEL,
    A.BACK,
    A.LOCK,
    A.RELEASE_ALL,
    A.RESET,
    A.EMERGENCY,
)
YARD_SIZES: Final = tuple(s for s in SIZES if s != M.PEDAL)
"""A part's deck: the pedal has none (TKL122)."""
YARD_FUNCTIONS: Final = (
    A.GIVE_BACK,
    A.DONE,
    A.RING,
    A.GATES,
    A.HORN,
    A.FIKA,
    A.CLOCK,
    A.REQUESTS,
    A.RUN,
)
"""The shunter's functions in Knappar (SD61, RANG-04)."""
END_WORDS: Final = {PartSide.LEFT: "vänster", PartSide.RIGHT: "höger"}
PLACEHOLDER_BG: Final = "#1f2328"
PLACEHOLDER_FG: Final = "#9ca3af"
FACE_OF: Final[dict[DeckKeyType, DeckFaceType]] = {
    K.TRAIN: "train",
    K.LINE: "line",
    K.ALARM: "alarm",
    K.TRACK: "track",
    K.PLACE: "place",
    K.PART: "part",
    K.SIGNAL: "signal",
    K.DAILY: "daily",
    K.FAVOURITE: "favourite",
    K.TILE: "tile",
    K.CELL: "cell",
    K.PAN: "pan",
    K.MODE: "mode",
    K.NEXT: "next",
    K.PAGE: "page",
    K.ACTION: "action",
    K.PANEL: "panel",
    K.ROUTE: "route",
    K.END: "end",
    K.STREET: "street",
    K.REQUEST: "request",
    K.READY: "train",
}
"""The face a key gets in Studio when it follows the traffic: what kind of key it is."""


def size_of(model: DeckModelId | None) -> DeckModelId | None:
    """The size whose profile a model gets (SD54); None for a grid TKL does not know."""
    return BY_ID[model].size if model is not None else None


def deviations_for(
    sizes: dict[DeckModelId, list[TklDeckDeviation]], model: DeckModelId | None
) -> list[TklDeckDeviation]:
    size = size_of(model)
    return list(sizes.get(size, [])) if size is not None else []


def _placeholder(key: TklDeckKey) -> TklDeckFace:
    """A key whose face follows the traffic, as Studio shows it: what it is and its number."""
    name = TYPE_NAMES.get(key.type, key.type.value)
    if key.type == K.ACTION and key.action is not None:
        name = ACTION_NAMES[key.action]
    under = str(key.slot) if key.slot else ""
    if key.track:
        name = key.track
    return TklDeckFace(
        type=FACE_OF.get(key.type, "empty"),
        text=key.text or name,
        under=key.under or under,
        bg=PLACEHOLDER_BG,
        fg=PLACEHOLDER_FG,
        label=f"{name} {under}".strip(),
    )


def faces(profile: TklDeckProfile, plant: Plant, geo: Geography) -> list[list[TklDeckFace]]:
    """Every page's keys as the deck draws them, against an empty interlocking."""
    world = logic.World(plant=plant, geo=geo, interlocking=Interlocking(plant))
    settings = TklDeckSettings(serial="studio", grid=profile.grid, model=profile.model)
    selection = logic.Selection()
    found = []
    for i, page in enumerate(profile.pages):
        deck = logic.Deck(settings=settings, profile=profile, mode=page.mode, page=i)
        shown = []
        for key in page.keys:
            face = logic.face(deck, selection, world, page, key)
            if key is not None and (face.type == "empty" or (not face.text and not face.tile)):
                face = _placeholder(key)
            shown.append(face)
        found.append(shown)
    return found


def _where(profile: TklDeckProfile, key: TklDeckKey) -> str:
    wanted = identity(key)
    fixed = set(frame(profile.grid).fixed.values())
    for page in profile.pages:
        for cell, k in enumerate(page.keys):
            if k is not None and identity(k) == wanted:
                return "fast rad" if cell in fixed else page.name
    if any(k is not None and identity(k) == wanted for k in profile.pedals):
        return "pedal"
    return ""


def _route_pieces(plant: Plant, route: TklDeckRoute) -> list[str]:
    chains = plant.candidates(EngineKind(route.kind.value), route.start, route.end)
    if not chains:
        return []
    return [piece for way in chains[0] for piece in way.pieces]


def yard_buttons(profile: TklDeckProfile, plant: Plant) -> list[TklDeckButton]:
    """Knappar for the shunter's deck (#87 del d): the train key, the part's tracks and routes
    out, a key that follows Ände and one for each end, and the shunter's functions."""
    found: list[TklDeckButton] = []
    part = plant.parts.get(profile.part or "")
    reached = checks.yard_reach(profile)

    def add(group: DeckButtonGroup, key: TklDeckKey, text: str, missing: bool = False) -> None:
        where = _where(profile, key)
        if not where and key.type == K.REQUEST and DeckDial.REQUEST in reached.dials:
            where = "ratten"
        found.append(
            TklDeckButton(
                group=group,
                key=key,
                text=text,
                where=where or ("läggs på skärmen" if group == G.YARD_TRACKS else "dra hit"),
                missing=missing,
            )
        )

    add(G.TRAFFIC, TklDeckKey(type=K.READY), TYPE_NAMES[K.READY])
    if part is not None:
        for kind, group, items in (
            (K.STREET, G.YARD_TRACKS, list(part.streets.values())),
            (K.REQUEST, G.YARD_OUTS, list(part.routes_out.values())),
        ):
            for track in yard_tracks(items):
                unreached = [
                    item
                    for item in items
                    if item.track == track.track
                    and (kind == K.REQUEST or track.through)
                    and not reached.has(kind, item.track, item.side)
                ]
                add(group, TklDeckKey(type=kind, track=track.track), track.track, bool(unreached))
                for side in (PartSide.LEFT, PartSide.RIGHT):
                    if side in track.sides:
                        text = f"{track.track} från {END_WORDS[side]}"
                        add(group, TklDeckKey(type=kind, track=track.track, side=side), text)
    add(G.FUNCTIONS, TklDeckKey(type=K.END), TYPE_NAMES[K.END])
    for action in YARD_FUNCTIONS:
        add(G.FUNCTIONS, TklDeckKey(type=K.ACTION, action=action), ACTION_NAMES[action])
    add(G.FUNCTIONS, TklDeckKey(type=K.MODE), "Läge")
    return found


def buttons(profile: TklDeckProfile, plant: Plant, geo: Geography) -> list[TklDeckButton]:
    """Knappar (SD41): the station's keys by group, each with where it is on the deck."""
    if profile.part is not None:
        return yard_buttons(profile, plant)
    found: list[TklDeckButton] = []

    def add(group: DeckButtonGroup, key: TklDeckKey, text: str) -> None:
        where = _where(profile, key)
        found.append(TklDeckButton(group=group, key=key, text=text, where=where or "dra hit"))

    for key in (
        TklDeckKey(type=K.TRAIN, slot=1),
        TklDeckKey(type=K.LINE, slot=1),
        TklDeckKey(type=K.ALARM),
        TklDeckKey(type=K.DAILY, slot=1),
        TklDeckKey(type=K.FAVOURITE, slot=1),
    ):
        add(G.TRAFFIC, key, TYPE_NAMES[key.type])
    reached = checks.reach(profile)
    pages = profile.pages
    for route in checks.routes_of(plant):
        group = G.TRAIN_ROUTES if route.kind == RouteKind.TRAIN else G.SHUNTING_ROUTES
        key = TklDeckKey(type=K.ROUTE, route=route)
        way = checks.how(route, reached, plant, geo)
        quick = _where(profile, key)
        if quick:
            where = f"snabbväg · {quick}"
        elif way is not None:
            where = f"{way[0]} · {pages[way[1]].name}" if way[1] < len(pages) else way[0]
        else:
            where = "nås inte"
        found.append(
            TklDeckButton(
                group=group,
                key=key,
                text=f"{route.start} {ARROW} {route.end}",
                where=where,
                missing=way is None and bool(pages),
                pieces=_route_pieces(plant, route),
            )
        )
    one_line = sum(1 for p in geo.places if p.kind == "exit") == 1
    for place in geo.places:
        kind = K.TRACK if one_line and place.kind == "track" else K.PLACE
        add(G.PLACES, TklDeckKey(type=kind, place=place.id), place.name)
    for point in sorted((p for p in geo.points if p.start), key=lambda p: (p.x, p.y)):
        add(G.SIGNALS, TklDeckKey(type=K.SIGNAL, point=point.name), point.name)
    for action in FUNCTIONS:
        add(G.FUNCTIONS, TklDeckKey(type=K.ACTION, action=action), ACTION_NAMES[action])
    for name in sorted(plant.functions):
        add(G.FUNCTIONS, TklDeckKey(type=K.PANEL, function=name), name)
    add(G.FUNCTIONS, TklDeckKey(type=K.MODE), "Läge")
    add(G.FUNCTIONS, TklDeckKey(type=K.PAGE), "Nästa sida")
    return found


def sizes(
    plant: Plant,
    panel: Panel | None,
    kept: dict[DeckModelId, list[TklDeckDeviation]],
    decks: Iterable[DeckModelId | None],
    part: str | None = None,
) -> list[TklDeckSize]:
    """The sizes to choose from, each with its decks here, its changes and its Att kolla. A
    part's deck has no pedal (TKL122)."""
    counted: dict[DeckModelId, int] = {}
    for model in decks:
        size = size_of(model)
        if size is not None:
            counted[size] = counted.get(size, 0) + 1
    geo = geography_of(plant, panel)
    known_here = known_of(plant, geo, part)
    found = []
    for size in YARD_SIZES if part is not None else SIZES:
        known = BY_ID[size]
        mine = kept.get(size, [])
        used = bool(mine) or counted.get(size, 0) > 0
        applied = owned(plant, panel, known.grid, size, mine, part) if used else None
        # The checks for every size the station uses: a deck here has it, or the owner changed it.
        problems = (
            len(checks.check(applied.profile, plant, geo, known_here).problems)
            if applied is not None
            else 0
        )
        found.append(
            TklDeckSize(
                size=size,
                name=known.name,
                grid=known.grid,
                decks=counted.get(size, 0),
                deviations=len(mine),
                to_check=len(applied.to_check) if applied is not None else 0,
                problems=problems,
            )
        )
    return found


def view(
    size: DeckModelId,
    plant: Plant,
    panel: Panel | None,
    deviations: list[TklDeckDeviation],
    applied: Applied,
    *,
    saved: bool,
    all_sizes: list[TklDeckSize],
    message: str | None = None,
    roles: list[TklDeckRole] | None = None,
) -> TklDeckStudio:
    """Sidor for one size: the owner's profile with Att kolla, the checks and Knappar; for a
    part's deck the shunter's (#87 del d)."""
    geo = geography_of(plant, panel)
    part = applied.profile.part
    known: Known = known_of(plant, geo, part)
    profile = applied.profile
    drawn = faces(profile, plant, geo)
    pages = [
        TklDeckStudioPage(
            ref=ref_of(page), faces=drawn[i], changed=ref_key(ref_of(page)) in applied.changed
        )
        for i, page in enumerate(profile.pages)
    ]
    return TklDeckStudio(
        size=size,
        sizes=all_sizes,
        profile=profile,
        pages=pages,
        deviations=deviations,
        saved=saved,
        to_check=applied.to_check,
        checks=checks.check(profile, plant, geo, known),
        buttons=buttons(profile, plant, geo),
        message=message,
        part=part,
        roles=roles or [],
    )


def default_of(
    plant: Plant, panel: Panel | None, size: DeckModelId, part: str | None = None
) -> TklDeckProfile:
    return build(plant, panel, BY_ID[size].grid, size, part)


def roles_of(plant: Plant) -> list[TklDeckRole]:
    """The roles a deck can have: the tågklarerare, and every part of the station (#87)."""
    found = [TklDeckRole(part=None, name="Tågklareraren")]
    found += [TklDeckRole(part=p.id, name=p.name) for p in plant.parts.values()]
    return found


__all__ = [
    "SIZES",
    "YARD_SIZES",
    "buttons",
    "default_of",
    "deviations_for",
    "faces",
    "roles_of",
    "size_of",
    "sizes",
    "view",
]
