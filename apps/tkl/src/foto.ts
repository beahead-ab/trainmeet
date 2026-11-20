// Foto, the fun skin (STV-06, STV-12): the station seen from above in its real shape, with
// rails, sleepers, ballast and a landscape, all drawn as vectors (no photographs). What this
// module works out, without React: the station's geometry from the drawing (TrackPiece.geometry,
// `real` in the panel), the states from the same logical drawing as every skin (stallverk.ts),
// and the trains, each on the real geometry of the section it stands on.
//
// The measures are the skins document's (trainmeet-spec docs/trainmeet-tkl-skalen.md, "Foto"),
// in its units: the gauge is 8.6 units, the rails 1.7, the concrete sleepers 15 long, the
// ballast 22 wide, the glow 24 and the band between the rails 6.5. A unit is scaled to the
// station's real geometry by its gauge: the model has no gauge, so it is read from the drawing,
// where parallel tracks lie about 3.4 gauges apart (H0: 16.5 mm gauge, 56 mm apart; 0: 32 and
// 113). A station without the real geometry has no Foto: it is greyed with the reason (STV-18).
//
// Mätbilden under (#89 del d4, CAD8, CAD-33): a station from CAD may show its modules' measuring
// images, the photos straightened to 1 px per mm, under the tracks, each moved by its matrix from
// its pixels to the station's mm (the same mm as the real geometry, from the same track graph in
// CAD) and clipped to its module's board. On a board with a photo Foto leaves out its own grass,
// trees, platforms, ballast and sleepers, which the photo has; the rails, the states and the
// trains stay vectors on top. The choice is the station's, off by default.
//
// Trains: short and rounded for a passenger train, longer and square for a goods train, which
// is a train numbered 4000 to 9999; a shunt without a number is only the locomotive (trainmeet-
// spec docs/tkl-tag-och-tagnummer.md). The number stands on the roof. Kör rolls the train along
// the route's pieces from the section it was on to the next (STV-06).
import type { ImageUnder, Panel } from "./api";
import { lengthOf, slice, type Cell, type Drawing, type DrawnSignal, type DrawnSwitch, type DrawnTable, type Filled, type TrackState } from "./stallverk";

export type Pt = [number, number];

/** The skins document's measures for Foto, in its units. */
export const FOTO = {
  gauge: 8.6,
  rail: 1.7,
  railTop: 0.6,
  sleeper: 15,
  sleeperDash: [2.4, 3.6] as const,
  ballast: 22,
  bank: 27,
  glow: 24,
  band: 6.5,
  /** Passenger coaches, the goods train's locomotive and wagons, and the gap between. */
  coach: 44,
  coachWidth: 13,
  loco: 32,
  wagon: 30,
  wagons: 5,
  goodsWidth: 13.5,
  gap: 3,
} as const;

/** How far apart parallel tracks lie, in gauges: NEM-like spacing in H0 and 0. */
const SPACING = 3.4;
/** The pixels per unit in Närbild: the skins document's 0.79 px at 1440 px. */
export const PX_PER_UNIT = 0.8;
/** The animation of a train rolling, in milliseconds. */
export const ROLL_MS = 1000;

export const NO_REAL_FORM = "Foto kräver stationens verkliga form (från CAD)";

const dist = (a: Pt, b: Pt) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const unit = (v: Pt): Pt => {
  const n = Math.hypot(v[0], v[1]) || 1;
  return [v[0] / n, v[1] / n];
};

/** Does the station have its real shape: the drawing's frame and track pieces in it? */
export function hasRealForm(panel: Panel): boolean {
  return !!panel.real_box && panel.lines.some((l) => (l.real ?? []).length > 1);
}

const gauges = new WeakMap<Panel, number>();

/** The station's gauge in the drawing's units, read from how far apart its parallel tracks lie:
 * the lower quartile of the distances from a track to the nearest parallel one. */
