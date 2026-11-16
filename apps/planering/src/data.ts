// Data's words and rules without React: the facts behind each row (source and certainty), the
// trains' days and the import's report. The same as the old page (hub/static/planering.js).
import type { Draft, ImportPreview } from "./api";
import { number } from "./text";

export type Package = NonNullable<Draft["package"]>;
export type Place = NonNullable<Package["places"]>[number];
export type Section = NonNullable<Package["sections"]>[number];
export type Part = NonNullable<Section["parts"]>[number];
export type Train = NonNullable<Package["trains"]>[number];
export type Call = Train["calls"][number];
export type Duty = NonNullable<Package["duties"]>[number];
export type Turn = NonNullable<Package["turns"]>[number];
export type Shunting = NonNullable<Package["shunting"]>[number];
export type TrainTypeRule = NonNullable<NonNullable<Draft["rulebook"]>["train_types"]>[number];
export type Source = NonNullable<Draft["sources"]>[number];
export type Fact = NonNullable<Draft["facts"]>[number];
export type Origin = Fact["origins"][number];
export type Question = NonNullable<Draft["questions"]>[number];

export const KINDS: Record<string, string> = { manned: "Bemannad", remote: "Fjärrstyrd", unmanned: "Obemannad", shadow_yard: "Skuggbangård", halt: "Industri/hållplats" };
export const KINDS_MANY: Record<string, string> = { manned: "bemannade", remote: "fjärrstyrda", unmanned: "obemannade", shadow_yard: "skuggbangårdar", halt: "industrier/hållplatser" };
export const CERTAINTY: Record<string, string> = { sure: "säker", likely: "trolig", unsure: "osäker", confirmed: "bekräftad" };
export const CONTENT: Record<string, string> = { passengers: "Resande", goods: "Gods", service: "Tjänst" };
export const MODES: Record<string, string> = { requested: "Begärd", direct: "Direkt" };
export const TRACKS: Record<string, string> = { single: "Enkel", double: "Dubbel" };
export const LEVELS: [number, string][] = [
  [1, "ST"],
  [2, "+ BILD"],
  [3, "+ GRAF"],
  [4, "JSON"],
];
/** Rows shown per block before Visa alla. */
export const SHOWN = 300;

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_NAMES = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];

export const plural = (count: number, one: string, many: string) => `${number(count)} ${count === 1 ? one : many}`;

/** A train's days: Dagl, a run such as Mån–Fre, or the days one by one. */
export function days(list: readonly string[]): string {
  if (list.length === 7) return "Dagl";
  const indexes = list.map((day) => DAYS.indexOf(day));
  const run = indexes.every((value, i) => i === 0 || value === (indexes[i - 1] ?? -2) + 1);
  if (run && indexes.length > 2) return `${DAY_NAMES[indexes[0] ?? 0]}–${DAY_NAMES[indexes[indexes.length - 1] ?? 0]}`;
  return indexes.map((i) => DAY_NAMES[i]).join(", ");
}

export const trainName = (train: Train) => [train.train_type, train.number].filter(Boolean).join(" ");

export function callKind(train: Train, call: Call, index: number): string {
  if (index === 0) return "Utgångsstation";
  if (index === train.calls.length - 1) return "Slutstation";
  if (call.stops === false) return "Ej uppehåll";
  if (call.exchange === false) return "Inget utbyte";
  return "Uppehåll";
}

/** The facts by ref, and grouped by the thing they are about (place:p5 and place:p5.phone). */
export class Facts {
  readonly byRef: Map<string, Fact>;
  readonly grouped = new Map<string, Fact[]>();

  constructor(facts: readonly Fact[]) {
    this.byRef = new Map(facts.map((fact) => [fact.ref, fact]));
    for (const fact of facts) {
      const dot = fact.ref.indexOf(".", fact.ref.indexOf(":"));
      const base = dot < 0 ? fact.ref : fact.ref.slice(0, dot);
      const list = this.grouped.get(base) ?? [];
      list.push(fact);
      this.grouped.set(base, list);
    }
  }

  /** The facts for a thing and its fields. */
  of(ref: string): Fact[] {
    return this.grouped.get(ref) ?? [];
  }

