// Studio › Inställningar › Stream Deck (#86 del c): what the page does with the owner's changes,
// without React. The owner's changes are deviations from the default per size (SD32, SD40), in
// stable ids: a key by what it is, a page by its kind and name, a cell only as where a key goes.
// Every change here only adds a deviation; TKL's server lays them on the default, makes them the
// fewest that give the same profile, says Att kolla for what cannot be laid on, and refuses with
// the reason what may not be changed: colours, symbols and what a gesture means (SD3, SD43).
import type { DeckAction, DeckButton, DeckChange, DeckChecks, DeckDeviation, DeckKey, DeckMode, DeckModelId, DeckPage, DeckPageRef, DeckProfile, DeckSettings, DeckStatus, DeckSuggestion, DeckToCheck } from "./api";

export type KeyType = DeckKey["type"];
export type Tab = "sidor" | "deck" | "prova";
export type Look = Pick<DeckKey, "text" | "under" | "press" | "hold" | "number" | "dim" | "confirm">;
/** What is dragged onto a cell: a row of Knappar, or a key from another cell of the page. */
export type Dragged = { from: "list"; index: number } | { from: "cell"; cell: number };

export const SIZES: DeckModelId[] = ["mini", "neo", "15", "xl", "plus", "plus-xl", "studio", "pedal"];
export const MODE_NAMES: Record<DeckMode, string> = { tagen: "Tågen", platser: "Platser", sparplan: "Spårplan" };
export const ACTION_NAMES: Record<DeckAction, string> = {
  los: "Lös ut",
  ankommit: "Ankommit",
  kor: "Kör",
  avbryt: "Avbryt",
  tillbaka: "Tillbaka",
  las: "Lås",
  lagg: "Lägg vägen",
  "los-vagen": "Lös ut vägen",
  "los-alla": "Lös ut alla",
  noll: "Noll",
  nodutlosning: "Nödutlösning",
  ingenting: "Ingenting",
};
export const TYPE_NAMES: Record<KeyType, string> = {
  train: "Tågknapp",
  line: "Linjeknapp",
  alarm: "Larm och klocka",
  track: "Spårknapp",
  place: "Plats",
  part: "Del",
  signal: "Signal",
  daily: "Dagens väg",
  favourite: "Favorit",
  tile: "Spårplanens bit",
  cell: "Utsnittets ruta",
  pan: "Panorering",
  mode: "Läge",
  next: "Nästa sida",
  page: "Nästa sida",
  action: "Funktion",
  panel: "Panelfunktion",
  route: "Snabbväg",
};
/** What a press and a hold may do, per type: the fixed list (SD43), as TKL's server has it.
 * Lös ut alla, Noll and Nödutlösning are holds, never a press (SD29). */
export const PRESS: Partial<Record<KeyType, DeckAction[]>> = {
  route: ["lagg", "kor", "ingenting"],
  action: ["los", "ankommit", "kor", "avbryt", "tillbaka", "las", "ingenting"],
  panel: ["ingenting"],
};
export const HOLD: Partial<Record<KeyType, DeckAction[]>> = {
  route: ["los-vagen", "ingenting"],
  action: ["los", "los-alla", "noll", "nodutlosning", "avbryt", "ingenting"],
  panel: ["ingenting"],
};
/** What a press and a hold do when the owner has chosen nothing: the catalogue's. */
export const DEFAULT_GESTURE: Partial<Record<KeyType, [string, string]>> = {
  route: ["Lägg vägen", "Lös ut vägen"],
  action: ["Funktionen", "Lös ut: alla"],
  panel: ["Slå på eller av", "Ingenting"],
};
/** Never on a pedal (SD55). */
export const NOT_ON_A_PEDAL: DeckAction[] = ["los-alla", "noll", "nodutlosning"];
export const PEDAL_ACTIONS: DeckAction[] = ["los", "ankommit", "kor", "avbryt"];
export const SUGGESTIONS: [DeckSuggestion, string][] = [
  ["geografiskt", "Geografiskt"],
  ["dagens", "Dagens vägar"],
  ["mest-anvanda", "Mest använda"],
];
export const HOLDS: [NonNullable<DeckSettings["hold"]>, string][] = [
  ["kort", "Kort · 0,4 sekunder"],
  ["normal", "Normal · 0,6 sekunder"],
  ["lang", "Lång · 1 sekund"],
];
export const SLEEPS: [number, string][] = [
  [0, "Aldrig"],
  [5, "Efter 5 minuter utan tryck"],
  [10, "Efter 10 minuter utan tryck"],
  [30, "Efter 30 minuter utan tryck"],
  [60, "Efter en timme utan tryck"],
];
export const GROUPS: [DeckButton["group"], string][] = [
  ["trafiken", "Trafiken"],
  ["tagvagar", "Tågvägar"],
  ["vaxlingsvagar", "Växlingsvägar"],
  ["platser", "Platser"],
  ["signaler", "Signaler"],
  ["funktioner", "Funktioner"],
];
const IDENTITY = ["type", "slot", "point", "place", "part", "dx", "dy", "rect", "pan", "action", "function", "route"] as const;
const LOOK = ["text", "under", "press", "hold", "number", "dim", "confirm"] as const;
const ARROW = "→";