export function gaugeOf(panel: Panel): number {
  const known = gauges.get(panel);
  if (known !== undefined) return known;
  const [, , width, height] = panel.real_box ?? [0, 0, 1, 1];
  const size = Math.max(width, height, 1);
  type Seg = { line: number; a: Pt; d: Pt; length: number };
  const segs: Seg[] = [];
  panel.lines.forEach((l, line) => {
    const real = l.real ?? [];
    for (let i = 1; i < real.length; i++) {
      const a = real[i - 1] as Pt;
      const b = real[i] as Pt;
      const length = dist(a, b);
      if (length > 0) segs.push({ line, a, d: [(b[0] - a[0]) / length, (b[1] - a[1]) / length], length });
    }
  });
  const every = Math.max(1, Math.floor(segs.length / 600));
  const found: number[] = [];
  for (let i = 0; i < segs.length; i += every) {
    const s = segs[i] as Seg;
    const m: Pt = [s.a[0] + (s.d[0] * s.length) / 2, s.a[1] + (s.d[1] * s.length) / 2];
    let best = Infinity;
    for (const o of segs) {
      if (o.line === s.line || Math.abs(s.d[0] * o.d[1] - s.d[1] * o.d[0]) > 0.035) continue;
      const along = (m[0] - o.a[0]) * o.d[0] + (m[1] - o.a[1]) * o.d[1];
      if (along < 0 || along > o.length) continue;
      const across = Math.abs(-(m[0] - o.a[0]) * o.d[1] + (m[1] - o.a[1]) * o.d[0]);
      if (across > size * 1e-4 && across < best) best = across;
    }
    if (Number.isFinite(best)) found.push(best);
  }
  found.sort((a, b) => a - b);
  const spacing = found.length >= 5 ? (found[Math.floor(found.length / 4)] as number) : size / 150;
  const gauge = Math.min(size / 60, Math.max(size / 4000, spacing / SPACING));
  gauges.set(panel, gauge);
  return gauge;
}

// --- paths ------------------------------------------------------------------------------------

/** The point and the heading at a distance along a path; beyond its ends it goes straight on. */
export function along(path: Pt[], s: number): { at: Pt; heading: Pt } {
  let walked = 0;
  let last: [Pt, Pt, number, number] | null = null;
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1] as Pt;
    const b = path[i] as Pt;
    const step = dist(a, b);
    if (step === 0) continue;
    last = [a, b, step, walked];
    if (s <= walked + step) break;
    walked += step;
  }
  if (!last) return { at: (path[0] ?? [0, 0]) as Pt, heading: [1, 0] };
  const [a, b, step, before] = last;
  const t = (s - before) / step;
  return { at: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], heading: [(b[0] - a[0]) / step, (b[1] - a[1]) / step] };
}

/** A path moved sideways: to the right of its direction for a positive distance. */
export function offset(path: Pt[], by: number): Pt[] {
  return path.map((p, i) => {
    const a = path[Math.max(0, i - 1)] as Pt;
    const b = path[Math.min(path.length - 1, i + 1)] as Pt;
    const [tx, ty] = unit([b[0] - a[0], b[1] - a[1]]);
    return [p[0] - ty * by, p[1] + tx * by];
  });
}

/** Pieces' real polylines joined into one path, each turned so that it goes on from the last. */
export function chain(parts: Pt[][]): Pt[] {
  const found = parts.filter((p) => p.length > 1);
  if (!found.length) return [];
  let path: Pt[] = [...(found[0] as Pt[])];
  for (const next of found.slice(1)) {
    const end = path[path.length - 1] as Pt;
    const start = path[0] as Pt;
    const first = next[0] as Pt;
    const last = next[next.length - 1] as Pt;
    const best = Math.min(dist(end, first), dist(end, last), dist(start, first), dist(start, last));
    if (best === dist(end, first)) path = [...path, ...next.slice(1)];
    else if (best === dist(end, last)) path = [...path, ...[...next].reverse().slice(1)];
    else if (best === dist(start, last)) path = [...next, ...path.slice(1)];
    else path = [...[...next].reverse(), ...path.slice(1)];
  }
  return path;
}

