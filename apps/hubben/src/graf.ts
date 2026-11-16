// Tågdiagrammet without the drawing: the lines of the graph, the traffic days, where each train
// runs on a day, and the typical running times that space the places when the plan gives no km.
// The same rules as the old page (hub/static/graf.js). Shared by Graf in Planering and the
// screens' Tågdiagram (SKARM-18).
import type { Package } from "./andringar";

type Train = NonNullable<Package["trains"]>[number];
type Call = Train["calls"][number];

export const DAY = 1440;
export const WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export const KIND: Record<string, string> = { passengers: "resande", goods: "gods", service: "tjanst" };

export const minutes = (text: string | null | undefined) => (text ? Number(text.slice(0, 2)) * 60 + Number(text.slice(3, 5)) : null);

export const clock = (value: number) => {
  const minute = ((Math.round(value) % DAY) + DAY) % DAY;
  return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
};

const median = (values: number[]) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? (sorted[middle] as number) : ((sorted[middle - 1] as number) + (sorted[middle] as number)) / 2;
};
const pair = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);

/** The minutes a call holds, counted from its train's first day. */
export function times(call: Partial<Call>): { arrival: number | null; departure: number | null } {
  const offset = (call.day_offset ?? 0) * DAY;
  let arrival = minutes(call.arrival);
  let departure = minutes(call.departure);
  if (arrival !== null) arrival += offset;
  if (departure !== null) {
    departure += offset;
    if (arrival !== null && departure < arrival) departure += DAY;
  }
  return { arrival, departure };
}

/** The typical running time between two places next to each other, from the trains. */
export function runTimes(pkg: Package): (a: string, b: string) => number {
  const samples = new Map<string, number[]>();
  for (const train of pkg.trains ?? []) {
    for (let i = 1; i < train.calls.length; i++) {
      const a = train.calls[i - 1] as Call;
      const b = train.calls[i] as Call;
      const start = times(a).departure ?? times(a).arrival;
      const end = times(b).arrival ?? times(b).departure;
      if (start === null || end === null || end <= start || end - start > 240) continue;
      const key = pair(a.place, b.place);
      samples.set(key, [...(samples.get(key) ?? []), end - start]);
    }
  }
  const typical = new Map([...samples].map(([key, values]) => [key, median(values) as number]));
  const fallback = median([...typical.values()]) ?? 5;
  return (a, b) => typical.get(pair(a, b)) ?? fallback;
}

export type Line = { id: string; name: string; places: string[]; distances: number[] | null; color: string | null };

type GraphPage = { id: string; name: string; number?: string | null; places: string[]; distances?: number[] | null; color?: string | null };

/** The graph's lines: the plan's sheets, or else one line along the sections. */
export function lines(pkg: Package): Line[] {
  const pages = ((pkg.display as { graph_pages?: GraphPage[] } | undefined)?.graph_pages ?? []) as GraphPage[];
  if (pages.length) {
    return pages.map((page) => ({ id: page.id, name: page.number ? `${page.number} · ${page.name}` : page.name, places: page.places, distances: page.distances ?? null, color: page.color ?? null }));
  }
  // Without the plan's lines: the longest way through the sections' parts.
  const next = new Map<string, Set<string>>();
  const link = (a: string, b: string) => next.set(a, new Set([...(next.get(a) ?? []), b]));
  for (const section of pkg.sections ?? []) {
    for (const part of section.parts ?? []) {
      link(part.from_place, part.to_place);
      link(part.to_place, part.from_place);
    }
  }
  const longest = (from: string, seen: Set<string>): string[] => {
    seen.add(from);
    let best = [from];
    for (const other of next.get(from) ?? []) {
      if (seen.has(other)) continue;
      const way = [from, ...longest(other, seen)];
      if (way.length > best.length) best = way;
    }
    seen.delete(from);
    return best;
  };
  let way: string[] = [];
  for (const place of next.keys()) {
    if ((next.get(place)?.size ?? 0) > 1) continue;
    const candidate = longest(place, new Set());
    if (candidate.length > way.length) way = candidate;
  }
  if (way.length < 2) way = pkg.places.map((place) => place.id);
  const order = pkg.places.map((place) => place.id);
  if (way.length && order.indexOf(way[0] as string) > order.indexOf(way[way.length - 1] as string)) way.reverse();
  const names = new Map(pkg.places.map((place) => [place.id, place.name]));
  return [{ id: "linjen", name: `${names.get(way[0] as string)}–${names.get(way[way.length - 1] as string)}`, places: way, distances: null, color: null }];
}

/** The weekdays the meet's game week covers, in order. */
export function trafficDays(pkg: Package): string[] {
  const week = (pkg.meet as { traffic_week?: { start_weekday: string; days: number } | null }).traffic_week ?? { start_weekday: "mon", days: 1 };
  const start = WEEK.indexOf(week.start_weekday as (typeof WEEK)[number]);
  const result: string[] = [];
  for (let i = 0; i < Math.min(week.days, 7); i++) result.push(WEEK[(start + i) % 7] as string);
  return result;
}

export type Point = [minute: number, row: number, call: Call];

/** The runs of one train along the line on a day: points of [minute, row]. A train from the day
 * before that runs on past midnight comes in at the left edge. */
export function runs(train: Train, rows: Map<string, number>, day: string): Point[][] {
  const index = WEEK.indexOf(day as (typeof WEEK)[number]);
  const before = WEEK[(index + 6) % 7] as string;
  const days = train.days as string[];
  const shifts: number[] = [];
  if (days.includes(day)) shifts.push(0);
  if (days.includes(before) && train.calls.some((call) => (call.day_offset ?? 0) > 0)) shifts.push(-DAY);
  const result: Point[][] = [];
  for (const shift of shifts) {
    let current: Point[] = [];
    for (const call of train.calls) {
      const row = rows.get(call.place);
      if (row === undefined) {
        if (current.length > 1) result.push(current);
        current = [];
        continue;
      }
      const { arrival, departure } = times(call);
      if (arrival !== null) current.push([arrival + shift, row, call]);
      if (departure !== null && departure !== arrival) current.push([departure + shift, row, call]);
    }
    if (current.length > 1) result.push(current);
  }
  return result.filter((points) => points.some(([minute]) => minute >= 0 && minute <= DAY));
}

/** A finding as a mark in the graph: a ring at a moment, or a band between two places. */
export type Mark = { number: number; severity: string; message: string; place?: string; minute?: number | null; days?: string[]; from?: string; to?: string };

export function marksOf(pkg: Package, findings: { severity: string; message: string; code: string; refs?: string[] }[]): Mark[] {
  const calls = new Map<string, { train: Train; call: Call }>();
  for (const train of pkg.trains ?? []) for (const call of train.calls) calls.set(call.id, { train, call });
  return findings.map((finding, index) => {
    const refs = finding.refs ?? [];
    const mark: Mark = { number: index + 1, severity: finding.severity, message: finding.message };
    if (finding.code === "no_section") {
      mark.from = refs[0];
      mark.to = refs[1];
    } else if (finding.code === "track_conflict") {
      const hit = calls.get(refs[1] ?? "");
      const { arrival, departure } = times(hit?.call ?? {});
      mark.place = refs[0];
      mark.minute = arrival ?? departure;
      mark.days = (hit?.train.days as string[] | undefined) ?? [];
    }
    return mark;
  });
}

export function onLine(mark: Mark, line: Line): boolean {
  if (mark.from !== undefined) return line.places.includes(mark.from) && line.places.includes(mark.to ?? "");
  return mark.place !== undefined && line.places.includes(mark.place);
}
