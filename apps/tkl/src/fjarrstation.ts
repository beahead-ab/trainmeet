// Fjärrstyrning, the station's side (#36 del b), in words and colours: the operating form for the
// bar over Ställverket (FR5), the station row with the automats and the name (FR32, FR34, FR39,
// FR43), the arrows at the main signals (FR33), and Studio's catalogue by line end with its quick
// choices (TKL46, FR10) and the automats' codes (FR40). Pure functions, no drawing.
import type { AutomatKind, AutomatSpec, FjarrState, FjarrStudio, FunctionShown, Outside, PlaceMode, Receiver, RemoteCandidate, Snapshot } from "./api";

export const MODE_NAMES: Record<PlaceMode, string> = {
  manned: "Bemannad",
  offered: "Erbjuden",
  remote: "Fjärrstyrd",
  no_contact: "Kontakt saknas",
  automatic: "Automatik",
};

/** The operating form as the bar says it, from the snapshot's mode and remote (FR5, FR8). */
export type ModeSaid = { mode: PlaceMode; title: string; detail: string | null };

export function modeSaid(snapshot: Snapshot | null): ModeSaid {
  if (!snapshot) return { mode: "manned", title: MODE_NAMES.manned, detail: null };
  const mode: PlaceMode = snapshot.mode ?? (snapshot.automatic ? "automatic" : "manned");
  const remote = snapshot.remote;
  const controller = remote?.controller ?? null;
  if (controller && (mode === "remote" || mode === "no_contact")) {
    const silent = remote?.controller_silent ?? null;
    const detail = mode === "no_contact" || (silent !== null && silent >= 45) ? `Ingen kontakt med ${controller.name} på ${silent ?? "?"} s` : null;
    return { mode, title: `Fjärrstyrs från ${controller.name}`, detail };
  }
  if (remote?.offer) {
    return { mode: "offered", title: `Erbjuden till ${remote.offer.to.name}`, detail: `${remote.offer.expires_in} s kvar` };
  }
  return { mode, title: MODE_NAMES[mode], detail: null };
}

/** Whom the station can be handed to now (FR2, FR3): a neighbour by the place it runs, a
 * remote interlocking by its name. */
export function receiverName(receiver: Receiver): string {
  return receiver.kind === "remote" ? `${receiver.name} (fjärrställverk)` : receiver.name;
}

/** Is the station remote-controlled, so that its own panel lays nothing (FR6, FR17)? */
export function controlled(snapshot: Snapshot | null, state: FjarrState | null | undefined): boolean {
  return Boolean(snapshot?.remote?.controller) || Boolean(state?.controller);
}

// --- Studio: the catalogue by line end, and the quick choices --------------------------------------

export type ExitGroup = { exit: string; name: string; into: RemoteCandidate[]; out: RemoteCandidate[] };

/** The candidates by line end, in from it and out to it, in the order Studio got them. */
export function grouped(candidates: RemoteCandidate[]): ExitGroup[] {
  const groups: ExitGroup[] = [];
  for (const c of candidates) {
    let group = groups.find((g) => g.exit === c.exit);
    if (!group) {
      group = { exit: c.exit, name: c.exit_name, into: [], out: [] };
      groups.push(group);
    }
    (c.direction === "in" ? group.into : group.out).push(c);
  }
  return groups;
}

export type Quick = { kind: "all" } | { kind: "none" } | { kind: "except"; track: string } | { kind: "only"; tracks: string[] };

/** Snabbval (TKL46): alla, inga, alla utom ett spår, bara vissa spår. */
export function quick(candidates: RemoteCandidate[], rule: Quick): string[] {
  switch (rule.kind) {
    case "all":
      return candidates.map((c) => c.id);
    case "none":
      return [];
    case "except":
      return candidates.filter((c) => c.track !== rule.track).map((c) => c.id);
    case "only":
      return candidates.filter((c) => rule.tracks.includes(c.track)).map((c) => c.id);
  }
}

/** The station tracks the candidates reach, in their order, with their labels. */
export function tracksOf(candidates: RemoteCandidate[]): { id: string; label: string }[] {
  const seen = new Map<string, string>();
  for (const c of candidates) if (!seen.has(c.track)) seen.set(c.track, c.track_label);
  return [...seen].map(([id, label]) => ({ id, label }));
}

const KIND_CODE: Record<AutomatKind, string> = { a1: "A1", a2: "A2", a3: "A3", an: "AN", au: "AU", local_release: "L" };
export const KIND_NAMES: Record<AutomatKind, string> = {
  a1: "A1 enstaka möte",
  a2: "A2 enstaka förbigång",
  a3: "A3 automatdrift",
  an: "AN automatdrift på nedspåret",
  au: "AU automatdrift på uppspåret",
  local_release: "Lokalfrigivningsautomat",
};

/** A new automat's code (FR40): its kind, and the entry signal's number when the station has
 * another of the same kind, as AN21 and AN121. */