/** The longest way through a section's pieces: from its longest piece, on at each end with the
 * longest piece that goes on from there. A track circuit at a switch has a branch the train
 * does not stand on; this leaves it out. */
export function through(parts: Pt[][], tolerance: number): Pt[] {
  const left = parts.filter((p) => p.length > 1);
  if (!left.length) return [];
  const longest = left.reduce((best, p) => (lengthOf(p) > lengthOf(best) ? p : best));
  left.splice(left.indexOf(longest), 1);
  let path: Pt[] = [...longest];
  for (let grown = true; grown; ) {
    grown = false;
    for (const atEnd of [true, false]) {
      const here = (atEnd ? path[path.length - 1] : path[0]) as Pt;
      const next = left.filter((p) => dist(p[0] as Pt, here) <= tolerance || dist(p[p.length - 1] as Pt, here) <= tolerance).sort((a, b) => lengthOf(b) - lengthOf(a))[0];
      if (!next) continue;
      left.splice(left.indexOf(next), 1);
      const way = dist(next[0] as Pt, here) <= tolerance ? next : [...next].reverse();
      path = atEnd ? [...path, ...way.slice(1)] : [...[...way].reverse(), ...path.slice(1)];
      grown = true;
    }
  }
  return path;
}

/** A path turned so that its end is the one nearer `towards`. */
function facing(path: Pt[], towards: Pt | null): Pt[] {
  if (!towards || path.length < 2) return path;
  return dist(path[0] as Pt, towards) < dist(path[path.length - 1] as Pt, towards) ? [...path].reverse() : path;
}

// --- the trains ---------------------------------------------------------------------------------

export type TrainKind = "passenger" | "goods" | "shunt";

/** Passenger or goods by the number, as the train numbers document says: goods trains are
 * numbered 4000 to 9999. Without a number it is a shunt, only the locomotive. */
export function trainKind(number: string | null): TrainKind {
  if (!number) return "shunt";
  const n = /^\d+$/.test(number) ? Number(number) : NaN;
  return n >= 4000 && n <= 9999 ? "goods" : "passenger";
}

/** The vehicles of a train, front first: their lengths in units. */
export function vehicles(kind: TrainKind): number[] {
  if (kind === "passenger") return [FOTO.coach, FOTO.coach, FOTO.coach];
  if (kind === "goods") return [FOTO.loco, ...Array.from({ length: FOTO.wagons }, () => FOTO.wagon)];
  return [FOTO.loco];
}

export function trainLength(kind: TrainKind): number {
  const cars = vehicles(kind);
  return cars.reduce((a, b) => a + b, 0) + FOTO.gap * (cars.length - 1);
}

/** A train where it stands: on the real geometry of its section, its centre `at` along `path`,
 * which runs in the train's direction. `key` says where it stands, so a move shows. */
export type FotoTrain = { train: number; number: string | null; kind: TrainKind; key: string; path: Pt[]; at: number };

/** A vehicle placed: its centre, its heading and its length, all in the drawing's units. */
export type Placed = { at: Pt; heading: Pt; length: number; index: number };

/** The vehicles of a train with its centre at `at` along `path`, in the drawing's units. */
export function placeTrain(kind: TrainKind, path: Pt[], at: number, u: number): Placed[] {
  const cars = vehicles(kind);
  let front = at + (trainLength(kind) * u) / 2;
  return cars.map((length, index) => {
    const centre = front - (length * u) / 2;
    front -= (length + FOTO.gap) * u;
    const { at: point, heading } = along(path, centre);
    return { at: point, heading, length, index };
  });
}

