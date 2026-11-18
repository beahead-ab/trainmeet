"""Manöver, the owner's free panel (STV-46, TKL86): the settings checked against the panel.

Manöver draws the station's own panel, from its track plan when it has one, else the engine's
layout, with the symbols and colours of the standard skin 59, 85 or 95 the owner chose. The
owner's labels rename what is shown for a track, a signal or a switch; the ids stay, so every
click still asks the interlocking with the id. A label must name something the panel has: a
track by the name the panel shows, a signal by its id and a switch by its number there.

When the model changes, a label for something the new panel lacks is kept with the station but
left out of what is shown; the next save drops it.
"""

from __future__ import annotations

from contracts.tkl import Panel, TklManover, TklManoverLabels

NO_PANEL = "Panelen går inte att göra förrän problemen i stationsmodellen är rättade."


def _known(panel: Panel) -> tuple[set[str], set[str], set[str]]:
    return (
        {t.name for t in panel.track_names},
        {s.name for s in panel.signals},
        {s.number for s in panel.switches},
    )


def problems(panel: Panel | None, settings: TklManover) -> list[str]:
    """What is wrong with the settings for this panel, in Swedish; empty when they may be kept."""
    if panel is None:
        return [NO_PANEL]
    tracks, signals, switches = _known(panel)
    labels = settings.labels
    found = []
    for kind, given, known in (
        ("spåret", labels.tracks, tracks),
        ("signalen", labels.signals, signals),
        ("växeln", labels.switches, switches),
    ):
        unknown = sorted(set(given) - known)
        if unknown:
            found.append(f"Panelen har inte {kind} {', '.join(unknown)}.")
    return found


def shown(panel: Panel | None, settings: TklManover) -> TklManover:
    """The settings as Manöver uses them: labels only for what the panel has."""
    if panel is None:
        return settings
    tracks, signals, switches = _known(panel)
    labels = settings.labels
    kept = TklManoverLabels(
        tracks={k: v for k, v in labels.tracks.items() if k in tracks},
        signals={k: v for k, v in labels.signals.items() if k in signals},
        switches={k: v for k, v in labels.switches.items() if k in switches},
    )
    return settings.model_copy(update={"labels": kept})
