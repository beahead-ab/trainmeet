"""trainmeet.station-outside/1: a station's outside, as TKL Studio publishes it.

The outside is what the meet needs to know about a station: its id and name, its station
tracks, its exits with a fixed id and side, and the sides boxes can show. Synk stores it,
and the meet package pins it to a version (decisions H28, TKL14, TKL21).

A station split into parts (delställverk, TKL97) lists the parts that are their own driftplatser
in Hubben: those staffed on their own, chosen by the owner in Studio (TKL101). Each becomes a
driftplats of its own in the plan, linked to the same station (PLAN-34), and the station's TKL
asks for one driftplats per part when it connects (TRAFIK-35). A part the same person runs is
not listed: Hubben never sees it.

Never in the outside: the inside (track plan, signals, addresses) and telephone numbers.
The telephone number belongs to the place in the plan (H30).
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, model_validator

from contracts.common import Contract, Id, Side, Text

FORMAT: Final = "trainmeet.station-outside/1"


class StationTrack(Contract):
    id: Id = Field(description="Spårets korta namn i stationen, till exempel 1a. Fast id.")
    label: Text = Field(description="Det som står på skärmen, till exempel Spår 1a.")


class Exit(Contract):
    id: Id = Field(description="Utfartens fasta id. Kopplas till en sträcka per träff (H26).")
    side: Side = Field(description="Vilken sida utfarten ligger på.")
    name: Text | None = Field(default=None, description="Till exempel Mot Norrby.")
    tracks: list[Id] = Field(
        default_factory=list, description="Stationsspåren som når utfarten, vid gränsen."
    )
    signals: list[Text] = Field(
        default_factory=list, description="Signalerna vid gränsen, med sina namn."
    )


class BoxSide(Contract):
    side: Side
    label: Text = Field(description="Det boxen visar för sidan, till exempel Väster.")


class StationPart(Contract):
    """A part of the station that is its own driftplats in Hubben (TKL101, PLAN-34)."""

    id: Id = Field(description="Delens fasta id i stationen, satt i TKL Studio.")
    name: Text = Field(description="Delens namn, som driftplatsen får i planen.")
    code: Text | None = Field(
        default=None,
        description="Delens signatur som driftplats. Tomt: namnet används, som när planen saknar "
        "en signatur.",
    )


class StationOutside(Contract):
    """The outside of one station. Level 0 stations write tracks and exits as a list (TKL21)."""

    format: Literal["trainmeet.station-outside/1"] = FORMAT
    station_id: Id = Field(description="Stationens id, skapat i TKL Studio.")
    name: Text
    tracks: list[StationTrack] = Field(min_length=1)
    exits: list[Exit] = Field(min_length=1)
    sides: list[BoxSide] = Field(default_factory=list)
    parts: list[StationPart] = Field(
        default_factory=list,
        description="Delarna som är egna driftplatser i Hubben, de som bemannas för sig "
        "(TKL101, PLAN-34). Tomt för en station utan sådana delar.",
    )

    @model_validator(mode="after")
    def _check(self) -> StationOutside:
        track_ids = [t.id for t in self.tracks]
        if len(set(track_ids)) != len(track_ids):
            raise ValueError("Två stationsspår har samma id.")
        exit_ids = [e.id for e in self.exits]
        if len(set(exit_ids)) != len(exit_ids):
            raise ValueError("Två utfarter har samma id.")
        for exit_ in self.exits:
            unknown = sorted(set(exit_.tracks) - set(track_ids))
            if unknown:
                raise ValueError(f"Utfarten {exit_.id} pekar på okända spår: {', '.join(unknown)}.")
        part_ids = [p.id for p in self.parts]
        if len(set(part_ids)) != len(part_ids):
            raise ValueError("Två delar har samma id.")
        return self