/** The trains in the interlocking, each on its section's real geometry, turned the way its
 * route goes; a train on the line, towards the station. A train on its route stands on the
 * route's pieces in the section, so Kör rolls it along them; else on the way through the section. */
export function trainsOf(panel: Panel, state: Filled): FotoTrain[] {
  const real = new Map(panel.lines.map((l) => [l.piece, (l.real ?? []) as Pt[]]));
  const [bx, by, bw, bh] = panel.real_box ?? [0, 0, 0, 0];
  const centre: Pt = [bx + bw / 2, by + bh / 2];
  const tolerance = 1e-3 * Math.max(bw, bh, 1);
  const found: FotoTrain[] = [];
  for (const n of state.numbers) {
    if (n.colour !== "red") continue;
    const pieces = (n.pieces ?? []).filter((p) => (real.get(p) ?? []).length > 1);
    if (!pieces.length) continue;
    const route = state.routes.find((r) => r.train === n.train && r.sections.some((s) => s.section === n.section)) ?? state.routes.find((r) => r.train === n.train) ?? null;
    const part = route && n.section ? route.sections.find((s) => s.section === n.section) : undefined;
    const own = (part?.pieces ?? []).filter((p) => (real.get(p) ?? []).length > 1);
    let path = own.length ? chain(own.map((p) => real.get(p) as Pt[])) : through(pieces.map((p) => real.get(p) as Pt[]), tolerance);
    let towards: Pt | null = n.exit ? centre : null;
    if (route) {
      const way = chain(route.sections.flatMap((s) => s.pieces).map((p) => real.get(p) ?? []));
      if (way.length > 1) towards = way[way.length - 1] as Pt;
    }
    path = facing(path, towards);
    if (path.length < 2) continue;
    const key = n.section ? `s:${n.section}` : `e:${n.exit ?? ""}:${pieces.join(",")}`;
    found.push({ train: n.train, number: n.number ?? null, kind: trainKind(n.number ?? null), key, path, at: lengthOf(path) / 2 });
  }
  return found;
}

/** The roll from where a train stood to where it stands: the two paths joined where they meet,
 * and the distances along the joined path from the old centre to the new. None when the two do
 * not meet, and the train is then only drawn where it is. */
export type Roll = { path: Pt[]; from: number; to: number };

export function rollOf(before: FotoTrain, after: FotoTrain, u: number): Roll | null {
  const a = before.path;
  const b = after.path;
  if (a.length < 2 || b.length < 2) return null;
  const options: [Pt[], Pt[], boolean, boolean][] = [
    [a, b, false, false],
    [a, [...b].reverse(), false, true],
    [[...a].reverse(), b, true, false],
    [[...a].reverse(), [...b].reverse(), true, true],
  ];
  let best = options[0] as (typeof options)[number];
  let gap = Infinity;
  for (const o of options) {
    const g = dist(o[0][o[0].length - 1] as Pt, o[1][0] as Pt);
    if (g < gap) {
      gap = g;
      best = o;
    }
  }
  if (gap > 40 * u) return null;
  const [first, second, turnedA, turnedB] = best;
  const lengthA = lengthOf(first);
  const path = [...first, ...second];
  const from = turnedA ? lengthA - before.at : before.at;
  const to = lengthA + gap + (turnedB ? lengthOf(second) - after.at : after.at);
  return { path, from, to };
}

/** Smooth start and stop. */
export const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

// --- the scene ----------------------------------------------------------------------------------

