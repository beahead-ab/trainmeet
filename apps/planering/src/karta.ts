// Banan som karta (H47): the places and the clearance sections with their parts, laid out from
// the meet package. The plan has no coordinates, so the map is laid out here: the longest way
// through the line stands level, and each branch hangs off on a row of its own. Track that is
// only in the graph's lines (without clearance) is drawn dashed. The same rules as the old
// page (hub/static/bana.js), without the drawing.
import type { Package, Part, Section } from "./data";

export const STEP_X = 118;
export const STEP_Y = 118;
const pair = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);

export type Link = { a: string; b: string; section: Section | null; part?: Part };

type GraphPage = { id: string; places: string[] };
const graphPages = (pkg: Package) => ((pkg.display as { graph_pages?: GraphPage[] } | undefined)?.graph_pages ?? []) as GraphPage[];

/** The physical links: every part of a section, and the graph's lines between places that no
 * section joins (track without clearance in the plan). */
export function links(pkg: Package): Link[] {
  const found = new Map<string, Link>();
  for (const section of pkg.sections ?? []) {
    for (const part of section.parts ?? []) {
      found.set(pair(part.from_place, part.to_place), { a: part.from_place, b: part.to_place, section, part });
    }
  }
  for (const page of graphPages(pkg)) {
    for (let i = 1; i < page.places.length; i++) {
      const a = page.places[i - 1] as string;
      const b = page.places[i] as string;
      if (!found.has(pair(a, b))) found.set(pair(a, b), { a, b, section: null });
    }
  }
  return [...found.values()];
}

export type Layout = { at: Map<string, [number, number]>; left: number; top: number; width: number; height: number };

/** Where every place stands: [column, row]. */
export function layout(pkg: Package): Layout {
  const next = new Map<string, string[]>(pkg.places.map((place) => [place.id, []]));
  for (const link of links(pkg)) {
    next.get(link.a)?.push(link.b);
    next.get(link.b)?.push(link.a);
  }
  const order = pkg.places.map((place) => place.id);
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
  let main: string[] = [];
  for (const place of order) {
    if ((next.get(place)?.length ?? 0) !== 1) continue;
    const way = longest(place, new Set());
    if (way.length > main.length) main = way;
  }
  if (!main.length && order.length) main = [order[0] as string];
  if (main.length && order.indexOf(main[0] as string) > order.indexOf(main[main.length - 1] as string)) main.reverse();

  const at = new Map<string, [number, number]>();
  const taken = new Set<string>();
  const claim = (place: string, column: number, row: number) => {
    at.set(place, [column, row]);
    taken.add(`${column},${row}`);
  };
  main.forEach((place, i) => claim(place, i, 0));
  const queue = [...main];
  const rows = [1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6];
  while (queue.length) {
    const from = queue.shift() as string;
    const [column, row] = at.get(from) as [number, number];
    for (const first of next.get(from) ?? []) {
      if (at.has(first)) continue;
      // The branch: on from the first place as long as the way does not split.
      const chain = [first];
      let previous = from;
      for (;;) {
        const last = chain[chain.length - 1] as string;
        const onward = (next.get(last) ?? []).filter((other) => other !== previous && !at.has(other) && !chain.includes(other));
        if (onward.length !== 1 || (next.get(last)?.length ?? 0) > 2) break;
        previous = last;
        chain.push(onward[0] as string);
      }
      const right = column < (main.length - 1) / 2 || column === 0 ? 1 : -1;
      const free = (step: number, branchRow: number) => chain.every((_, k) => !taken.has(`${column + step * (k + 1)},${branchRow}`));
      let chosen: [number, number] | null = null;
      for (const offset of rows) {
        const candidate = row + (row < 0 ? -Math.abs(offset) : offset);
        for (const step of [right, -right]) {
          if (free(step, candidate)) {
            chosen = [step, candidate];
            break;
          }
        }
        if (chosen) break;
      }
      const [step, branchRow] = chosen ?? [right, row + 7];
      chain.forEach((place, k) => claim(place, column + step * (k + 1), branchRow));
      queue.push(...chain);
    }
  }
  // A part of a station that no link reaches stands right by its station (PLAN-34): under it,
  // else above, else beside.
  for (const place of pkg.places) {
    const home = place.part_of ? at.get(place.part_of) : undefined;
    if (at.has(place.id) || !home) continue;
    const [column, row] = home;
    const spots: [number, number][] = [1, -1, 2, -2].flatMap((step): [number, number][] => [[column, row + step], [column + step, row + Math.sign(step)], [column - step, row + Math.sign(step)]]);
    const spot = spots.find(([c, r]) => !taken.has(`${c},${r}`));
    if (spot) claim(place.id, spot[0], spot[1]);
  }
  // Places no link reaches stand in a row of their own under the rest.
  const bottom = Math.max(0, ...[...at.values()].map(([, r]) => r)) + 1;
  let spare = 0;
  for (const place of order) if (!at.has(place)) claim(place, spare++, bottom);
  const columns = [...at.values()].map(([c]) => c);
  const used = [...at.values()].map(([, r]) => r);
  const left = columns.length ? Math.min(...columns) : 0;
  const top = used.length ? Math.min(...used) : 0;
  return { at, left, top, width: (columns.length ? Math.max(...columns) : 0) - left + 1, height: (used.length ? Math.max(...used) : 0) - top + 1 };
}

/** A section's short name: the plan's number for its clearance section. */
/** The plan's number for the section; a section derived from the station lists has none. */
export const sectionLabel = (section: Section) => (section.source_ids as Record<string, string> | undefined)?.["planning_json"] ?? "";
