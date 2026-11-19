// Studio › Dela stationen (#87 del b, TKL99, TKL101, TKL103): what the page does to the parts,
// without React. A part is data in the station model; TKL's server works out its streets and
// routes out from the track plan and checks it (tkl/studio/dela.py). Here the owner's clicks and
// choices change the parts, which the page then saves as a draft. Nothing here names a station
// (RS13).
import type { BorderSwitch, Dela, DelaCheck, DelaFound, PartSide, RouteOut, StationPart, SwitchStreet } from "./api";
import { toggleName, toggleSection, type Sections } from "./omrade";

/** What a click on the panel does: the area, the part's own switches, the border switches, the
 * signals in the area, or the signals at the border. */
export type Tool = "area" | "switches" | "border" | "signals" | "border_signals";
export const TOOLS: { tool: Tool; label: string; hint: string }[] = [
  { tool: "area", label: "Område", hint: "Klicka på spåren som hör till delen, sektion för sektion. Klicka igen för att ta bort." },
  { tool: "switches", label: "Egna växlar", hint: "Klicka på växlarna delen lägger själv, fritt inom området." },
  { tool: "border", label: "Gränsväxlar", hint: "Klicka på växlarna vid gränsen. Stationen äger dem tills du väljer delen (TKL99)." },
  { tool: "signals", label: "Signaler", hint: "Klicka på signalerna i området." },
  { tool: "border_signals", label: "Gränssignaler", hint: "Klicka på signalerna vid gränsen, där vägarna ut går över." },
];
export const SIDES: [PartSide, string][] = [
  ["left", "Vänster"],
  ["right", "Höger"],
];
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/;
const FOLD: Record<string, string> = { å: "a", ä: "a", ö: "o", Å: "A", Ä: "A", Ö: "O", é: "e", É: "E", æ: "ae", ø: "o" };

/** An id from a name, as the outside folds names (tkl/standard/outside.py), free among `taken`. */
export function idFrom(name: string, taken: string[]): string {
  const folded = [...name.trim()].map((c) => FOLD[c] ?? c).join("");
  const base =
    folded
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^A-Za-z0-9._:-]+/g, "-")
      .replace(/^[._:-]+|-+$/g, "")
      .slice(0, 70)
      .toLowerCase() || "del";
  let made = base;
  for (let n = 2; taken.includes(made); n++) made = `${base}-${n}`;
  return made;
}

export const validId = (id: string) => ID.test(id);

/** A new part: a name and an id, no area yet, the default rules (TKL99). */
export function newPart(parts: StationPart[]): StationPart {
  const names = parts.map((p) => p.name);
  let name = "Ny del";
  for (let n = 2; names.includes(name); n++) name = `Ny del ${n}`;
  return {
    id: idFrom(name, parts.map((p) => p.id)),
    name,
    track_circuits: [],
    pieces: [],
    switches: [],
    signals: [],
    border: [],
    border_signals: [],
    own_place: false,
    place: null,
    code: null,
    rules: { lays_towards_part: true, one_way: true },
    streets: [],
    routes_out: [],
    note: null,
    origin: null,
  };
}

/** The parts with one changed. */
export function changePart(parts: StationPart[], id: string, change: (part: StationPart) => StationPart): StationPart[] {
  return parts.map((p) => (p.id === id ? change(p) : p));
}

/** A part renamed: its id follows the name while it is the one the name gave. */
export function renamed(part: StationPart, name: string, parts: StationPart[]): StationPart {
  const others = parts.filter((p) => p !== part).map((p) => p.id);
  const followed = part.id === idFrom(part.name, others);
  return { ...part, name, id: followed ? idFrom(name, others) : part.id };
}

/** A click on a piece: its section in or out of the area (omrade.ts). */
export function clickPiece(part: StationPart, piece: string, sections: Sections): StationPart {
  return toggleSection(part, piece, sections);
}

/** A click on a switch with a tool: the part's own switch, or a border switch with the owner and
 * position Studio suggests (TKL99). A switch is one or the other. */
export function clickSwitch(part: StationPart, number: string, tool: Tool, found?: DelaFound | null): StationPart {
  const border = part.border ?? [];
  if (tool === "switches") {
    return { ...part, switches: toggleName(part.switches, number), border: border.filter((b) => b.switch !== number) };
  }
  if (tool !== "border") return part;
  if (border.some((b) => b.switch === number)) return { ...part, border: border.filter((b) => b.switch !== number) };
  const suggested = (found?.border_switches ?? []).find((b) => b.switch === number);
  const made: BorderSwitch = suggested ?? { switch: number, owner: "station", towards_part: "+" };
  return { ...part, border: [...border, { ...made, owner: made.owner ?? "station" }], switches: (part.switches ?? []).filter((s) => s !== number) };
}

/** A click on a signal with a tool: in the area, or at the border. */
export function clickSignal(part: StationPart, name: string, tool: Tool): StationPart {
  if (tool === "signals") return { ...part, signals: toggleName(part.signals, name) };
  if (tool === "border_signals") return { ...part, border_signals: toggleName(part.border_signals, name) };
  return part;
}

