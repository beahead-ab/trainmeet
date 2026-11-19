"""Föreslå in Studio (#86 del c, SD45): a page made again by a rule.

- Geografiskt: as the default lays the page out, west to east (SD2). A page of the owner's own
  gets its keys in the same order: by where their route, place or signal is on the panel.
- Dagens vägar: a snabbväg for each of today's routes, the entry and the exit of every train on
  its planned track, from TKL's runtime data (SD23, SD49).
- Mest använda: a snabbväg for each counted route, the most used first (SD24). Only routes are
  counted, never people.

The result is the owner's deviations for the size with the page made again: what the owner
changed on other pages stays, and so does Att kolla (SD40). Navigation keys (Läge, ▶) and the
fixed row stay where they are.

Pure Python without I/O. No code here names a station (RS13).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from contracts.tkl import (
    DeckKeyType,
    DeckPageRef,
    DeckSuggestion,
    RouteKind,
    TklDeckDeviation,
    TklDeckKey,
    TklDeckProfile,
    TklDeckRoute,
)
from tkl.deck.deviations import ARROW, Known, apply, diff, ref_of, same_ref
from tkl.deck.places import Geography
from tkl.deck.profile import frame
from tkl.deck.trains import Daily
from tkl.stallverk import Plant
from tkl.standard import RouteKind as EngineKind

K = DeckKeyType
STAYS: Final = frozenset({K.MODE, K.NEXT, K.PAGE})
"""Keys a suggestion leaves where they are: they turn the pages and the modes."""


class NoSuggestion(Exception):
    """Nothing to make the page of: the reason in Swedish."""


def daily_routes(daily: Iterable[Daily], plant: Plant, geo: Geography) -> list[TklDeckKey]:
    """Dagens vägar as snabbvägar: the route between the two places, the shortest first."""
    places = {p.id: p for p in geo.places}
    keys: list[TklDeckKey] = []
    seen: set[tuple[str, str]] = set()
    for d in daily:
        origin, goal = places.get(d.origin), places.get(d.goal)
        if origin is None or goal is None:
            continue
        found: list[tuple[int, str, str]] = []
        for start in origin.starts:
            for end in goal.ends:
                chains = plant.candidates(EngineKind.TRAIN, start, end)
                if chains:
                    found.append((len(chains[0]), start, end))
        if not found:
            continue
        _, start, end = min(found)
        if (start, end) in seen:
            continue
        seen.add((start, end))
        keys.append(
            TklDeckKey(
                type=K.ROUTE,
                route=TklDeckRoute(start=start, end=end, kind=RouteKind.TRAIN),
                text=f"{origin.name}{ARROW}{goal.name}"[:60],
                under=d.number[:60],
            )
        )
    return keys


def counted_routes(counts: dict[tuple[str, str, RouteKind], int], known: Known) -> list[TklDeckKey]:
    """Mest använda: the counted routes that still exist, the most used first."""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    keys = []
    for (start, end, kind), _ in ordered:
        route = TklDeckRoute(start=start, end=end, kind=kind)
        if known.route(route):
            keys.append(TklDeckKey(type=K.ROUTE, route=route))
    return keys


def _x_of(key: TklDeckKey, profile: TklDeckProfile) -> float:
    """Where a key is from west to east on the panel; keys without a place last."""
    points = {p.name: p.x for p in profile.points}
    places = {p.id: p.x for p in profile.places}
    if key.type == K.ROUTE and key.route is not None:
        return points.get(key.route.start, 1e9)
    if key.type == K.SIGNAL and key.point:
        return points.get(key.point, 1e9)
    if key.type in (K.PLACE, K.TRACK) and key.place:
        return places.get(key.place, 1e9)
    return 1e9


def suggest(
    default: TklDeckProfile,
    deviations: list[TklDeckDeviation],
    ref: DeckPageRef,
    rule: DeckSuggestion,
    known: Known,
    plant: Plant,
    geo: Geography,
    daily: list[Daily],
    counts: dict[tuple[str, str, RouteKind], int],
) -> list[TklDeckDeviation]:
    """The deviations with the page made again by the rule (SD45)."""
    applied = apply(default, deviations, known)
    profile = applied.profile
    at = next((i for i, p in enumerate(profile.pages) if same_ref(ref_of(p), ref)), None)
    if at is None:
        raise NoSuggestion(f"Sidan {ref.name} finns inte.")
    page = profile.pages[at]
    fixed = set(frame(profile.grid).fixed.values())
    stays = {
        i: k for i, k in enumerate(page.keys) if k is not None and (i in fixed or k.type in STAYS)
    }
    free = [i for i in frame(profile.grid).area if i not in stays]
    base = next((p for p in default.pages if same_ref(ref_of(p), ref)), None)
    keys: list[TklDeckKey | None]
    if rule == DeckSuggestion.GEOGRAPHIC and base is not None:
        keys = list(base.keys)
    else:
        if rule == DeckSuggestion.GEOGRAPHIC:
            mine = [k for i, k in enumerate(page.keys) if k is not None and i not in stays]
            chosen = sorted(mine, key=lambda k: _x_of(k, profile))
        elif rule == DeckSuggestion.DAILY:
            chosen = daily_routes(daily, plant, geo)
            if not chosen:
                raise NoSuggestion(
                    "Det finns inga Dagens vägar än. TKL räknar fram dem ur träffens tidtabell "
                    "när stationen är ansluten till en träff (SD23)."
                )
        else:
            chosen = counted_routes(counts, known)
            if not chosen:
                raise NoSuggestion(
                    "Inga vägar är räknade än. Ställverket räknar varje lagd väg, och Mest "
                    "använda föreslås när vägar har lagts (SD24)."
                )
        keys = [None] * len(page.keys)
        for i, k in stays.items():
            keys[i] = k
        for i, k in zip(free, chosen, strict=False):
            keys[i] = k
    pages = list(profile.pages)
    pages[at] = page.model_copy(update={"keys": keys})
    made = profile.model_copy(update={"pages": pages})
    kept = [deviations[c.deviation] for c in applied.to_check]
    return diff(default, made) + kept


__all__ = ["NoSuggestion", "counted_routes", "daily_routes", "suggest"]