export type FotoTrack = { piece: string; path: Pt[]; state: TrackState; route: number | null; line: boolean };
export type FotoSignal = DrawnSignal & { track: Pt; heading: Pt };
export type FotoSwitch = DrawnSwitch & { at: Pt; label: Pt };
export type FotoBuffer = { id: string; at: Pt; heading: Pt };
export type FotoPoint = { name: string; at: Pt };
export type FotoName = { name: string; at: Pt; hidden: boolean };
export type FotoLabel = { text: string; kind: "exit" | "point"; at: Pt };
export type FotoTable = DrawnTable & { at: Pt; r: number; heading: Pt };
export type FotoButton = { name: string; type: string; at: Pt; on: boolean };
export type Tree = { at: Pt; r: number; bush: boolean };
export type FotoScene = {
  /** The view: the drawing's frame with a margin, in its units (mm). */
  box: [number, number, number, number];
  /** The drawing's units per unit of the skins document: the gauge over 8.6. */
  u: number;
  tracks: FotoTrack[];
  signals: FotoSignal[];
  switches: FotoSwitch[];
  buffers: FotoBuffer[];
  points: FotoPoint[];
  names: FotoName[];
  labels: FotoLabel[];
  tables: FotoTable[];
  buttons: FotoButton[];
  platforms: Pt[][];
  building: Pt[] | null;
  trees: Tree[];
  trains: FotoTrain[];
};

/** A band along a path, between two distances to its right (negative: to its left). */
export function band(path: Pt[], near: number, far: number): Pt[] {
  return [...offset(path, near), ...offset(path, far).reverse()];
}

/** Where a node is in the drawing, and the way into it along the track that ends there. */
function nodeWay(panel: Panel, id: string): { at: Pt; heading: Pt } | null {
  const node = panel.nodes.find((n) => n.id === id);
  if (!node?.real) return null;
  const at = node.real as Pt;
  for (const l of panel.lines) {
    const real = (l.real ?? []) as Pt[];
    if (real.length < 2) continue;
    const way = dist(real[0] as Pt, at) < dist(real[real.length - 1] as Pt, at) ? [...real].reverse() : real;
    if (dist(way[way.length - 1] as Pt, at) > 1e-3 * Math.max(1, ...(panel.real_box ?? [1]).slice(2))) continue;
    const a = way[way.length - 2] as Pt;
    return { at, heading: unit([at[0] - a[0], at[1] - a[1]]) };
  }
  return { at, heading: [1, 0] };
}

/** A part of the station on the grid, such as a platform, put beside the track nearest it in the
 * real shape: the stretch of that track between the part's ends, and the side it is on. */
function beside(panel: Panel, rect: readonly [number, number, number, number]): { path: Pt[]; side: number; other: Pt[] | null } | null {
  const [x1, y1, x2, y2] = rect;
  const [cx, cy] = [(x1 + x2) / 2, (y1 + y2) / 2];
  type Hit = { line: Panel["lines"][number]; y: number; at: number };
  const hits: Hit[] = [];
  for (const line of panel.lines) {
    if ((line.real ?? []).length < 2) continue;
    let walked = 0;
    for (let i = 1; i < line.cells.length; i++) {
      const a = line.cells[i - 1] as Cell;
      const b = line.cells[i] as Cell;
      const step = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const lo = Math.min(a[0], b[0]);
      const hi = Math.max(a[0], b[0]);
      if (hi - lo > Math.abs(b[1] - a[1]) && lo <= cx && cx <= hi) {
        const t = (cx - a[0]) / (b[0] - a[0]);
        hits.push({ line, y: a[1] + (b[1] - a[1]) * t, at: walked + step * t });
      }
      walked += step;
    }
  }
  const nearest = hits.reduce<Hit | null>((best, h) => (best === null || Math.abs(h.y - cy) < Math.abs(best.y - cy) ? h : best), null);
  if (!nearest) return null;
  const down = cy > nearest.y ? 1 : -1;
  const opposite = hits.filter((h) => (h.y - cy) * down > 0 && Math.abs(h.y - cy) < 1.5).sort((p, q) => Math.abs(p.y - cy) - Math.abs(q.y - cy))[0];
  const cells = nearest.line.cells as Cell[];
  const real = nearest.line.real as Pt[];
  const total = lengthOf(cells);
  const scale = lengthOf(real) / (total || 1);
  // How far along the track the part's two ends are, on the grid.
  const reach = (x: number) => {
    let walked = 0;
    for (let i = 1; i < cells.length; i++) {
      const a = cells[i - 1] as Cell;
      const b = cells[i] as Cell;
      const step = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if ((a[0] - x) * (b[0] - x) <= 0 && a[0] !== b[0]) return walked + (step * (x - a[0])) / (b[0] - a[0]);
      walked += step;
    }
    return Math.abs(x - (cells[0] as Cell)[0]) < Math.abs(x - (cells[cells.length - 1] as Cell)[0]) ? 0 : total;
  };
  const [s1, s2] = [reach(x1), reach(x2)].sort((p, q) => p - q) as [number, number];
  const path = slice(real, s1 * scale, s2 * scale) as Pt[];
  if (path.length < 2) return null;
  // The side, from the grid: to the right of the track's way where the part lies below an
  // eastward track.
  const here = slice(cells, Math.max(0, nearest.at - 0.05), Math.min(total, nearest.at + 0.05));
  const dirx = (here[here.length - 1] as Cell)[0] - (here[0] as Cell)[0];
  const side = (dirx >= 0 ? 1 : -1) * down;
  return { path, side, other: opposite ? ((opposite.line.real ?? []) as Pt[]) : null };
}