/** What a key is: the same fields as TKL's server finds it by. */
export function keyId(key: DeckKey | null | undefined): string {
  if (!key) return "";
  const found: [string, unknown][] = [];
  for (const name of [...IDENTITY].sort()) {
    const value = key[name];
    if (value === null || value === undefined) continue;
    found.push([name, name === "route" && key.route ? [key.route.start, key.route.end, key.route.kind] : value]);
  }
  return JSON.stringify(found);
}

/** A key with every field, as the contract has it: nothing given is nothing. */
export function fullKey(given: Partial<DeckKey> & Pick<DeckKey, "type">): DeckKey {
  return {
    slot: null,
    point: null,
    place: null,
    part: null,
    page: null,
    dx: null,
    dy: null,
    rect: null,
    pan: null,
    action: null,
    function: null,
    route: null,
    text: "",
    under: "",
    press: null,
    hold: null,
    number: null,
    dim: null,
    confirm: null,
    ...given,
  };
}

/** A key by what it is, without the owner's text and the rest. */
export function bare(key: DeckKey): DeckKey {
  const found: Partial<DeckKey> = {};
  for (const name of IDENTITY) {
    const value = key[name];
    if (value !== null && value !== undefined) Object.assign(found, { [name]: value });
  }
  return fullKey({ ...found, type: key.type });
}

type Given = Partial<DeckDeviation> & Pick<DeckDeviation, "change">;

/** A deviation with every field: nothing given changes nothing. */
export function deviation(given: Given): DeckDeviation {
  return { page: null, key: null, cell: null, text: null, under: null, press: null, hold: null, number: null, dim: null, confirm: null, mode: null, order: [], pedal: null, ...given };
}

export const refOf = (page: Pick<DeckPage, "kind" | "name">): DeckPageRef => ({ kind: page.kind, name: page.name });
export const sameRef = (a: DeckPageRef | null | undefined, b: DeckPageRef | null | undefined) => !!a && !!b && a.kind === b.kind && a.name === b.name;

/** A key dropped on a cell: one from the same page moves there, and what stood there takes its
 * place; one from Knappar is added, and what stood there goes (SD41). The fixed row is not
 * changed here (SD27). */
export function dropped(deviations: DeckDeviation[], page: DeckPage, fixed: number[], key: DeckKey, cell: number): DeckDeviation[] {
  if (fixed.includes(cell)) return deviations;
  const ref = refOf(page);
  const id = keyId(key);
  const here = page.keys.findIndex((k) => keyId(k) === id);
  if (here === cell) return deviations;
  if (here >= 0) return [...deviations, deviation({ change: "flytta", page: ref, key: bare(key), cell })];
  const occupant = page.keys[cell];
  const out = occupant ? [deviation({ change: "ta-bort", page: ref, key: bare(occupant) })] : [];
  return [...deviations, ...out, deviation({ change: "lagg-till", page: ref, key: fullKey(key), cell })];
}

export function removed(deviations: DeckDeviation[], page: DeckPage, key: DeckKey): DeckDeviation[] {
  return [...deviations, deviation({ change: "ta-bort", page: refOf(page), key: bare(key) })];
}

/** The owner's text, line under, press, hold and what the key shows (SD43). */
export function edited(deviations: DeckDeviation[], page: DeckPage, key: DeckKey, change: Partial<Look>): DeckDeviation[] {
  const kept = Object.fromEntries(Object.entries(change).filter(([name]) => (LOOK as readonly string[]).includes(name))) as Partial<Look>;
  return [...deviations, deviation({ change: "andra", page: refOf(page), key: bare(key), ...kept })];
}

export function pageAdded(deviations: DeckDeviation[], name: string, mode: DeckMode): DeckDeviation[] {
  return [...deviations, deviation({ change: "ny-sida", page: { kind: "egen", name }, mode })];
}

export function pageRemoved(deviations: DeckDeviation[], page: DeckPage): DeckDeviation[] {
  return [...deviations, deviation({ change: "ta-bort-sida", page: refOf(page) })];
}

/** A page one step back or forth among its mode's pages. */
export function pageMoved(deviations: DeckDeviation[], profile: DeckProfile, page: DeckPage, step: -1 | 1): DeckDeviation[] {
  const listed = (profile.pages ?? []).filter((p) => p.mode === page.mode && (p.listed ?? true));
  const at = listed.findIndex((p) => sameRef(refOf(p), refOf(page)));
  const to = at + step;
  if (at < 0 || to < 0 || to >= listed.length) return deviations;
  const order = listed.map(refOf);
  [order[at], order[to]] = [order[to] as DeckPageRef, order[at] as DeckPageRef];
  return [...deviations, deviation({ change: "ordning", order })];
}

export function pedalChosen(deviations: DeckDeviation[], pedal: number, key: DeckKey | null): DeckDeviation[] {
  return [...deviations.filter((d) => !(d.change === "pedal" && d.pedal === pedal)), deviation({ change: "pedal", pedal, key })];
}