/** A border switch's owner or position towards the part, changed. */
export function setBorder(part: StationPart, number: string, change: Partial<BorderSwitch>): StationPart {
  return { ...part, border: (part.border ?? []).map((b) => (b.switch === number ? { ...b, ...change } : b)) };
}

/** The streets Studio computed for an end that the part does not have yet (RANG-02). */
export function streetsAt(found: DelaFound | null | undefined, part: StationPart, side: PartSide): SwitchStreet[] {
  const have = part.streets ?? [];
  return (found?.streets ?? []).filter((s) => s.side === side && !have.some((h) => h.side === s.side && h.track === s.track));
}

/** A street added from Studio's, with an id of its own in the part. */
export function addStreet(part: StationPart, street: SwitchStreet): StationPart {
  const have = part.streets ?? [];
  let id = street.id;
  for (let n = 2; have.some((s) => s.id === id); n++) id = `${street.id}-${n}`;
  return { ...part, streets: [...have, { ...street, id }] };
}

export function removeStreet(part: StationPart, id: string): StationPart {
  return { ...part, streets: (part.streets ?? []).filter((s) => s.id !== id) };
}

export function renameStreet(part: StationPart, id: string, name: string): StationPart {
  return { ...part, streets: (part.streets ?? []).map((s) => (s.id === id ? { ...s, name } : s)) };
}

const same = (a: RouteOut, b: RouteOut) => a.start === b.start && a.end === b.end;

/** Whether the part has a route out from the same start to the same end. */
export function hasRouteOut(part: StationPart, out: RouteOut): boolean {
  return (part.routes_out ?? []).some((r) => same(r, out));
}

/** A route out chosen from the station's routes, or taken away (RANG-03). */
export function toggleRouteOut(part: StationPart, out: RouteOut): StationPart {
  const have = part.routes_out ?? [];
  if (have.some((r) => same(r, out))) return { ...part, routes_out: have.filter((r) => !same(r, out)) };
  let id = out.id;
  for (let n = 2; have.some((r) => r.id === id); n++) id = `${out.id}-${n}`;
  return { ...part, routes_out: [...have, { ...out, id }] };
}

export function renameRouteOut(part: StationPart, id: string, name: string): StationPart {
  return { ...part, routes_out: (part.routes_out ?? []).map((r) => (r.id === id ? { ...r, name } : r)) };
}

/** The station's routes out of the area that Studio found, by end, in the order it gave. */
export function routesOutAt(found: DelaFound | null | undefined, side: PartSide): RouteOut[] {
  return (found?.routes_out ?? []).filter((r) => (r.side ?? "right") === side);
}

/** The checks, the problems first, and how many stop Använd. */
export function checkList(checks: DelaCheck[] | null | undefined): { list: DelaCheck[]; problems: number } {
  const list = [...(checks ?? [])].sort((a, b) => Number(b.problem ?? true) - Number(a.problem ?? true));
  return { list, problems: list.filter((c) => c.problem ?? true).length };
}

/** What a click on a check shows: the part, and the object on the panel or in the lists. */
export type Marked = { kind: NonNullable<DelaCheck["kind"]>; id: string } | null;

export function markOf(check: DelaCheck): Marked {
  return check.kind && check.id ? { kind: check.kind, id: check.id } : null;
}

/** The parts as JSON: whether two drafts are the same. */
export const sameParts = (a: StationPart[], b: StationPart[]) => JSON.stringify(a) === JSON.stringify(b);

/** The draft as Rita keeps its drawing: every change saved a moment later, the answer counting
 * only when nothing newer was sent, and everything sent before Använd. */
export class DraftSaver {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending: StationPart[] | null = null;
  private sent = 0;

  constructor(
    private readonly send: (parts: StationPart[]) => Promise<Dela>,
    private readonly shown: (view: Dela) => void,
    private readonly failed: (message: string) => void,
    private readonly saving: (on: boolean) => void,
    private readonly delay = 400,
  ) {}

  /** A change: saved after the delay, unless another comes first. */
  later(parts: StationPart[]): void {
    this.pending = parts;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.now(parts), this.delay);
  }

  async now(parts: StationPart[]): Promise<void> {
    const number = ++this.sent;
    this.pending = null;
    this.saving(true);
    try {
      const answer = await this.send(parts);
      if (number === this.sent) this.shown(answer);
    } catch (error) {
      if (number === this.sent) this.failed(error instanceof Error ? error.message : "Delarna sparades inte.");
    } finally {
      if (number === this.sent) this.saving(false);
    }
  }

  /** What is waiting is sent now: before Använd. */
  async flush(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.pending) await this.now(this.pending);
  }

  /** Släng utkastet: nothing waiting is sent, and no answer on the way counts. */
  drop(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.pending = null;
    this.sent++;
  }
}
