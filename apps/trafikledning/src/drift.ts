// What Trafikledningen says, and the small rules behind it, without React: the same words and
// choices as the old pages (hub/static/drift.js), so they can be tested on their own.
import type { Actor, AutomationPlace, Client, DayStatus, DriftEvent, LastJump, Leg, Now, Package, Refusal, Weekday } from "./api";
import { changeText, type DriftChange } from "./changes";
import { dayName } from "@trainmeet/hubben";
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
export const VIEWS: Record<string, string> = { clock: "Klocka, analog", clock_digital: "Klocka, digital", tracks: "Banöversikt" };
export const EVENTS: Record<string, string> = {
  "meet.started": "Träffen startade",
  "clock.started": "Klockan startade",
  "clock.stopped": "Klockan stoppades",
  "clock.speed": "Ny hastighet",
  "clock.jump": "Tidshopp",
  "clock.jump_undone": "Tidshoppet ångrat",
  "day.changed": "Ny dag",
  "day.settings": "Dygnsskiftet ändrat",
  "place.phone": "Telefonnumret ändrat",
  "change.made": "Driftändring",
  "change.applied": "Driftändringen gäller nu",
  "change.dropped": "Driftändringen släppt",
  "version.switched": "Ny version",
  "version.waiting": "Versionsbytet väntar på tåg som är ute",
  "version.called_off": "Versionsbytet avbrutet",
  "transition.done": "Drift upplåst",
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

// Tidshopp (TRAFIK-01, H37, F6): a minute of the game day on the slider, and what it does.
const pad = (value: number) => String(value).padStart(2, "0");
/** The clock time of a minute or a second count of the game day, as HH:MM. */
export const clockAt = (minutes: number) => `${pad(Math.floor(minutes / 60) % 24)}:${pad(Math.floor(minutes) % 60)}`;
export const hhmm = (seconds: number) => clockAt(Math.floor(seconds / 60));
export function minuteOf(time: string): number | null {
  const found = /^(\d{1,2}):(\d{2})$/.exec(time);
  if (!found) return null;
  const [hours, minutes] = [Number(found[1]), Number(found[2])];
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}
const clearances = (count: number) => (count === 1 ? "1 klarering" : `${count} klareringar`);
/** What a jump will do, said before it is made. */
export function jumpNote(open: number): string {
  const closing = open ? `${open === 1 ? "Den öppna klareringen" : `De ${open} öppna klareringarna`} stängs, och tågen` : "Tågen";
  return `${closing} ställs där tidtabellen har dem. Hoppet kan ångras.`;
}
const closedAfter = (count: number) => (count ? ` · ${clearances(count)} stängdes` : "");
/** The latest jump or new day, as Nu offers to undo it. */
export function jumpText(jump: Pick<LastJump, "from_time" | "to_time" | "closed"> & Partial<LastJump>): string {
  if (jump.kind === "day" && jump.game_day && jump.traffic_day) return `${dayTitle(jump.game_day, jump.traffic_day)} startade kl. ${jump.to_time}` + closedAfter(jump.closed);
  return `Tidshopp från ${jump.from_time} till ${jump.to_time}` + closedAfter(jump.closed);
}

// Dygnsskiftet (F7, TRAFIK-22, DRIFT-45): the next game day and its traffic day.
export const dayTitle = (gameDay: number, day: Weekday) => `Dag ${gameDay} · ${dayName(day)}`;
/** When the next day starts, and who starts it. */
export function dayNote(day: DayStatus): string {
  const reason = day.fixed ? "" : day.first ? `, en timme före första tåget ${day.first}` : ", dagen har inga tåg";
  const when = `Dygnsskiftet kl. ${day.time}${reason}`;
  const who = day.mode === "automatic" ? "Dagen startar av sig själv." : "Trafikledningen startar dagen.";
  return `Nästa: ${dayTitle(day.next_game_day, day.next_traffic_day).toLowerCase()}. ${when}. ${who}`;
}
/** Said when the time of the change has passed: by hand it is time, automatic it waits. */
export function dayDue(day: DayStatus): string | null {
  if (day.waiting) return "Dygnsskiftet väntar på tåg som är ute, högst 30 minuter.";
  if (day.due) return `Klockan har passerat dygnsskiftet. Starta dag ${day.next_game_day} när dagens tåg är inne.`;
  return null;
}

export function describe(event: DriftEvent, pkg: Package | null = null): string {
  const data = event.data ?? {};
  if (event.kind === "change.made" && data["change"]) {
    const text = changeText(data["change"] as DriftChange, pkg, data["train_number"] as string | null);
    return `Driftändring: ${text}` + (data["waiting"] ? ", väntar på tåget" : "") + (data["forced"] ? ", tvingad igenom" : "");
  }
  if (event.kind === "version.switched" && typeof data["version"] === "number") {
    if (data["small"]) return `Version ${data["version"]} togs direkt: små rättelser av tider och spår`;
    return `Version ${data["version"]} körs nu` + (data["forced"] ? ", tvingad igenom" : "");
  }
  if (event.kind === "version.waiting" && typeof data["version"] === "number") return `Byte till version ${data["version"]} väntar på tåg som är ute`;
  if (event.kind === "change.applied") return "Driftändringen gäller nu" + (data["forced"] ? ", tvingad igenom" : "");
  const forward = data["forward"] ? ", flyttat fram" : "";
  if (event.kind === "clock.jump" && typeof data["seconds"] === "number") {
    const closed = Array.isArray(data["closed"]) ? data["closed"].length : 0;
    return `Tidshopp till ${hhmm(data["seconds"])}` + (closed ? `, ${clearances(closed)} stängd${closed === 1 ? "" : "a"}` : "");
  }
  if (event.kind === "clock.jump_undone" && typeof data["seconds"] === "number") return `${data["kind"] === "day" ? "Nya dagen ångrad" : "Tidshoppet ångrat"}, klockan åter ${hhmm(data["seconds"])}`;
  if (event.kind === "day.changed" && typeof data["game_day"] === "number") {
    const closed = Array.isArray(data["closed"]) ? data["closed"].length : 0;
    return `${dayTitle(data["game_day"], data["traffic_day"] as Weekday)} startade` + (data["automatic"] ? " av sig själv" : "") + (closed ? `, ${clearances(closed)} stängd${closed === 1 ? "" : "a"}` : "");
  }
  if (event.kind === "place.phone") return typeof data["phone"] === "string" ? `Telefonnumret ${data["phone"]}` : "Telefonnumret borttaget";
  if (event.kind === "day.settings") {
    const how = data["mode"] === "automatic" ? "automatiskt" : "manuellt";
    return `Dygnsskiftet ${how}, ` + (typeof data["time"] === "string" ? `kl. ${data["time"]}` : "en timme före första tåget");
  }
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

// The log as a file (TRAFIK-20, F27): what Logg shows, oldest first, as CSV for a spreadsheet
// or as JSON. Semicolons and a byte order mark, so that a Swedish spreadsheet opens it as it is.
const cell = (value: string) => {
  // A cell a spreadsheet could take for a formula is written as text (CSV injection).
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[";\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};
export const csv = (rows: string[][]) => "\uFEFF" + rows.map((row) => row.map(cell).join(";")).join("\r\n") + "\r\n";

export function eventRows(events: DriftEvent[], now: Now | null, clients: Client[], pkg: Package | null = null): string[][] {
  const oldest = [...events].sort((a, b) => a.seq - b.seq);
  return [
    ["Nr", "Speldygn", "Tid", "Händelse", "Tåg", "Driftplats", "Vem", "Klockslag"],
    ...oldest.map((event) => [String(event.seq), String(event.game_day), event.model_time, describe(event, pkg), trainNumber(now, event.train), event.place ? placeName(now, event.place) : "", actorName(event.actor, clients), event.wall_time]),
  ];
}

export function refusalRows(refusals: Refusal[], now: Now | null): string[][] {
  return [
    ["Tid", "Vad", "Svar", "Driftplats", "Klient", "Klockslag"],
    ...[...refusals].reverse().map((refusal) => [refusal.model_time, refusal.what, refusal.message, refusal.place ? placeName(now, refusal.place) : "", refusal.client_id, refusal.wall_time]),
  ];
}

/** The file's name: the meet, the game day and the date. */
export const logFile = (now: Now | null, what: "logg" | "nekade", ending: "csv" | "json", today: Date = new Date()) =>
  `${what}-${now?.meet_id ?? "traffen"}-dag${now?.game_day ?? 1}-${today.toISOString().slice(0, 10)}.${ending}`;

/** Påbörjat och klart (DRIFT-47) are for Drift's own record: Logg shows only Lås upp. */
export const shown = (event: DriftEvent) =>
  event.kind !== "transition.begun" && (event.kind !== "transition.done" || Boolean((event.data ?? {})["unlocked"]));