/** The shortest distance from a point to a path. */
function toPath(p: Pt, path: Pt[]): number {
  let best = Infinity;
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1] as Pt;
    const b = path[i] as Pt;
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const l2 = dx * dx + dy * dy;
    const t = l2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)) : 0;
    best = Math.min(best, Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy));
  }
  return best;
}

/** The platforms and the station building where the plan has them, beside their tracks. A
 * platform between two tracks fills the space between them. */
function platformsOf(panel: Panel, u: number): { platforms: Pt[][]; building: Pt[] | null; reach: Map<string, number> } {
  const near = 12 * u;
  const reach = new Map<string, number>();
  const platforms: Pt[][] = [];
  for (const rect of panel.platforms ?? []) {
    const found = beside(panel, rect);
    if (!found) continue;
    const mid = along(found.path, lengthOf(found.path) / 2).at;
    const between = found.other ? toPath(mid, found.other) : 0;
    const width = found.other && between > 2 * near + 6 * u ? between - 2 * near : 20 * u;
    platforms.push(band(found.path, found.side * near, found.side * (near + width)));
    const key = `${found.side}:${found.path[0]?.join(",")}`;
    reach.set(key, Math.max(reach.get(key) ?? 0, near + width));
  }
  let building: Pt[] | null = null;
  if (panel.building) {
    const found = beside(panel, panel.building.cells);
    if (found) {
      const behind = Math.max(near + 20 * u, ...[...reach.values()]) + 6 * u;
      building = band(found.path, found.side * behind, found.side * (behind + 27 * u));
    }
  }
  return { platforms, building, reach };
}

/** A small random generator with a seed, so the landscape is the same every time. */
function seeded(seed: number): () => number {
  let s = seed;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

/** Trees and bushes, placed simply: anywhere on the grass, not on the tracks, the platforms or
 * the building. */
function treesOf(box: [number, number, number, number], tracks: FotoTrack[], keep: Pt[][], u: number): Tree[] {
  const [x, y, w, h] = box;
  const clear = (FOTO.bank / 2 + 10) * u;
  const cell = 40 * u;
  const grid = new Map<string, Pt[]>();
  for (const t of tracks) {
    const total = lengthOf(t.path);
    for (let s = 0; s <= total; s += 8 * u) {
      const p = along(t.path, s).at;
      const k = `${Math.floor(p[0] / cell)},${Math.floor(p[1] / cell)}`;
      grid.set(k, [...(grid.get(k) ?? []), p]);
    }
  }
  const free = (p: Pt, r: number) => {
    const [gx, gy] = [Math.floor(p[0] / cell), Math.floor(p[1] / cell)];
    for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) for (const q of grid.get(`${gx + i},${gy + j}`) ?? []) if (dist(p, q) < clear + r) return false;
    return !keep.some((poly) => inside(p, poly));
  };
  const random = seeded(7);
  const count = Math.max(12, Math.min(500, Math.round((w * h) / (110 * u) ** 2)));
  const found: Tree[] = [];
  for (let i = 0; i < count; i++) {
    const bush = random() < 0.4;
    const r = (bush ? 3 + random() * 3 : 7 + random() * 9) * u;
    const p: Pt = [x + random() * w, y + random() * h];
    if (free(p, r)) found.push({ at: p, r, bush });
  }
  return found;
}