  sources(ref: string): Set<string> {
    return new Set(this.of(ref).flatMap((fact) => fact.origins.map((origin) => origin.source)));
  }

  certainties(ref: string): Set<string> {
    return new Set(this.of(ref).map((fact) => fact.certainty));
  }

  /** The row's certainty: its own, or confirmed when one of its fields has been confirmed. */
  certainty(ref: string): string | null {
    const fact = this.byRef.get(ref);
    if (!fact) return null;
    const fields = this.of(ref).filter((item) => item !== fact);
    return fields.some((item) => item.certainty === "confirmed") ? "confirmed" : fact.certainty;
  }
}

/** Where a fact comes from: the plan (JSON), Planering itself, or the rulebook. */
export function sourceKind(origin: Origin, sources: Draft["sources"]): [label: string, kind: string, title: string] {
  if (origin.source === "planner") return ["PLAN", "andrad", "Ändrat i Planering"];
  if (origin.source === "regelboken") return ["REGEL", "regel", "Regelboken"];
  const source = (sources ?? []).find((item) => item.id === origin.source);
  const label = source?.kind === "station_lists" ? "ST" : source?.kind === "track_picture" ? "BILD" : source?.kind === "graph_picture" ? "GRAF" : source?.kind === "station_outside" ? "STN" : "JSON";
  return [label, "", source ? source.filename : "Underlaget"];
}

/** What the import gave, in one line. */
export function reportSummary(report: NonNullable<Draft["report"]>): string {
  const places = report.places ?? {};
  const count = Object.values(places).reduce((sum, value) => sum + value, 0);
  const kinds = Object.entries(places)
    .map(([kind, n]) => `${n} ${KINDS_MANY[kind] ?? kind}`)
    .join(", ");
  return (
    `${plural(count, "driftplats", "driftplatser")} (${kinds}), ` +
    `${plural(report.sections, "klareringssträcka", "klareringssträckor")}, ` +
    `${plural(report.trains, "tåg", "tåg")} med ${plural(report.calls, "besök", "besök")}, ` +
    `${plural(report.duties, "köruppdrag", "köruppdrag")}, ${plural(report.turns, "omlopp", "omlopp")}, ` +
    `${plural(report.shunting ?? 0, "växlingsuppdrag", "växlingsuppdrag")}`
  );
}

/** What a new source changes in the draft, before it is put in (Lägg till underlag). */
export function describePreview(preview: ImportPreview): string {
  const things: [keyof ImportPreview, string, string][] = [
    ["trains", "tåg", "tåg"],
    ["places", "driftplats", "driftplatser"],
    ["sections", "sträcka", "sträckor"],
    ["lines", "linje i grafen", "linjer i grafen"],
  ];
  const diff = (key: keyof ImportPreview) => (preview[key] ?? { added: 0, removed: 0, changed: 0 }) as { added?: number; removed?: number; changed?: number };
  if (preview.first) {
    return (
      "Allt är nytt: " +
      things
        .filter(([key]) => diff(key).added)
        .map(([key, one, many]) => plural(diff(key).added ?? 0, one, many))
        .join(", ") +
      "."
    );
  }
  const parts: string[] = [];
  for (const [key, one, many] of things) {
    const { added = 0, removed = 0, changed = 0 } = diff(key);
    if (added) parts.push(`${plural(added, one, many)} nya`);
    if (removed) parts.push(`${plural(removed, one, many)} borta`);
    if (changed) parts.push(`${plural(changed, one, many)} ändrade`);
  }
  if (preview.times) parts.push(`${plural(preview.times, "tid", "tider")} ändrade`);
  if (preview.tracks) parts.push(`${plural(preview.tracks, "spår", "spår")} ändrade`);
  if (preview.questions) parts.push(plural(preview.questions, "fråga", "frågor"));
  let text = parts.length ? `${parts.join(" · ")}.` : "Inget ändras: filen ger samma utkast.";
  if (preview.kept) text += ` ${plural(preview.kept, "ändring", "ändringar")} från Planering står kvar.`;
  return text;
}
