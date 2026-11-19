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
    # The automation (F14)
    PLACE_AUTOMATIC = "station_automatic"
    PLACE_MANNED = "automatic_station_manned"
    AUTOMATION_OFF = "automation_off"
    CLIENT_NOT_PRESENT = "client_not_present"
    # The clock: tidshopp and Ångra (H37, F6)
    NO_JUMP_TO_UNDO = "no_jump_to_undo"
    OTHER_GAME_DAY = "other_game_day"
    DAY_STILL_RUNNING = "day_still_running"
    # The places during the meet (H30)
    UNKNOWN_PLACE = "unknown_place"
    # Driftändringar (DRIFT-41)
    UNKNOWN_TRAIN = "unknown_train"
    NO_ROUTE = "no_route"
    INVALID_TIME = "invalid_time"
    TRAIN_NUMBER_TAKEN = "train_number_taken"
    UNKNOWN_CHANGE = "unknown_change"
    SECTION_CLOSED = "section_closed"
    # Versionsbyte and påbörjat och klart (DRIFT-29, DRIFT-47)
    UNKNOWN_VERSION = "unknown_version"
    SAME_VERSION = "same_version"
    NO_SWITCH_WAITING = "no_switch_waiting"
    DRIFT_LOCKED = "drift_locked"
    NOT_LOCKED = "not_locked"
    # Synk (SYNK-14): the hub follows a meet another hub leads
    NOT_LEADER = "not_leader"
    ALREADY_LEADER = "already_leader"
    # Lokföraren (LOK-40, LOK-25): a service has one driver at a time
    UNKNOWN_SERVICE = "unknown_service"
    SERVICE_TAKEN = "service_taken"
    ONE_SERVICE = "one_service"
    NO_SERVICE = "no_service"
    UNKNOWN_DRIVER = "unknown_driver"
    NOT_IN_SERVICE = "not_in_service"
    # Efter pappret (LOK-13, LOK-29): a service missing from the plan, read from the photos
    UNKNOWN_PAPER = "unknown_paper"
    PAPER_DECIDED = "paper_decided"
    PAPER_NO_PLACES = "paper_no_places"
    PAPER_FEW_PLACES = "paper_few_places"
    PAPER_NO_TIMES = "paper_no_times"
    PAPER_NO_NUMBER = "paper_no_number"
    # Fjärrstyrning (#36, TKL89): handing a station over, and the routes asked for from afar
    NOT_CONTROLLER = "not_controller"
    NOT_IN_CATALOG = "not_in_catalog"
    ROUTE_ALREADY_REQUESTED = "route_already_requested"
    ROUTE_NOT_PENDING = "route_not_pending"
    OFFER_NOT_PENDING = "offer_not_pending"
    OFFER_PENDING = "offer_pending"
    STATION_NOT_ANSWERING = "station_not_answering"
    PLACE_REMOTE = "place_remote"
    NO_CATALOG = "no_catalog"
    NOT_STATION = "not_station"
    UNKNOWN_RECEIVER = "unknown_receiver"
    NO_CONTACT = "no_contact"
    # The station's interlocking says no (FR12): it alone tries the route.
    CONFLICTING_ROUTE = "conflicting_route"
    SWITCH_NOT_IN_CONTROL = "switch_not_in_control"
    AREA_RELEASED = "area_released"


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
    Reason.PLACE_AUTOMATIC: "Automatiken sköter driftplatsen. Ta tillbaka den först.",
    Reason.PLACE_MANNED: "Driftplatsen är bemannad.",
    Reason.AUTOMATION_OFF: "Automatiken är avstängd av trafikledningen.",
    Reason.CLIENT_NOT_PRESENT: "Klienten måste vara ansluten till driftplatsen.",
    Reason.NO_JUMP_TO_UNDO: "Det finns inget tidshopp att ångra.",
    Reason.OTHER_GAME_DAY: "Ett hopp till ett annat speldygn görs med dygnsskiftet.",
    Reason.UNKNOWN_PLACE: "Driftplatsen finns inte i träffen.",
    Reason.UNKNOWN_TRAIN: "Tåget finns inte i träffen.",
    Reason.NO_ROUTE: "Det finns ingen väg mellan driftplatserna.",
    Reason.INVALID_TIME: "Tiderna går inte ihop: ett tåg kan inte gå bakåt i tiden.",
    Reason.TRAIN_NUMBER_TAKEN: "Tågnumret finns redan samma dag.",
    Reason.UNKNOWN_CHANGE: "Driftändringen finns inte, eller är redan släppt.",
    Reason.SECTION_CLOSED: "Sträckan är stängd.",
    Reason.UNKNOWN_VERSION: "Versionen finns inte, eller är tillbakadragen.",
    Reason.SAME_VERSION: "Den versionen körs redan.",
    Reason.NO_SWITCH_WAITING: "Inget versionsbyte väntar.",
    Reason.DRIFT_LOCKED: (
        "Drift är spärrad: något påbörjades och blev aldrig klart. Kontrollera läget i Nu och "
        "lås upp."
    ),
    Reason.NOT_LOCKED: "Drift är inte spärrad.",
    Reason.NOT_LEADER: "En annan hubb leder träffen. Den här hubben följer den och ändrar inget.",
    Reason.ALREADY_LEADER: "Den här hubben leder redan träffen.",
    Reason.UNKNOWN_SERVICE: "Tjänsten finns inte i träffen i dag.",
    Reason.SERVICE_TAKEN: "Tjänsten är tagen.",
    Reason.ONE_SERVICE: "Du har redan en tjänst. Släpp den först.",
    Reason.NO_SERVICE: "Du har ingen tjänst.",
    Reason.UNKNOWN_DRIVER: "Föraren finns inte i träffen.",
    Reason.NOT_IN_SERVICE: "Platsen eller tågbesöket finns inte i tjänsten.",
    Reason.UNKNOWN_PAPER: "Tjänsten efter pappret finns inte.",
    Reason.PAPER_DECIDED: "Tjänsten efter pappret är redan godkänd, avslagen eller släppt.",
    Reason.PAPER_NO_PLACES: (
        "Pappret nämner ingen driftplats i träffen. Fota sidorna igen, eller be trafikledningen "
        "om hjälp."
    ),
    Reason.PAPER_FEW_PLACES: (
        "Tåget behöver två driftplatser i träffen för att tågklarerarna ska kunna klarera det."
    ),
    Reason.PAPER_NO_TIMES: "Ingen tid på pappret gick att läsa, så tåget kan inte sättas in.",
    Reason.PAPER_NO_NUMBER: "Tågnumret gick inte att läsa på pappret. Skriv det.",
    Reason.DAY_STILL_RUNNING: (
        "Dagens tåg är ute eller har en öppen klarering. Vänta tills de har kommit fram, "
        "eller gör ett tidshopp."
    ),
    Reason.NOT_CONTROLLER: "Du styr inte driftplatsen.",
    Reason.NOT_IN_CATALOG: "Tågvägen finns inte i stationens fjärrkatalog.",
    Reason.ROUTE_ALREADY_REQUESTED: "Tågvägen är redan begärd.",
    Reason.ROUTE_NOT_PENDING: "Begäran om tågvägen finns inte, eller gäller inte längre.",
    Reason.OFFER_NOT_PENDING: "Erbjudandet gäller inte längre.",
    Reason.OFFER_PENDING: "Stationen är redan erbjuden. Vänta på svaret, eller ta tillbaka den.",
    Reason.STATION_NOT_ANSWERING: "Stationens ställverk svarar inte.",
    Reason.PLACE_REMOTE: "Driftplatsen fjärrstyrs. Ta tillbaka den först.",
    Reason.NO_CATALOG: (
        "Stationen kan inte fjärrstyras: den har ingen fjärrkatalog. En station på nivå 0 har "
        "ingen."
    ),
    Reason.NOT_STATION: "Bara stationens egen TKL kan lämna över eller ta tillbaka stationen.",
    Reason.UNKNOWN_RECEIVER: (
        "Stationen kan bara lämnas till en granne, till den som redan fjärrstyr en granne eller "
        "till ett godkänt fjärrställverk."
    ),
    Reason.NO_CONTACT: (
        "Kontakten med den som fjärrstyr saknades. Inga nya tågvägar gick under tiden. Läs om "
        "läget och försök igen."
    ),
    Reason.CONFLICTING_ROUTE: "En fientlig väg är lagd.",
    Reason.SWITCH_NOT_IN_CONTROL: "Växlarna ligger inte i kontroll.",
    Reason.AREA_RELEASED: "Området är lokalt frigivet.",
}


# Lokföraren speaks Swedish and English (ST10): the reasons a driver can be told, in English.
TEXT_EN: dict[Reason, str] = {
    Reason.UNKNOWN_SERVICE: "The service is not in today's meet.",
    Reason.SERVICE_TAKEN: "The service is taken.",
    Reason.ONE_SERVICE: "You already have a service. Release it first.",
    Reason.NO_SERVICE: "You have no service.",
    Reason.UNKNOWN_DRIVER: "The driver is not in the meet.",
    Reason.NOT_IN_SERVICE: "The place or call is not in the service.",
    Reason.UNKNOWN_PAPER: "The service run after the paper does not exist.",
    Reason.PAPER_DECIDED: "The service run after the paper is already decided or released.",
    Reason.PAPER_NO_PLACES: (
        "The paper names no place in the meet. Take the photos again, or ask the dispatcher."
    ),
    Reason.NO_ACTIVE_MEET: "No meet is running.",
    Reason.UNKNOWN_PLACE: "The place is not in the meet.",
    Reason.DRIFT_LOCKED: "Operations are locked. Ask the dispatcher.",
    Reason.NOT_LEADER: "Another hub leads the meet. This hub follows it and changes nothing.",
}