/** Återställ sidan: the page as the default has it; a page of the owner's own goes. */
export function pageReset(deviations: DeckDeviation[], ref: DeckPageRef): DeckDeviation[] {
  return deviations.filter((d) => !sameRef(d.page, ref) && !(d.change === "ordning" && (d.order ?? []).some((r) => sameRef(r, ref))));
}

/** A snabbväg from the start and the goal clicked in the miniature (SD42): a train route when
 * the station has one, else a shunting route. */
export function routeKey(buttons: DeckButton[], start: string, end: string): DeckKey | null {
  const found = buttons.filter((b) => b.key.type === "route" && b.key.route?.start === start && b.key.route?.end === end);
  const best = found.find((b) => b.key.route?.kind === "train") ?? found[0];
  return best ? best.key : null;
}

/** The first cell of a page a new key can go to: not the fixed row, and empty. */
export function freeCell(page: DeckPage, fixed: number[]): number | null {
  const at = page.keys.findIndex((k, i) => !k && !fixed.includes(i));
  return at >= 0 ? at : null;
}

/** The cell of a key on a page, for Att kolla and the checks to point at. */
export function cellOf(page: DeckPage | undefined, key: DeckKey | null | undefined): number | null {
  if (!page || !key) return null;
  const id = keyId(key);
  const at = page.keys.findIndex((k) => keyId(k) === id);
  return at >= 0 ? at : null;
}

/** Where an Att kolla points: its page and the key's cell there, when they still exist. */
export function whereToCheck(profile: DeckProfile, check: DeckToCheck): { page: number; cell: number | null } | null {
  const page = (profile.pages ?? []).findIndex((p) => sameRef(refOf(p), check.page));
  if (page < 0) return null;
  return { page, cell: cellOf(profile.pages?.[page], check.key) };
}

/** The checks in words (SD44): every route reached, how many by a snabbväg, and the problems. */
export function checkText(checks: DeckChecks): { ok: boolean; text: string } {
  const unreached = checks.routes - checks.reached;
  if (unreached > 0) return { ok: false, text: `${unreached} av ${checks.routes} vägar nås inte från decket` };
  return { ok: true, text: `Alla ${checks.routes} vägar nås · ${checks.quick ?? 0} som snabbväg` };
}

export function changesText(count: number): string {
  if (!count) return "Förval ur stationen";
  return `Förval ur stationen · ${count} ${count === 1 ? "egen ändring" : "egna ändringar"}`;
}

/** The key in words, as the properties show it. */
export function keyWords(key: DeckKey): string {
  switch (key.type) {
    case "route":
      return key.route ? `${key.route.start} ${ARROW} ${key.route.end} · ${key.route.kind === "train" ? "tågväg" : "växlingsväg"}` : "";
    case "signal":
      return `Signal ${key.point ?? ""}`;
    case "place":
    case "track":
      return `Plats ${key.place ?? ""}`;
    case "action":
      return key.action ? ACTION_NAMES[key.action] : "";
    case "panel":
      return key.function ?? "";
    default:
      return key.slot ? `${TYPE_NAMES[key.type]} ${key.slot}` : TYPE_NAMES[key.type];
  }
}

/** A pedal's choice as one value for a select: an action, a snabbväg or a panel function. */
export function pedalValue(key: DeckKey | null | undefined): string {
  if (!key) return "";
  if (key.type === "action" && key.action) return `action:${key.action}`;
  if (key.type === "route" && key.route) return `route:${key.route.kind}:${key.route.start}:${key.route.end}`;
  if (key.type === "panel" && key.function) return `panel:${key.function}`;
  return "";
}

export function pedalKey(value: string): DeckKey | null {
  const [kind, ...rest] = value.split(":");
  if (kind === "action" && rest[0]) return fullKey({ type: "action", action: rest[0] as DeckAction });
  if (kind === "route" && rest.length === 3) return fullKey({ type: "route", route: { kind: rest[0] as "train" | "shunting", start: rest[1] as string, end: rest[2] as string } });
  if (kind === "panel" && rest.length) return fullKey({ type: "panel", function: rest.join(":") });
  return null;
}

export const CONNECTION: Record<string, string> = { usb: "Inkopplat över USB", webhid: "Inkopplat med WebHID", skarm: "Visas i ställverket" };

/** A deck's connection in words, and whether it is there now. */
export function connectionText(deck: Pick<DeckStatus, "connection">): { on: boolean; text: string } {
  return deck.connection ? { on: true, text: CONNECTION[deck.connection] ?? deck.connection } : { on: false, text: "Inte inkopplat" };
}

/** The size whose profile a deck gets (SD54). */
export function sizeOfModel(model: DeckModelId | null | undefined): DeckModelId | null {
  if (!model) return null;
  if (model === "module-6") return "mini";
  if (model === "module-15") return "15";
  if (model === "module-32") return "xl";
  return model;
}

/** What Studio, Deck changes for one deck: what is not given stays as it is (SD46). */
export function deckChange(given: Partial<DeckChange>): DeckChange {
  return { name: null, brightness: null, hold: null, sleep: null, lock_key: null, opens_in: null, opens_on: null, workplace: null, ...given };
}
