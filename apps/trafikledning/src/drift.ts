// What Trafikledningen says, and the small rules behind it, without React: the same words and
// choices as the old pages (hub/static/drift.js), so they can be tested on their own.
import type { Actor, AutomationPlace, Client, DriftEvent, Leg, Now } from "./api";
export { dayName, WEEKDAYS } from "@trainmeet/hubben";

export const STATES: Record<Leg["state"], string> = {
  planned: "Ej begärd",
  requested: "Begärd",
  cleared: "Klar att avgå",
  on_the_way: "På väg",
  arrived: "Framme",
};
export const CASES: Record<string, string> = { waiting: "Väntar på svar", approved: "Klart givet" };
export const KINDS: Record<Client["kind"], string> = {
  tmbox_web: "Webbox",
  tmbox: "TMBox",
  tmbox_app: "TMBox-appen",
  tkl: "TKL",
  dispatch: "Trafikledningen",
  screen: "Skärm",
};
export const APPROVAL: Record<string, string> = { waiting: "Väntar", approved: "Ansluten", refused: "Nekad", revoked: "Återkallad" };
export const SIDES: Record<Client["side"], string> = { both: "Båda sidor", left: "Vänster", right: "Höger" };
export const LANGUAGES: Record<string, string> = { sv: "Svenska", en: "English", da: "Dansk", nb: "Norsk", de: "Deutsch" };
export const SPEEDS = [1, 2, 3, 4, 6, 8, 12];
export const VIEWS: Record<string, string> = { clock: "Klocka" };
export const EVENTS: Record<string, string> = {
  "meet.started": "Träffen startade",
  "clock.started": "Klockan startade",
  "clock.stopped": "Klockan stoppades",
  "clock.speed": "Ny hastighet",
  "clearance.requested": "Klarering begärd",
  "clearance.cancelled": "Begäran återtagen",
  "clearance.invalidated": "Klareringen blev ogiltig (spårbyte)",
  "clearance.reminded": "Påminnelse",
  "train.departed": "Avgång",
  "train.arrived": "Ankomst",
  "train.moved_here": "Flyttad hit",
  "train.set_aside": "Undanställd",
  "train.track_changed": "Spårbyte",
  "train.positioned": "Uppställd",
  "train.crew_ready": "Föraren på plats",
  "line.available": "Ledig linje",
  "line.acknowledged": "Ledig linje kvitterad",
  "place.manned": "Platsen bemannad",
  "place.left": "Lämnad till automatiken",
  "place.taken_back": "Tagen tillbaka från automatiken",
  "automation.set": "Automatikens inställningar ändrade",
};

// Automatiken (F14): the place's mode, who left it, and the choices (F15, H42).
export const MODES: Record<string, string> = { manned: "Bemannad", no_contact: "Kontakt saknas", automatic: "Automatiken" };
const LEFT_BY: Record<string, string> = {
  dispatcher: "lämnad av trafikledningen",
  operator: "lämnad av boxen eller TKL",
  lost_contact: "tog över efter Kontakt saknas",
};
/** What the automation waits with as it should is not listed: only what may need someone. */
export const ORDINARY = new Set(["Väntar på föregående ankomst", "På väg"]);
export const LOST: [0 | 2 | 5 | 10, string][] = [
  [0, "Aldrig"],
  [2, "2 min"],
  [5, "5 min"],
  [10, "10 min"],
];
export const DISTURBANCES: Record<string, string> = { off: "Av", normal: "Normal", disrupted: "Störd trafik" };
export const WHERE: Record<string, string> = { both: "Station och linje", station: "Bara station", line: "Bara linje" };

export const placeName = (now: Now | null, id: string) => now?.places.find((place) => place.place === id)?.name ?? id;
export const placeCode = (now: Now | null, id: string) => now?.places.find((place) => place.place === id)?.code ?? id;

/** What a client row says about the client, after its name. */
export function clientDetails(client: Client, now: Now | null): string {
  const details = [KINDS[client.kind] ?? client.kind, APPROVAL[client.status] ?? client.status];
  if (client.kind === "screen") details[1] = client.view ? `Visar ${VIEWS[client.view] ?? client.view}` : "Väntar på en vy";
  const where = (client.places ?? []).map((place) => placeName(now, place)).join(", ");
  if (where) details.push(where + (client.side !== "both" ? ` · ${SIDES[client.side].toLowerCase()}` : ""));
  if (client.display) details.push(`${client.display.cols}×${client.display.rows}`);
  if (client.language && client.kind.startsWith("tmbox")) details.push(LANGUAGES[client.language] ?? client.language);
  return details.join(" · ");
}

export type ClientGroup = "all" | "waiting" | "boxes" | "stations" | "screens";
export const CLIENT_GROUPS: [ClientGroup, string, (client: Client) => boolean][] = [
  ["all", "Alla", () => true],
  ["waiting", "Väntar", (client) => client.status === "waiting"],
  ["boxes", "Boxar", (client) => client.kind.startsWith("tmbox")],
  ["stations", "TKL", (client) => client.kind === "tkl"],
  ["screens", "Skärmar", (client) => client.kind === "screen"],
];

/** Who did it: the client's name if it is still connected, else its id; the hub itself. */
export function actorName(who: Actor | null | undefined, clients: Client[]): string {
  if (!who || who.kind === "system") return "Hubben";
  if (who.kind === "automation") return "Automatiken";
  if (who.kind === "dispatcher") return "Trafikledningen";
  const known = clients.find((client) => client.client_id === who.id);
  return known ? known.name : (who.id ?? who.kind);
}

export function describe(event: DriftEvent): string {
  const data = event.data ?? {};
  const forward = data["forward"] ? ", flyttat fram" : "";
  if (event.kind === "clearance.answered") return (data["approved"] ? "Klart givet" : "Begäran nekad") + forward;
  if (event.kind === "clock.speed") return `Ny hastighet ${String(data["speed"])}×`;
  if (event.kind === "clearance.reminded" && data["count"]) return `Påminnelse ${String(data["count"])}, obesvarad begäran`;
  if (event.kind === "train.arrived") return (data["track"] ? `Ankomst spår ${String(data["track"])}` : "Ankomst") + forward;
  return EVENTS[event.kind] ?? event.kind;
}

export const trainNumber = (now: Now | null, train: string | null | undefined) => now?.legs.find((leg) => leg.train === train)?.train_number ?? "";
export const trainId = (now: Now | null, number: string) => now?.legs.find((leg) => leg.train_number === number)?.train ?? number;

export function modeText(place: AutomationPlace, clientName: (id: string) => string): string {
  let text = MODES[place.mode] ?? place.mode;
  if (place.mode === "automatic" && place.left_by) text += ` · ${LEFT_BY[place.left_by]}`;
  if (place.takes_over_in !== null && place.takes_over_in !== undefined) {
    text += ` · automatiken tar över om ${Math.ceil(place.takes_over_in / 60)} min`;
  }
  if (place.operator && place.mode !== "automatic") text += ` · ${clientName(place.operator)}`;
  return text;
}
