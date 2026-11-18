// Studio › Koppla in (#85): the calls to TKL's server and what the page says, without React. The
// types are generated from the contracts (contracts/tkl.py); nothing here is typed by hand.
// LocoNet is only in a local TKL: in the cloud the server says why, and the page shows it.
import type { components } from "../../../contracts/tkl";
import { call, TKL } from "./api";

type Schemas = components["schemas"];
export type KopplaIn = Schemas["trainmeet.tkl-1.koppla-in"];
export type KopplaObject = Schemas["trainmeet.tkl-1.koppla-in.TklKopplaObject"];
export type Card = Schemas["trainmeet.tkl-1.koppla-in.TklCard"];
export type Question = Schemas["trainmeet.tkl-1.koppla-in.TklQuestion"];
export type Loconet = Schemas["trainmeet.tkl-1.koppla-in.TklLoconet"];
export type Port = Schemas["trainmeet.tkl-1.port"];
export type LoconetType = Port["type"];
export type Listen = Schemas["trainmeet.tkl-1.listen"];
export type Heard = Schemas["trainmeet.tkl-1.listen.TklHeard"];
export type ObjectChange = Schemas["trainmeet.tkl-1.object-change"];
export type ObjectKind = ObjectChange["kind"];
export type AddressState = KopplaObject["state"];
export type FeedbackType = NonNullable<ObjectChange["feedback"]>;
export type Answer = Schemas["trainmeet.tkl-1.learn-answer"]["answer"];

const K = `${TKL}/studio/koppla-in`;

/** Every call Koppla in makes; the tests give their own. */
export type Calls = {
  view: () => Promise<KopplaIn>;
  ports: () => Promise<Port[]>;
  connect: (type: LoconetType, port: string | null, channel: number) => Promise<KopplaIn>;
  disconnect: () => Promise<KopplaIn>;
  discover: () => Promise<KopplaIn>;
  module: (card: number, module: string | null) => Promise<KopplaIn>;
  change: (change: ObjectChange) => Promise<KopplaIn>;
  learn: (kind: ObjectKind, name: string) => Promise<KopplaIn>;
  answer: (question: number, answer: Answer, object: string | null) => Promise<KopplaIn>;
  level: (level: number) => Promise<KopplaIn>;
  listen: () => Promise<Listen>;
  wagon: (trackCircuit: string, occupied: boolean) => Promise<KopplaIn>;
};

export const kopplaIn: Calls = {
  view: () => call<KopplaIn>(K),
  ports: () => call<Port[]>(`${K}/ports`),
  connect: (type, port, channel) => call<KopplaIn>(`${K}/connect`, "POST", { type, port, channel }),
  disconnect: () => call<KopplaIn>(`${K}/disconnect`, "POST"),
  discover: () => call<KopplaIn>(`${K}/discover`, "POST"),
  module: (card, module) => call<KopplaIn>(`${K}/card`, "PUT", { card, module }),
  change: (change) => call<KopplaIn>(`${K}/object`, "PUT", change),
  learn: (kind, name) => call<KopplaIn>(`${K}/learn`, "POST", { kind, name }),
  answer: (question, answer, object) => call<KopplaIn>(`${K}/answer`, "POST", { question, answer, object }),
  level: (level) => call<KopplaIn>(`${K}/level`, "POST", { level }),
  listen: () => call<Listen>(`${K}/lyssna`),
  wagon: (trackCircuit, occupied) => call<KopplaIn>(`${K}/latsas`, "POST", { track_circuit: trackCircuit, occupied }),
};

/** The four states (STUDIO-17), as the page names them. */
export const STATE_LABEL: Record<AddressState, string> = {
  grey: "Grå · ej kopplad",
  yellow: "Gul · adress angiven",
  green: "Grön · bekräftad på banan",
  without: "Utan adress",
};
export const STATE_CLASS: Record<AddressState, string> = { grey: "gra", yellow: "gul", green: "gron", without: "utan" };
export const KIND_TITLE: Record<ObjectKind, string> = { switch: "Växlar", signal: "Signaler", track_circuit: "Spårledningar" };
export const TYPE_LABEL: Record<LoconetType, string> = {
  locobuffer: "LocoBuffer USB",
  btlocobridge: "BTLocoBridge",
  pretend: "Låtsas-LocoNet (LocoNet ej ansluten)",
};
export const FEEDBACK_LABEL: Record<FeedbackType, string> = {
  card: "Från kortet",
  sensors: "Två givare",
  none: "Ingen",
  manual: "Manuell",
};
export const KINDS: ObjectKind[] = ["switch", "signal", "track_circuit"];

