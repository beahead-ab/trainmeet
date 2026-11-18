"""Spår-vyn (BOXIOS-16, H65): which of the place's tracks the apps show, and in which order.

Ported from the old Server (docs/tmbox-sparvisning.md, runtime.save_track_display). The choice
is kept per run and place and shared by every app at the place; it is only presentation and
changes nothing in the traffic. The base is the plan's tracks for the place, in their sort
order, then any track the timetable uses that the plan does not list. A saved choice keeps its
order and hidden tracks for the tracks still there; new tracks come last, visible. Every save
and every reset counts the revision up, so a client that read before someone else's change is
always told so.
"""

from __future__ import annotations

from collections.abc import Sequence

from contracts import station
from contracts.meet import Place


class TrackDisplayConflict(Exception):
    """Someone else changed the place's Spår-vy since the client read it."""


class TracksChanged(Exception):
    """The list does not hold the place's tracks exactly once each."""


def base_order(place: Place, used: Sequence[str]) -> list[str]:
    """The plan's tracks for the place in their sort order, then the timetable's others."""
    planned = [t.name for t in sorted(place.tracks, key=lambda t: t.sort_order)]
    others = sorted({name for name in used if name and name not in planned})
    return planned + others


def shown(
    base: list[str], revision: int, saved: dict[str, list[str]] | None
) -> station.TrackDisplay:
    if saved is None:
        return station.TrackDisplay(
            revision=revision, tracks=[station.TrackShown(track=name) for name in base]
        )
    order = [name for name in saved.get("order", []) if name in base]
    order += [name for name in base if name not in order]
    hidden = set(saved.get("hidden", []))
    return station.TrackDisplay(
        revision=revision,
        customized=True,
        tracks=[station.TrackShown(track=name, visible=name not in hidden) for name in order],
    )


def checked(
    base: list[str], revision: int, change: station.TrackDisplayChange
) -> dict[str, list[str]] | None:
    """The choice to save, or None to go back to the meet's order."""
    if change.revision != revision:
        raise TrackDisplayConflict()
    if change.tracks is None:
        return None
    names = [t.track for t in change.tracks]
    if len(set(names)) != len(names) or sorted(names) != sorted(base):
        raise TracksChanged()
    return {"order": names, "hidden": [t.track for t in change.tracks if not t.visible]}