function inside(p: Pt, poly: Pt[]): boolean {
  let yes = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i] as Pt;
    const b = poly[j] as Pt;
    if (a[1] > p[1] !== b[1] > p[1] && p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]) yes = !yes;
  }
  return yes;
}

/** Mätbilden under: the gauge of the source's scale, and the photographed boards, which the view
 * shows whole. */
export type FotoPhoto = { gauge: number | null; boards: Pt[][] };

/** Everything Foto draws, in the drawing's units: the same logical drawing as every skin, put
 * on the station's real geometry. Null without the real shape. With the measuring images under,
 * the rails are laid at the scale's own gauge, on the photo's, and the view takes in the boards. */
export function fotoScene(panel: Panel, drawn: Drawing, state: Filled, photo: FotoPhoto | null = null): FotoScene | null {
  if (!hasRealForm(panel) || !panel.real_box) return null;
  const u = (photo?.gauge ?? gaugeOf(panel)) / FOTO.gauge;
  const [bx, by, bw, bh] = panel.real_box;
  const pad = 40 * u;
  let box: [number, number, number, number] = [bx - pad, by - pad, bw + 2 * pad, bh + 2 * pad];
  const corners = (photo?.boards ?? []).flat();
  if (corners.length) {
    const x0 = Math.min(box[0], ...corners.map((p) => p[0]));
    const y0 = Math.min(box[1], ...corners.map((p) => p[1]));
    const x1 = Math.max(box[0] + box[2], ...corners.map((p) => p[0]));
    const y1 = Math.max(box[1] + box[3], ...corners.map((p) => p[1]));
    box = [x0, y0, x1 - x0, y1 - y0];
  }
  const real = new Map(panel.lines.map((l) => [l.piece, (l.real ?? []) as Pt[]]));
  const tracks: FotoTrack[] = drawn.lines.filter((l) => (real.get(l.piece) ?? []).length > 1).map((l) => ({ piece: l.piece, path: real.get(l.piece) as Pt[], state: l.state, route: l.route, line: l.line }));
  const panelSignals = new Map((panel.signals ?? []).map((s) => [s.name, s]));
  const signals: FotoSignal[] = [];
  for (const s of drawn.signals) {
    const found = panelSignals.get(s.name);
    if (!found?.real) continue;
    signals.push({ ...s, track: found.real as Pt, heading: unit((found.real_toward ?? [1, 0]) as Pt) });
  }
  const switchReal = new Map((panel.switches ?? []).map((s) => [s.number, s]));
  const switches: FotoSwitch[] = [];
  for (const s of drawn.switches) {
    const found = switchReal.get(s.number);
    if (!found?.real) continue;
    const at = found.real as Pt;
    const up = s.label[1] <= s.cell[1] ? -1 : 1;
    switches.push({ ...s, at, label: [at[0], at[1] + up * (up < 0 ? 15 : 21) * u] });
  }
  const buffers: FotoBuffer[] = drawn.buffers.flatMap((b) => {
    const way = nodeWay(panel, b.id);
    return way ? [{ id: b.id, at: way.at, heading: way.heading }] : [];
  });
  const points: FotoPoint[] = drawn.points.flatMap((p) => {
    const node = panel.nodes.find((n) => n.id === p.name);
    return node?.real ? [{ name: p.name, at: node.real as Pt }] : [];
  });
  const trackNames = new Map((panel.track_names ?? []).map((t) => [t.name, t]));
  const names: FotoName[] = drawn.names.flatMap((n) => {
    const found = trackNames.get(n.name)?.real;
    return found ? [{ name: n.name, at: found as Pt, hidden: n.hidden }] : [];
  });
  const labels: FotoLabel[] = (panel.labels ?? []).flatMap((l) => (l.real ? [{ text: l.text, kind: l.kind, at: l.real as Pt }] : []));
  const tables: FotoTable[] = drawn.tables.flatMap((t) => (t.real && t.realRadius ? [{ ...t, at: t.real as Pt, r: t.realRadius, heading: (t.realToward ?? [1, 0]) as Pt }] : []));
  const nodeReal = new Map(panel.nodes.map((n) => [n.id, n.real]));
  const functionAt = new Map((panel.functions ?? []).map((f) => [f.name, f.node]));
  const buttons: FotoButton[] = drawn.buttons.flatMap((b) => {
    const at = nodeReal.get(functionAt.get(b.name) ?? "");
    return at ? [{ name: b.name, type: b.type, at: [at[0], at[1] + (b.side === "over" ? -16 : 16) * u] as Pt, on: b.on }] : [];
  });
  const { platforms, building } = platformsOf(panel, u);
  const trees = treesOf(box, tracks, building ? [...platforms, building] : platforms, u);
  return { box, u, tracks, signals, switches, buffers, points, names, labels, tables, buttons, platforms, building, trees, trains: trainsOf(panel, state) };
}

