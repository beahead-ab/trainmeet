"""Why Drift refused a command: one list for every client, each with the text a person reads.

The codes are the old Server's (protocol_v2, engine, terminal16_runtime), so its tests can be
ported with them. Two words follow the glossary: movement became call (tågbesök) and station
became place (driftplats). A client shows the text and waits for the next snapshot; it never
acts on its old data again.
"""

from __future__ import annotations

from enum import StrEnum


class Reason(StrEnum):
    # The envelope and the client
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    UNKNOWN_ACTION = "unknown_action"
    NOT_APPROVED = "not_approved"
    WRONG_PLACE = "wrong_place"
    STALE_MEET_CONTEXT = "stale_meet_context"
    STALE_REVISION = "stale_revision"
    NO_ACTIVE_MEET = "no_active_meet"
    # The train number
    TRAIN_NUMBER_REQUIRED = "train_number_required"
    UNKNOWN_TRAIN_NUMBER = "unknown_train_number"
    AMBIGUOUS_TRAIN_NUMBER = "ambiguous_train_number"
    UNKNOWN_CALL = "unknown_call"
    # Tracks
    UNKNOWN_TRACK = "unknown_track"
    TRACK_OCCUPIED = "track_occupied"
    # Clearance
    UNKNOWN_SECTION = "unknown_section"
    CHANNEL_OCCUPIED = "channel_occupied"
    CALL_ALREADY_REQUESTED = "call_already_requested"
    CLEARANCE_NOT_PENDING = "clearance_not_pending"
    UNKNOWN_CLEARANCE = "unknown_clearance"
    NOT_SENDER = "not_sender"
    NOT_RECEIVER = "not_receiver"
    TRAIN_ALREADY_DEPARTED = "train_already_departed"
    # Departure and arrival
    DEPARTURE_NOT_RESERVED = "departure_not_reserved"
    INVALID_DEPARTURE = "invalid_departure"
    INVALID_ARRIVAL = "invalid_arrival"
    TRAIN_NOT_DEPARTED = "train_not_departed"
    # Line clear
    UNKNOWN_LINE_MESSAGE = "unknown_line_message"
    ALREADY_ACKNOWLEDGED = "already_acknowledged"
    # Detection and signals (TKL level 3)
    NOT_LEVEL_3 = "not_level_3"


TEXT_SV: dict[Reason, str] = {
    Reason.UNSUPPORTED_PROTOCOL: "Hubben förstår inte den här versionen av protokollet.",
    Reason.UNKNOWN_ACTION: "Åtgärden finns inte.",
    Reason.NOT_APPROVED: "Klienten är inte godkänd för driftplatsen.",
    Reason.WRONG_PLACE: "Åtgärden gäller en annan driftplats.",
    Reason.STALE_MEET_CONTEXT: "Träffen eller dagen har bytts. Läs om läget.",
    Reason.STALE_REVISION: "Läget ändrades. Välj tåget igen.",
    Reason.NO_ACTIVE_MEET: "Ingen träff körs.",
    Reason.TRAIN_NUMBER_REQUIRED: "Skriv ett tågnummer.",
    Reason.UNKNOWN_TRAIN_NUMBER: "Tågnumret saknar ett passande tåg här denna trafikdag.",
    Reason.AMBIGUOUS_TRAIN_NUMBER: "Tågnumret har flera tåg. Välj det avsedda.",
    Reason.UNKNOWN_CALL: "Tågbesöket finns inte.",
    Reason.UNKNOWN_TRACK: "Spåret finns inte på driftplatsen.",
    Reason.TRACK_OCCUPIED: "Spåret är upptaget av ett annat tåg.",
    Reason.UNKNOWN_SECTION: "Sträckan finns inte.",
    Reason.CHANNEL_OCCUPIED: "Sträckan är upptagen.",
    Reason.CALL_ALREADY_REQUESTED: "Tåget har redan en pågående klarering.",
    Reason.CLEARANCE_NOT_PENDING: "Klareringsförfrågan gäller inte längre.",
    Reason.UNKNOWN_CLEARANCE: "Klareringen finns inte.",
    Reason.NOT_SENDER: "Bara den som begärde kan återkalla.",
    Reason.NOT_RECEIVER: "Bara mottagaren kan svara.",
    Reason.TRAIN_ALREADY_DEPARTED: "Tåget har redan avgått.",
    Reason.DEPARTURE_NOT_RESERVED: "Tåget saknar beviljad klarering.",
    Reason.INVALID_DEPARTURE: "Avgång kan inte registreras i tågets nuvarande läge.",
    Reason.INVALID_ARRIVAL: "Ankomst kan inte registreras i tågets nuvarande läge.",
    Reason.TRAIN_NOT_DEPARTED: "Tåget har inte avgått.",
    Reason.UNKNOWN_LINE_MESSAGE: "Beskedet om ledig linje finns inte.",
    Reason.ALREADY_ACKNOWLEDGED: "Beskedet är redan kvitterat.",
    Reason.NOT_LEVEL_3: "Beläggning tas bara emot från en station på nivå 3.",
}
