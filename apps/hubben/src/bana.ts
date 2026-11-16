// Banöversikten (SKARM-21, H47): the line drawn from the places and sections of the meet package,
// with a train number field per track and per part of a section. Without detection the number
// follows the buttons: the start track, the section at departure, the destination track at
// arrival. Shared by the screens, Nu, Översikt and Deltagarna; without React, so it can be
// tested on its own.
import type { components } from "../../../contracts/types";
import type { Now } from "./api";
import type { Package } from "./andringar";

type Schemas = components["schemas"];
type Place = Package["places"][number];
type Section = NonNullable<Package["sections"]>[number];
export type Leg = Now["legs"][number];

/** The box of a place that clears, and how much room its tracks take. */
export const BOX_W = 176;
export const HEAD_H = 44;
export const ROW_H = 27;
export const GAP_X = 120;
export const GAP_Y = 76;

const pair = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);
const halt = (place: Place | undefined) => place?.kind === "halt";

export type Link = { a: string; b: string; section: Section | null };

/** The links between places that clear: each section, and the way a train runs where no section
 * joins two places (track without clearance). */
export function linksOf(pkg: Package): Link[] {
  const places = new Map(pkg.places.map((place) => [place.id, place]));
  const found = new Map<string, Link>();
  for (const section of pkg.sections ?? []) found.set(pair(section.place_a, section.place_b), { a: section.place_a, b: section.place_b, section });
  for (const train of pkg.trains ?? []) {
    const stops = train.calls.filter((call) => places.has(call.place) && !halt(places.get(call.place))).map((call) => call.place);
    for (let i = 1; i < stops.length; i++) {
      const a = stops[i - 1] as string;
      const b = stops[i] as string;
      if (a !== b && !found.has(pair(a, b))) found.set(pair(a, b), { a, b, section: null });
    }
  }
  return [...found.values()];
}

export type Box = { place: Place; x: number; y: number; w: number; h: number; tracks: string[]; band: number };
/** gaps: where the way back runs between one band and the next, by band. */
export type Drawing = { boxes: Map<string, Box>; links: Link[]; width: number; height: number; gaps: number[] };

const trackNames = (place: Place) => (place.kind === "shadow_yard" ? [] : (place.tracks ?? []).map((track) => track.name));
const boxHeight = (place: Place) => HEAD_H + Math.max(trackNames(place).length, place.kind === "shadow_yard" ? 1 : 0) * ROW_H + 10;

/** Where every place that clears stands. The organiser's map when it has all of them
 * (SKARM-17); otherwise the longest way stands level and each branch hangs off on a row of its
 * own, as Bana in Planering draws it. A long line can be broken into bands, like the lines of a
 * text, so that it is drawn larger on a wide screen. */
