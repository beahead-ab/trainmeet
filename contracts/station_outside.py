"""trainmeet.station-outside/1: a station's outside, as TKL Studio publishes it.

The outside is what the meet needs to know about a station: its id and name, its station
tracks, its exits with a fixed id and side, and the sides boxes can show. Synk stores it,
and the meet package pins it to a version (decisions H28, TKL14, TKL21).

A station split into parts (delställverk, TKL97) lists the parts that are their own driftplatser
in Hubben: those staffed on their own, chosen by the owner in Studio (TKL101). Each becomes a
driftplats of its own in the plan, linked to the same station (PLAN-34), and the station's TKL
asks for one driftplats per part when it connects (TRAFIK-35). A part the same person runs is
not listed: Hubben never sees it.

Remote control (fjärrstyrning, #36, TKL46–TKL48, TKL89): the station says which of its own
train routes may be requested from afar (the remote catalogue, `remote_routes`), which station
automats it has (`automats`), who may receive it (`remote_receivers`), and a simple drawing of
what is controlled centrally (`overview`), so that a remote interlocking can draw it without the
inside. All four are new and empty by default, so an older outside still reads, and the format
keeps its number. A station at level 0 locks no routes and has no catalogue (FR16).

Never in the outside: the inside (track plan, switch numbers, addresses) and telephone numbers.
The telephone number belongs to the place in the plan (H30).
"""

from __future__ import annotations

from enum import StrEnum
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


class RouteDirection(StrEnum):
    IN = "in"  # från linjen in till spåret
    OUT = "out"  # från spåret ut mot linjen


class RemoteRoute(Contract):
    """A route in the remote catalogue (fjärrkatalog, TKL46, FR10): one of the station's own
    train routes that may be requested from afar. Shunting routes never are. The catalogue only
    says what may be asked for; the station's interlocking tries each request as if it had been
    laid on the spot (FR12)."""

    id: Id = Field(description="Tågvägens fasta id i stationen, till exempel 21-33.")
    start: Text = Field(
        description="Start som i stationens egen tabell: en signal, ett spår eller A1."
    )
    end: Text = Field(description="Mål som i stationens egen tabell.")
    exit: Id = Field(description="Linjeänden: utfartens id i utsidan.")
    track: Id = Field(description="Stationsspåret.")
    direction: RouteDirection = Field(
        description="in från linjen till spåret, out från spåret mot linjen."
    )


class AutomatKind(StrEnum):
    """The station automats (FR24, FR39), as in interlockings 85 and 95."""

    A1 = "a1"  # enstaka möte
    A2 = "a2"  # enstaka förbigång
    A3 = "a3"  # automatdrift
    AN = "an"  # automatdrift på nedspåret
    AU = "au"  # automatdrift på uppspåret
    LOCAL_RELEASE = "local_release"  # lokalfrigivningsautomat, L1 eller L01 (TKL44)


class Automat(Contract):
    """A station automat in the station's own interlocking (FR24). Switched on and off by whoever
    controls the station: on the spot when manned, from the remote picture when remote-controlled
    (FR25)."""

    code: Text = Field(
        max_length=12,
        description="Koden vid stationsnamnet, till exempel A3, AU21 eller L01. Flera av samma "
        "slag skiljs åt med infartssignalens nummer (FR40).",
    )
    kind: AutomatKind
    default: bool = Field(
        default=False,
        description="Förvald: stationen kopplar in den själv efter 90 sekunder utan kontakt med "
        "den som fjärrstyr (FR29).",
    )


class ReceiverKind(StrEnum):
    """Who may receive the station when it is handed over (FR3, TKL46, TKL47)."""

    NEIGHBOURS = "neighbours"  # en granne längs linjen, eller den som redan fjärrstyr en granne
    REMOTE = "remote"  # ett godkänt fjärrställverk


class OverviewTrack(Contract):
    """A horizontal piece of track in the overview, on one row of the grid."""

    id: Id = Field(description="Bitens id i översikten. Inte ett nummer eller en adress.")
    row: int = Field(ge=0, description="Raden, uppifrån och från 0.")
    start: int = Field(ge=0, description="Kolumnen där biten börjar, från vänster och från 0.")
    end: int = Field(ge=1, description="Kolumnen där biten slutar, till höger om start.")
    track: Id | None = Field(
        default=None, description="Stationsspåret biten är, med spårets id i utsidan."
    )
    platform: bool = Field(default=False, description="Biten har plattform.")


class OverviewLink(Contract):
    """A switch as a line between two rows (växeln som streck, FR31, FR36): from a point on one
    row to a point on another. No number, no address."""

    id: Id = Field(description="Streckets id i översikten. Aldrig växelns nummer.")
    from_row: int = Field(ge=0)
    from_column: int = Field(ge=0)
    to_row: int = Field(ge=0)
    to_column: int = Field(ge=0)


class OverviewSignal(Contract):
    """A main signal with its number, where it stands and which way it faces. The catalogue's
    routes start and end at them (FR31). Dwarf signals are never in the overview (FR36)."""

    name: Text = Field(max_length=12, description="Signalens nummer, som i tågvägarna.")
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    towards: Side = Field(description="Åt vilket håll signalen visar.")


