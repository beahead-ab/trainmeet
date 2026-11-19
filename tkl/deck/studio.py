"""Studio, Inställningar, Stream Deck, the tab Sidor (#86 del c, SD38–SD45), as data for the page.

For one size: the owner's profile (the default with the deviations laid on), every page's keys
drawn as the deck on the screen draws them against an empty interlocking, Att kolla, Studio's
checks (SD44), and the list Knappar (SD41): what the station model has, by group, each with where
it is on the deck now, or that it is not reached. The sizes to choose from each say how many
decks on this computer have that size and how many changes and Att kolla the owner has there.

Pure Python without I/O. No code here names a station (RS13).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from contracts.tkl import (
    DeckAction,
    DeckButtonGroup,
    DeckKeyType,
    DeckModelId,
    Panel,
    RouteKind,
    TklDeckButton,
    TklDeckDeviation,
    TklDeckFace,
    TklDeckKey,
    TklDeckProfile,
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
from tkl.deck.profile import build, frame, geography_of
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
PLACEHOLDER_BG: Final = "#1f2328"
PLACEHOLDER_FG: Final = "#9ca3af"
FACE_TYPES: Final = frozenset(
    {
        "train",
        "line",
        "alarm",
        "track",
        "place",
        "part",
        "signal",
        "daily",
        "favourite",
        "tile",
        "cell",
        "pan",
        "mode",
        "next",
        "page",
        "action",
        "panel",
        "route",
    }
)


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
    return TklDeckFace(
        type=key.type.value if key.type.value in FACE_TYPES else "empty",
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


def buttons(profile: TklDeckProfile, plant: Plant, geo: Geography) -> list[TklDeckButton]:
    """Knappar (SD41): the station's keys by group, each with where it is on the deck."""
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
) -> list[TklDeckSize]:
    """The sizes to choose from, each with its decks here, its changes and its Att kolla."""
    counted: dict[DeckModelId, int] = {}
    for model in decks:
        size = size_of(model)
        if size is not None:
            counted[size] = counted.get(size, 0) + 1
    geo = geography_of(plant, panel)
    known_here = known_of(plant, geo)
    found = []
    for size in SIZES:
        known = BY_ID[size]
        mine = kept.get(size, [])
        used = bool(mine) or counted.get(size, 0) > 0
        applied = owned(plant, panel, known.grid, size, mine) if used else None
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
) -> TklDeckStudio:
    """Sidor for one size: the owner's profile with Att kolla, the checks and Knappar."""
    geo = geography_of(plant, panel)
    known: Known = known_of(plant, geo)
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
    )


def default_of(plant: Plant, panel: Panel | None, size: DeckModelId) -> TklDeckProfile:
    return build(plant, panel, BY_ID[size].grid, size)


__all__ = [
    "SIZES",
    "buttons",
    "default_of",
    "deviations_for",
    "faces",
    "size_of",
    "sizes",
    "view",
]