export function codeFor(kind: AutomatKind, signals: string[], automats: AutomatSpec[]): string {
  const base = KIND_CODE[kind];
  const same = automats.filter((a) => a.kind === kind).length;
  return (same > 0 && signals[0] ? `${base}${signals[0]}` : base).slice(0, 12);
}

/** The automats with the codes renumbered by the rule: one of a kind is plain, several get their
 * entry signal (FR40). Only codes Studio gave are changed. */
export function withCodes(automats: AutomatSpec[]): AutomatSpec[] {
  return automats.map((a) => {
    if (a.kind === "local_release" || a.kind === "a1" || a.kind === "a2" || a.kind === "a3") return a;
    const many = automats.filter((b) => b.kind === a.kind).length > 1;
    const wanted = many && a.signals?.[0] ? `${KIND_CODE[a.kind]}${a.signals[0]}` : KIND_CODE[a.kind];
    const studios = a.code === KIND_CODE[a.kind] || a.code.startsWith(KIND_CODE[a.kind]);
    return studios ? { ...a, code: wanted.slice(0, 12) } : a;
  });
}

// --- Ställverket: the station row and the arrows ---------------------------------------------------

/** The station's automats as Ställverket uses them: the owner's, else Studio's suggestion, and a
 * local release automat for every local release function the owner left out (FR39). */
export function specsOf(studio: FjarrStudio | null): AutomatSpec[] {
  if (!studio) return [];
  const given = [...(studio.settings.automats ?? [])];
  const named = new Set(given.filter((a) => a.kind === "local_release").map((a) => a.function));
  const codes = new Set(given.map((a) => a.code.toLowerCase()));
  for (const local of (studio.suggested ?? []).filter((a) => a.kind === "local_release")) {
    if (named.has(local.function) || codes.has(local.code.toLowerCase())) continue;
    given.push(local);
  }
  return given;
}

export const ROW_COLOURS = {
  remote: "#9aa3ad", // grått: fjärrstyrd (FR32)
  manned: "#3d8bfd", // blått: bemannad
  on: "#ffd84a", // gult: en inkopplad stationsautomat (FR34)
  off: "#9aa3ad",
  local: "#3d8bfd", // blått: lokalfrigivningen inkopplad (FR43)
} as const;

export type RowCode = {
  code: string;
  kind: AutomatKind;
  on: boolean;
  /** Who switched it on: from afar, on the spot or by itself. */
  by: "remote" | "station" | "automat" | null;
  /** In the magazine: a route waits for this automat (FR45). */
  magazine: boolean;
  /** The local release's panel function, for a local release code (FR39). */
  fn: string | null;
  /** The people on site have asked for it and not been answered. */
  asked: boolean;
  colour: string;
};

/** The station row (FR43): the station automats, A3, A2 and A1 first, then the rest; and under
 * the name the local release automats. A switched-on automat is yellow, a local area blue. */
export function stationRow(specs: AutomatSpec[], state: FjarrState | null | undefined, functions: FunctionShown[], snapshot: Snapshot | null): { automats: RowCode[]; locals: RowCode[] } {
  const on = new Map((state?.automats ?? []).map((a) => [a.code, a]));
  const waiting = new Set((state?.magazine ?? []).map((m) => m.automat));
  const asked = new Set((snapshot?.remote?.local_requests ?? []).map((r) => r.code));
  const order: AutomatKind[] = ["a3", "a2", "a1", "an", "au"];
  const automats = specs
    .filter((s) => s.kind !== "local_release")
    .sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind))
    .map((s): RowCode => {
      const found = on.get(s.code);
      return { code: s.code, kind: s.kind, on: !!found, by: found?.by ?? null, magazine: waiting.has(s.code), fn: null, asked: false, colour: found ? ROW_COLOURS.on : ROW_COLOURS.off };
    });
  const locals = specs
    .filter((s) => s.kind === "local_release")
    .map((s): RowCode => {
      const fn = functions.find((f) => f.name === s.function) ?? null;
      const lit = !!fn?.on;
      return { code: s.code, kind: s.kind, on: lit, by: null, magazine: false, fn: s.function ?? null, asked: asked.has(s.code), colour: lit ? ROW_COLOURS.local : ROW_COLOURS.off };
    });
  return { automats, locals };
}

/** The arrows at the main signals (FR33): only while the station is remote-controlled, at the
 * signals the catalogue's routes start at; green where a switched-on automat lays the routes,
 * red where the one who controls the station does. */
export function arrowsOf(outside: Outside | null, specs: AutomatSpec[], state: FjarrState | null | undefined, remote: boolean): Record<string, "red" | "green"> {
  if (!remote || !outside) return {};
  const on = (state?.automats ?? []).map((a) => specs.find((s) => s.code === a.code)).filter((s): s is AutomatSpec => !!s);
  const whole = on.some((s) => s.kind === "a1" || s.kind === "a2" || s.kind === "a3");
  const signals = new Set(on.flatMap((s) => s.signals ?? []));
  const found: Record<string, "red" | "green"> = {};
  for (const route of outside.remote_routes ?? []) {
    found[route.start] = whole || signals.has(route.start) ? "green" : "red";
  }
  return found;
}