// --- Mätbilden under (#89 del d4) -----------------------------------------------------------------

/** SVG's matrix (a, b, c, d, e, f) applied to a point. */
export function applyMatrix(m: readonly number[], p: Pt): Pt {
  const [a = 1, b = 0, c = 0, d = 1, e = 0, f = 0] = m;
  return [a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f];
}

/** A measuring image as Foto draws it: its pixels moved by `transform` into the station's mm,
 * clipped to `clip`, its module's board. */
export type FotoImage = { key: string; url: string; title: string; width: number; height: number; matrix: number[]; transform: string; clip: Pt[] };

/** The images to draw: none unless the station has them and has chosen to show them. */
export function imagesOf(under: ImageUnder | null | undefined): FotoImage[] {
  if (!under?.available || !under.on) return [];
  return (under.images ?? []).flatMap((i) =>
    i.url && i.outline.length >= 3
      ? [{ key: `${i.module}:${i.version}`, url: i.url, title: i.title, width: i.width, height: i.height, matrix: i.matrix, transform: `matrix(${i.matrix.map((v) => Math.round(v * 1e6) / 1e6).join(" ")})`, clip: i.outline as Pt[] }]
      : [],
  );
}

/** Does a point lie on a photographed board? */
export function onPhoto(images: FotoImage[], p: Pt): boolean {
  return images.some((i) => inside(p, i.clip));
}

/** Does a track lie on a photographed board, by its middle? */
export function trackOnPhoto(images: FotoImage[], path: Pt[]): boolean {
  return images.length > 0 && path.length > 1 && onPhoto(images, along(path, lengthOf(path) / 2).at);
}

/** A polygon's middle, by its corners. */
export function middleOf(poly: Pt[]): Pt {
  const n = poly.length || 1;
  return [poly.reduce((s, p) => s + p[0], 0) / n, poly.reduce((s, p) => s + p[1], 0) / n];
}

/** A point's place in the view, from 0 to 1 across and down: for scrolling to a train. */
export function placeIn(box: [number, number, number, number], p: Pt): Pt {
  return [(p[0] - box[0]) / box[2], (p[1] - box[1]) / box[3]];
}
