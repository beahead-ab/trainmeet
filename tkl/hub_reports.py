"""Ställverket towards Hubben (STV-10): what the interlocking reports goes up as station commands.

Upwards at level 1–2: the departure (train.departed), the arrival (train.arrived) or a track
change for a train already here (train.track.change), and the exit signal's aspect
(signal.exit). section.occupancy is level 3 only, and never sent from here.

The interlocking knows the train number and, for a train it took from Hubben's list of trains on
their way here, the call. The call is found in the place's snapshot, as level 0's buttons find
it: by the call, else by a train number that only one call at the place has. A report whose
train Hubben does not know, or knows twice, is not sent, and the answer says why; nothing is
guessed. Hubben's answer, yes or no with its reason, comes back as it was given. A train that
left by another exit than its clearance's is not reported departed: the operator reports it in
Klarering. Only a track Hubben's plan knows for the place goes with an arrival.

The key stays in TKL's server and only goes in the Authorization header (H31).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from contracts import station
from contracts.tkl import TklReport, TklReportKind
from tkl.hub_client import HubClient, HubError, Unreachable

Planned = tuple[station.Action, dict[str, object], station.Revision | None]


def _revision(snapshot: station.Snapshot, call: str) -> station.Revision | None:
    found = next((c for c in snapshot.calls if c.call == call), None)
    if found is None:
        return None
    return station.Revision(scope=station.RevisionScope.CALL, key=call, value=found.revision)


def _name(report: TklReport) -> str:
    return f"Tåg {report.train_number}" if report.train_number else f"Tågbesöket {report.call}"


def _departure(snapshot: station.Snapshot, report: TklReport) -> Planned | str:
    here = [c for c in snapshot.calls if c.departure_state != station.DepartureState.DEPARTED]
    if report.call is not None:
        found = [c for c in here if c.call == report.call]
    else:
        found = [c for c in here if c.train_number == report.train_number]
    if not found:
        return f"{_name(report)} finns inte i hubbens bild. Avgången rapporterades inte."
    if len(found) > 1:
        return f"Flera tågbesök har numret {report.train_number}. Rapportera avgången i Klarering."
    call = found[0]
    clearance = next(
        (
            c
            for c in snapshot.clearances
            if c.call == call.call and c.status == station.ClearanceStatus.APPROVED
        ),
        None,
    )
    if clearance is not None and report.exit is not None:
        section = next((s for s in snapshot.sections if s.section == clearance.section), None)
        if section is not None and section.exit is not None and section.exit != report.exit:
            return (
                f"{_name(report)} har klarering mot utfarten {section.exit}, men lämnade mot "
                f"{report.exit}. Avgången rapporterades inte; rapportera den i Klarering."
            )
    payload: dict[str, object] = {"call": call.call}
    return station.Action.TRAIN_DEPARTED, payload, _revision(snapshot, call.call)


def _arrival(snapshot: station.Snapshot, report: TklReport) -> Planned | str:
    known = {t.track for t in snapshot.track_display.tracks}
    track = report.track if report.track and (not known or report.track in known) else None
    if report.call is not None:
        coming = [t for t in snapshot.on_the_way if t.call == report.call]
    else:
        coming = [t for t in snapshot.on_the_way if t.train_number == report.train_number]
    if len(coming) > 1:
        return f"Flera tåg på väg hit har numret {report.train_number}. Tryck Ankommit i Tåg."
    if coming:
        payload: dict[str, object] = {"call": coming[0].call}
        if track is not None:
            payload["track"] = track
        return station.Action.TRAIN_ARRIVED, payload, _revision(snapshot, coming[0].call)
    here = [
        c
        for c in snapshot.calls
        if (c.call == report.call if report.call else c.train_number == report.train_number)
        and station.Action.TRAIN_TRACK_CHANGE in c.allowed_actions
    ]
    if len(here) == 1 and track is not None:
        if here[0].track == track:
            return f"{_name(report)} står redan på spår {track} i hubbens bild."
        payload = {"call": here[0].call, "track": track}
        return station.Action.TRAIN_TRACK_CHANGE, payload, _revision(snapshot, here[0].call)
    return f"{_name(report)} är inte på väg hit i hubbens bild. Ankomsten rapporterades inte."


def _exit_signal(snapshot: station.Snapshot, report: TklReport) -> Planned | str:
    section = next((s for s in snapshot.sections if s.exit == report.exit), None)
    if section is None or report.aspect is None:
        return f"Ingen sträcka går från utfarten {report.exit} i den här träffen."
    payload: dict[str, object] = {
        "exit": report.exit,
        "section": section.section,
        "aspect": report.aspect.value,
    }
    if report.call is not None:
        payload["call"] = report.call
    return station.Action.SIGNAL_EXIT, payload, None


def plan(snapshot: station.Snapshot, report: TklReport) -> Planned | str:
    """The station command a report becomes, or why it is not sent."""
    if report.kind == TklReportKind.DEPARTED:
        return _departure(snapshot, report)
    if report.kind == TklReportKind.ARRIVED:
        return _arrival(snapshot, report)
    return _exit_signal(snapshot, report)


WHAT = {
    TklReportKind.DEPARTED: "Avgången",
    TklReportKind.ARRIVED: "Ankomsten",
    TklReportKind.EXIT_SIGNAL: "Utfartssignalen",
}


def said(report: TklReport) -> str:
    """How a report went, as a line in the interlocking's events."""
    who = f" för tåg {report.train_number}" if report.train_number else ""
    return f"{WHAT[report.kind]}{who}: {report.message or 'inget svar.'}"


def send(
    hub: HubClient,
    client_id: str,
    place: str,
    snapshot: station.Snapshot,
    reports: Sequence[TklReport],
) -> tuple[list[TklReport], station.Snapshot]:
    """Each report as a station command, in order, with Hubben's answer; and the last
    snapshot Hubben gave."""
    done: list[TklReport] = []
    for report in reports:
        planned = plan(snapshot, report)
        if isinstance(planned, str):
            done.append(report.model_copy(update={"message": planned}))
            continue
        action, payload, revision = planned
        command = station.Command(
            message_id=f"tkl-{uuid4().hex}",
            client_id=client_id,
            place=place,
            context=snapshot.context,
            action=action,
            expected_revision=revision,
            payload=payload,
        )
        try:
            reply = hub.command(command)
        except Unreachable:
            done.append(
                report.model_copy(update={"action": action, "message": "Ingen kontakt med hubben."})
            )
            continue
        except HubError as error:
            done.append(report.model_copy(update={"action": action, "message": error.detail}))
            continue
        accepted = reply.status != station.ReplyStatus.REJECTED
        snapshot = reply.snapshot
        said = reply.message or ("Hubben tog emot den." if accepted else "Hubben sa nej.")
        done.append(
            report.model_copy(
                update={"action": action, "sent": True, "accepted": accepted, "message": said}
            )
        )
    return done, snapshot