class OverviewExit(Contract):
    """Where a line end leaves the drawing."""

    exit: Id = Field(description="Utfartens id i utsidan.")
    row: int = Field(ge=0)
    column: int = Field(ge=0)


class OverviewDrawing(Contract):
    """The outside's overview (FR31, FR48, TKL88): a simple drawing, in a grid read from left to
    right, of the tracks, switches and main signals that are controlled centrally. Every signal
    and switch sits on a horizontal line, as in the remote picture. Tracks no catalogue route
    reaches are left out, and there are no switch numbers, dwarf signals or addresses. Each
    catalogue route names the pieces and links it lays, in order, so that a locked route can be
    drawn and the switches' lie seen. Studio makes it from the drawing."""

    columns: int = Field(ge=1, le=400, description="Rutnätets bredd i kolumner.")
    rows: int = Field(ge=1, le=40, description="Rutnätets höjd i rader.")
    tracks: list[OverviewTrack] = Field(default_factory=list)
    links: list[OverviewLink] = Field(default_factory=list)
    signals: list[OverviewSignal] = Field(default_factory=list)
    exits: list[OverviewExit] = Field(default_factory=list)
    routes: dict[Id, list[Id]] = Field(
        default_factory=dict,
        description="Katalogvägens id → bitarna och strecken den lägger, i ordning.",
    )

    @model_validator(mode="after")
    def _check(self) -> OverviewDrawing:
        ids = [t.id for t in self.tracks] + [link.id for link in self.links]
        if len(set(ids)) != len(ids):
            raise ValueError("Två bitar eller streck i översikten har samma id.")
        for piece in self.tracks:
            if not piece.start < piece.end <= self.columns or piece.row >= self.rows:
                raise ValueError(f"Biten {piece.id} ligger utanför översikten.")
        points = [(link.from_row, link.from_column) for link in self.links]
        points += [(link.to_row, link.to_column) for link in self.links]
        points += [(s.row, s.column) for s in self.signals]
        points += [(e.row, e.column) for e in self.exits]
        if any(row >= self.rows or column > self.columns for row, column in points):
            raise ValueError("Ett streck, en signal eller en utfart ligger utanför översikten.")
        known = set(ids)
        for route, pieces in self.routes.items():
            unknown = sorted(set(pieces) - known)
            if unknown:
                raise ValueError(f"Vägen {route} i översikten går över okända bitar: {unknown}.")
        return self


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
    remote_routes: list[RemoteRoute] = Field(
        default_factory=list,
        description="Fjärrkatalogen: de av stationens tågvägar som får begäras från fjärr "
        "(TKL46, FR10). Tomt: stationen kan inte fjärrstyras, som på nivå 0 (FR16).",
    )
    automats: list[Automat] = Field(
        default_factory=list, description="Stationsautomaterna med sina koder (FR24, FR39)."
    )
    overview: OverviewDrawing | None = Field(
        # A factory, so that the schema gives no default and an older outside may leave it out.
        default_factory=lambda: None,
        description="En enkel ritning av det som styrs centralt, för fjärrbilden (FR31, FR48).",
    )
    remote_receivers: list[ReceiverKind] = Field(
        default_factory=list,
        description="Vilket slag som får ta emot stationen: grannar, fjärrställverk eller båda. "
        "Tomt: båda. Vilka grannarna är avgörs per träff (H26).",
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
        self._check_remote(track_ids, exit_ids)
        return self

    def _check_remote(self, track_ids: list[str], exit_ids: list[str]) -> None:
        """The catalogue points at the station's own tracks and exits, and the overview at the
        catalogue's routes (TKL46, FR31)."""
        route_ids = [r.id for r in self.remote_routes]
        if len(set(route_ids)) != len(route_ids):
            raise ValueError("Två tågvägar i fjärrkatalogen har samma id.")
        for route in self.remote_routes:
            if route.track not in track_ids:
                raise ValueError(f"Tågvägen {route.id} går till ett okänt spår: {route.track}.")
            if route.exit not in exit_ids:
                raise ValueError(f"Tågvägen {route.id} pekar på en okänd utfart: {route.exit}.")
        codes = [a.code.casefold() for a in self.automats]
        if len(set(codes)) != len(codes):
            raise ValueError("Två stationsautomater har samma kod.")
        if sum(a.kind == AutomatKind.A3 for a in self.automats) > 1:
            raise ValueError("En station har bara en A3 (FR26).")
        if self.overview is None:
            return
        drawn = {t.track for t in self.overview.tracks if t.track is not None} - set(track_ids)
        if drawn:
            raise ValueError(f"Översikten ritar okända spår: {sorted(drawn)}.")
        exits = {e.exit for e in self.overview.exits} - set(exit_ids)
        if exits:
            raise ValueError(f"Översikten ritar okända utfarter: {sorted(exits)}.")
        outside = sorted(set(self.overview.routes) - set(route_ids))
        if outside:
            raise ValueError(f"Översikten har vägar utanför katalogen: {outside}.")