export function drawing(pkg: Package, bands = 1): Drawing {
  const places = pkg.places.filter((place) => !halt(place));
  const ids = new Set(places.map((place) => place.id));
  const links = linksOf(pkg).filter((link) => ids.has(link.a) && ids.has(link.b));
  const reference = ((pkg.display as { reference_layout?: Record<string, { x: number; y: number }> } | undefined)?.reference_layout ?? {}) as Record<string, { x: number; y: number }>;
  const used = places.filter((place) => links.some((link) => link.a === place.id || link.b === place.id));
  const boxes = new Map<string, Box>();
  const gaps: number[] = [];
  if (used.length > 1 && used.every((place) => reference[place.id])) {
    const xs = used.map((place) => reference[place.id]?.x ?? 0);
    const ys = used.map((place) => reference[place.id]?.y ?? 0);
    const span = Math.max(1, Math.max(...xs) - Math.min(...xs));
    const scale = Math.max(1, ((BOX_W + GAP_X) * Math.max(2, used.length / 2)) / span);
    for (const place of used) {
      const point = reference[place.id] as { x: number; y: number };
      boxes.set(place.id, { place, x: (point.x - Math.min(...xs)) * scale, y: (point.y - Math.min(...ys)) * scale, w: BOX_W, h: boxHeight(place), tracks: trackNames(place), band: 0 });
    }
  } else {
    const grid = gridOf(used.map((place) => place.id), links);
    const left = Math.min(...[...grid.values()].map(([column]) => column));
    const columns = Math.max(...[...grid.values()].map(([column]) => column)) - left + 1;
    const per = Math.ceil(columns / Math.max(1, Math.min(bands, columns)));
    const bandOf = (column: number) => Math.floor((column - left) / per);
    // The rows of each band, top to bottom, each as high as its highest box.
    const rows = new Map<string, number>();
    for (const place of used) {
      const [column, row] = grid.get(place.id) as [number, number];
      const key = `${bandOf(column)},${row}`;
      rows.set(key, Math.max(rows.get(key) ?? 0, boxHeight(place)));
    }
    const order = [...rows.keys()].map((key) => key.split(",").map(Number) as [number, number]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const top = new Map<string, number>();
    let y = 0;
    let band = 0;
    for (const [b, row] of order) {
      if (b !== band) {
        gaps[band] = y - GAP_Y / 2;
        y += GAP_Y;
        band = b;
      }
      top.set(`${b},${row}`, y);
      y += (rows.get(`${b},${row}`) ?? 0) + GAP_Y;
    }
    for (const place of used) {
      const [column, row] = grid.get(place.id) as [number, number];
      const b = bandOf(column);
      boxes.set(place.id, { place, x: ((column - left) % per) * (BOX_W + GAP_X), y: top.get(`${b},${row}`) ?? 0, w: BOX_W, h: boxHeight(place), tracks: trackNames(place), band: b });
    }
  }
  const all = [...boxes.values()];
  return {
    boxes,
    links: links.filter((link) => boxes.has(link.a) && boxes.has(link.b)),
    width: Math.max(0, ...all.map((box) => box.x + box.w)),
    height: Math.max(0, ...all.map((box) => box.y + box.h)),
    gaps,
  };
}

/** How many bands draw the line largest in a space this many times wider than high. */
export function bestBands(pkg: Package, aspect: number, extra = 0): number {
  let best = 1;
  let scale = 0;
  for (let bands = 1; bands <= 3; bands++) {
    const drawn = drawing(pkg, bands);
    const fits = Math.min(aspect / Math.max(1, drawn.width), 1 / Math.max(1, drawn.height + extra));
    if (fits > scale * 1.05) {
      scale = fits;
      best = bands;
    }
  }
  return best;
}

/** [column, row] for each place: the longest way on row 0, each branch on a free row. */
export function gridOf(order: string[], links: Link[]): Map<string, [number, number]> {
  const next = new Map<string, string[]>(order.map((id) => [id, []]));
  for (const link of links) {
    next.get(link.a)?.push(link.b);
    next.get(link.b)?.push(link.a);
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
  let main: string[] = [];
  for (const id of order) {
    if ((next.get(id)?.length ?? 0) > 1) continue;
    const way = longest(id, new Set());
    if (way.length > main.length) main = way;
  }
  if (!main.length && order.length) main = [order[0] as string];
  if (main.length && order.indexOf(main[0] as string) > order.indexOf(main[main.length - 1] as string)) main.reverse();
  const at = new Map<string, [number, number]>();
  const taken = new Set<string>();
  const claim = (id: string, column: number, row: number) => {
    at.set(id, [column, row]);
    taken.add(`${column},${row}`);
  };
  main.forEach((id, i) => claim(id, i, 0));
  const queue = [...main];
  while (queue.length) {
    const from = queue.shift() as string;
    const [column, row] = at.get(from) as [number, number];
    for (const first of next.get(from) ?? []) {
      if (at.has(first)) continue;
      const chain = [first];
      let previous = from;
      for (;;) {
        const last = chain[chain.length - 1] as string;
        const onward = (next.get(last) ?? []).filter((other) => other !== previous && !at.has(other) && !chain.includes(other));
        if (onward.length !== 1 || (next.get(last)?.length ?? 0) > 2) break;
        previous = last;
        chain.push(onward[0] as string);
      }
      // A branch goes down from where it leaves, then on sideways on its own row.
      let branchRow = row + 1;
      const free = (r: number) => chain.every((_, k) => !taken.has(`${column + k},${r}`));
      while (!free(branchRow)) branchRow++;
      chain.forEach((id, k) => claim(id, column + k, branchRow));
      queue.push(...chain);
    }
  }
  const bottom = Math.max(0, ...[...at.values()].map(([, r]) => r)) + 1;
  let spare = 0;
  for (const id of order) if (!at.has(id)) claim(id, spare++, bottom);
  return at;
}

// --- Where the trains are ------------------------------------------------------------------------

export type TrackState = "here" | "requested" | "cleared" | "coming" | "ends";
export type OnTrack = { train: string; number: string; state: TrackState; toward: string | null; at: string | null };
export type OnSection = { train: string; number: string; state: "requested" | "cleared" | "occupied"; from: string; to: string; leg: Leg; progress: number };

export type Traffic = {
  tracks: Map<string, Map<string, OnTrack[]>>;
  yards: Map<string, number>;
  sections: Map<string, OnSection[]>;
  online: Leg[];
  cleared: Leg[];
  requested: Leg[];
  ends: Leg[];
};

export const minutesOf = (text: string | null | undefined) => (text ? Number(text.slice(0, 2)) * 60 + Number(text.slice(3, 5)) : null);
/** Minutes from a to b on the clock, the short way round midnight. */
export const between = (a: number, b: number) => ((b - a + 2160) % 1440) - 720;

/** A train shows at its start track this long before it leaves, and where it ends this long. */
export const SHOWN_BEFORE = 15;
export const SHOWN_AFTER = 10;

/** Where each train stands now: on a track, on a section, or nowhere on the line. */
export function trafficOf(pkg: Package, now: Now): Traffic {
  const calls = new Map((pkg.trains ?? []).flatMap((train) => train.calls.map((call) => [call.id, call] as const)));
  const places = new Map(pkg.places.map((place) => [place.id, place]));
  const clock = minutesOf(now.clock.time) ?? 0;
  const traffic: Traffic = { tracks: new Map(), yards: new Map(), sections: new Map(), online: [], cleared: [], requested: [], ends: [] };
  const put = (place: string, track: string | null | undefined, entry: OnTrack) => {
    if (places.get(place)?.kind === "shadow_yard") {
      traffic.yards.set(place, (traffic.yards.get(place) ?? 0) + 1);
      return;
    }
    const known = trackNames(places.get(place) as Place);
    const name = track && known.includes(track) ? track : (known[0] ?? "");
    const at = traffic.tracks.get(place) ?? new Map<string, OnTrack[]>();
    at.set(name, [...(at.get(name) ?? []), entry]);
    traffic.tracks.set(place, at);
  };
  const onSection = (leg: Leg, state: OnSection["state"]) => {
    const start = minutesOf(leg.departure);
    const end = minutesOf(leg.arrival);
    const progress = start === null || end === null || end === start ? 0.5 : Math.min(1, Math.max(0, between(start, clock) / between(start, end)));
    const list = traffic.sections.get(leg.section) ?? [];
    list.push({ train: leg.train, number: leg.train_number, state, from: leg.from_place, to: leg.to_place, leg, progress });
    traffic.sections.set(leg.section, list);
  };
  const byTrain = new Map<string, Leg[]>();
  for (const leg of now.legs) byTrain.set(leg.train, [...(byTrain.get(leg.train) ?? []), leg]);
  for (const legs of byTrain.values()) {
    const moving = legs.find((leg) => leg.state === "on_the_way");
    const asked = legs.find((leg) => leg.state === "requested" || leg.state === "cleared");
    const start = (leg: Leg) => calls.get(leg.leg)?.track ?? null;
    if (moving) {
      traffic.online.push(moving);
      onSection(moving, "occupied");
      put(moving.to_place, moving.track, { train: moving.train, number: moving.train_number, state: "coming", toward: moving.to_place, at: moving.arrival ?? null });
      continue;
    }
    if (asked) {
      const state = asked.state === "cleared" ? "cleared" : "requested";
      (state === "cleared" ? traffic.cleared : traffic.requested).push(asked);
      onSection(asked, state);
      put(asked.from_place, start(asked), { train: asked.train, number: asked.train_number, state, toward: asked.to_place, at: asked.departure ?? null });
      continue;
    }
    const done = legs.filter((leg) => leg.state === "arrived");
    const last = done[done.length - 1];
    const ahead = legs.find((leg) => leg.state === "planned");
    if (last && ahead) {
      put(last.to_place, last.track, { train: last.train, number: last.train_number, state: "here", toward: ahead.to_place, at: ahead.departure ?? null });
    } else if (last) {
      const arrived = minutesOf(last.arrival);
      if (arrived !== null && between(arrived, clock) >= 0 && between(arrived, clock) <= SHOWN_AFTER) {
        traffic.ends.push(last);
        put(last.to_place, last.track, { train: last.train, number: last.train_number, state: "ends", toward: null, at: last.arrival ?? null });
      }
    } else if (ahead) {
      const leaves = minutesOf(ahead.departure);
      if (leaves !== null && between(clock, leaves) >= 0 && between(clock, leaves) <= SHOWN_BEFORE) {
        put(ahead.from_place, start(ahead), { train: ahead.train, number: ahead.train_number, state: "here", toward: ahead.to_place, at: ahead.departure ?? null });
      }
    }
  }
  return traffic;
}

// --- Words ---------------------------------------------------------------------------------------

export const KIND_TEXT: Record<string, string> = {
  manned: "bemannad",
  remote: "fjärrstyrd",
  unmanned: "obemannad · automatiken",
  shadow_yard: "skuggbangård",
  halt: "hållplats",
};

/** A section's short name: the plan's number for it, as the stations know it. */
export const sectionLabel = (section: Section) => (section.source_ids as Record<string, string> | undefined)?.["planning_json"] ?? section.id;

/** What the section is: begärd or direkt, and dubbel when it is double track. */
export function sectionNote(section: Section, pkg: Package): string {
  const mode = section.clearance_mode ?? (pkg.meet as Schemas["trainmeet.meet-1"]["meet"]).clearance_mode;
  return [mode === "direct" ? "direkt" : "begärd", section.tracks === "double" ? "dubbel" : null].filter(Boolean).join(" · ");
}

export const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

/** The line under the meet's name: what is on the line now. */
export function summary(traffic: Traffic): string {
  return [
    plural(traffic.online.length, "tåg på linjen", "tåg på linjen"),
    `${traffic.cleared.length} klart, inte avgått`,
    `${traffic.requested.length} väntar på svar`,
    `${traffic.ends.length} slutar här`,
  ].join(" · ");
}