/** What learning by touching does for each kind (STUDIO-04). */
export function learnLabel(kind: ObjectKind): string {
  return kind === "switch" ? "Lägg om" : kind === "signal" ? "Skicka kör" : "Lär in";
}

/** How many objects are in each state, in the states' order. */
export function counts(objects: KopplaObject[]): [AddressState, number][] {
  const order: AddressState[] = ["green", "yellow", "grey", "without"];
  return order.map((s) => [s, objects.filter((o) => o.state === s).length]);
}

/** Where an object's address sits: its card, module and channel (STUDIO-18). */
export function where(object: KopplaObject): string {
  if (object.card === null || object.card === undefined) return "";
  const parts = [`Kort ${object.card}`];
  if (object.module) parts.push(object.module);
  if (object.channel) parts.push(`kanal ${object.channel}`);
  return parts.join(" · ");
}

/** The address as the row shows it. */
export function addressText(object: KopplaObject): string {
  if (object.state === "without") return "–";
  if (object.address === null || object.address === undefined) return "ingen";
  return `${object.address}${object.default ? " (förval)" : ""}${object.reversed ? " · omvänd" : ""}`;
}

export const BLUETOOTH = /^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/;

/** Anslut: what is asked, or why it cannot be. */
export function connectAsk(type: LoconetType, port: string, channel: number): { port: string | null; channel: number } | { error: string } {
  if (type === "pretend") return { port: null, channel: 1 };
  const given = port.trim();
  if (!given) return { error: type === "locobuffer" ? "Välj LocoBufferns port." : "Ange BTLocoBridgens adress eller dess parade port." };
  if (type === "btlocobridge" && !given.startsWith("/dev/") && !BLUETOOTH.test(given)) return { error: "Ange adressen som AA:BB:CC:DD:EE:FF, eller en port under /dev." };
  if (type === "locobuffer" && !given.startsWith("/dev/")) return { error: "LocoBufferns port ligger under /dev." };
  if (channel < 1 || channel > 30) return { error: "Kanalen är 1–30." };
  return { port: given, channel };
}

/** The owner's edit of one row. */
export type Edit = { address: string; without: boolean; reversed: boolean; feedback: FeedbackType | ""; straight: string; diverging: string };

export function editOf(object: KopplaObject): Edit {
  return {
    address: object.address === null || object.address === undefined ? "" : String(object.address),
    without: object.state === "without",
    reversed: object.reversed ?? false,
    feedback: object.feedback ?? "",
    straight: object.straight ? String(object.straight) : "",
    diverging: object.diverging ? String(object.diverging) : "",
  };
}

const number = (text: string): number | null => {
  const found = Number(text.trim());
  return text.trim() && Number.isInteger(found) && found >= 1 && found <= 4096 ? found : null;
};

/** The change the server takes for an edit, or why it is not one. */
export function changeOf(object: KopplaObject, edit: Edit): { change: ObjectChange } | { error: string } {
  const address = edit.address.trim() ? number(edit.address) : null;
  if (edit.address.trim() && address === null) return { error: "Adressen är ett heltal 1–4096." };
  const change: ObjectChange = { kind: object.kind, name: object.name, address, without: edit.without, reversed: edit.reversed, feedback: null, straight: null, diverging: null };
  if (object.kind === "switch" && edit.feedback) {
    change.feedback = edit.feedback;
    if (edit.feedback === "sensors") {
      change.straight = number(edit.straight);
      change.diverging = number(edit.diverging);
    }
  }
  return { change };
}

/** The time of a heard message, as a clock shows it. */
export function heardAt(heard: Heard): string {
  const at = new Date(heard.at);
  return Number.isNaN(at.getTime()) ? "" : at.toLocaleTimeString("sv-SE");
}

/** Run a call: the next view, or what went wrong in words with the problems. */
export async function attempt<T>(work: () => Promise<T>): Promise<{ done: T } | { error: string; problems: string[] }> {
  try {
    return { done: await work() };
  } catch (error) {
    const problems = error && typeof error === "object" && "problems" in error && Array.isArray(error.problems) ? (error.problems as string[]) : [];
    return { error: error instanceof Error ? error.message : "Det gick inte.", problems };
  }
}
