// Rita (#85 del a): the station drawn on the grid, without React. The drawing is the station
// model with its panel plan (contracts/tkl.py, TklDrawing): every switch, crossing and track end
// has a cell, and every track runs from node to node over the grid, horizontally, vertically or
// at 45°, with the joints between its pieces counted in cells along the way (STD-25, TKL81). The
// owner draws six objects (STUDIO-02): tracks, switches, signals, track-circuit boundaries,
// buffer stops and line exits. Each tool here is a pure function from one drawing to the next,
// or a RitaError with the reason in Swedish; TKL's server turns the drawing into the model and
// computes the rest (tkl/studio/rita.py). The same functions redraw the panel of a station that
// has a model (STUDIO-30): nodes move between cells, and tracks get new bends. Nothing here
// names a station (RS13).
import type {
  Drawing,
  Lever,
  LineExit,
  Model,
  ModelNode,
  NodeType,
  Origin,
  Piece,
  Placement,
  Plan,
  PlanTrack,
  Position,
  Signal,
  SignalType,
  StationTrack,
  Switch,
  SwitchControl,
  SwitchType,
  TrackCircuit,
  TrackName,
} from "./api";

export type Cell = [number, number];
/** A contract's own fields, without the index signature its schema allows. */
type Known<T> = { [K in keyof T as string extends K ? never : K]: T[K] };
export type Track = Omit<Known<PlanTrack>, "via" | "joints"> & { via: Cell[]; joints: number[] };
export type FullPlan = Omit<Known<Plan>, "tracks" | "signals" | "track_names"> & { tracks: Track[]; signals: Record<string, Placement>; track_names: TrackName[] };
type Listed = "basis" | "switches" | "levers" | "signals" | "track_circuits" | "station_tracks" | "line_exits" | "turntables" | "functions" | "panel";
export type FullModel = Omit<Known<Model>, Listed> & {
  basis: string[];
  switches: Switch[];
  levers: Lever[];
  signals: Signal[];
  track_circuits: TrackCircuit[];
  station_tracks: StationTrack[];
  line_exits: LineExit[];
  turntables: NonNullable<Model["turntables"]>;
  functions: NonNullable<Model["functions"]>;
  panel: FullPlan;
};
export type FullDrawing = { model: FullModel; proposal: boolean };

/** What the owner said no to, or what a tool cannot do, in Swedish. */
export class RitaError extends Error {}

export const DRAWN: Origin = { source: "drawn", confirmed: true, ref: null, note: null };

/** What a new object's origin is: none where the whole model is drawn, which it then takes
 * after; drawn and confirmed in a model from another source (RS5). */
export function originFor(model: Model): Origin | null {
  return model.origin?.source === "drawn" && model.origin.confirmed ? null : DRAWN;
}
/** How far the switch tool's diverging leg reaches: one of the engine's rows (STD-20). */
export const STUB = 3;
const EPS = 1e-6;

/** The drawing with every list and map present, as the editor works on it. */
export function full(drawing: Drawing): FullDrawing {
  const m = drawing.model;
  const plan: Plan = m.panel ?? { basis: null, grid: { dx: 24, dy: 24 }, turntable: null, nodes: {}, tracks: [], name_offset: null, building: null, deviation: null };
  return {
    proposal: !!drawing.proposal,
    model: {
      ...m,
      basis: m.basis ?? [],
      switches: m.switches ?? [],
      levers: m.levers ?? [],
      signals: m.signals ?? [],
      track_circuits: m.track_circuits ?? [],
      station_tracks: m.station_tracks ?? [],
      line_exits: m.line_exits ?? [],
      turntables: m.turntables ?? [],
      functions: m.functions ?? [],
      panel: {
        ...plan,
        tracks: plan.tracks.map((t) => ({ ...t, via: t.via ?? [], joints: t.joints ?? [] })),
        signals: plan.signals ?? {},
        track_names: plan.track_names ?? [],
      },
    },
  };
}

// --- Lengths and ways on the grid -------------------------------------------------------------

type Grid = { dx: number; dy: number };

export const round4 = (v: number) => Math.round(v * 10_000) / 10_000;
const same = (a: Cell, b: Cell) => Math.abs(a[0] - b[0]) < 1e-4 && Math.abs(a[1] - b[1]) < 1e-4;

/** A track's length between two cells, as the plan counts its joints: in cells along the
 * grid, or straight in the cell's width where the track may run at any angle. */
export function length(a: Cell, b: Cell, free: boolean, grid: Grid): number {
  if (free) return Math.hypot((b[0] - a[0]) * grid.dx, (b[1] - a[1]) * grid.dy) / grid.dx;
  return Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
}

function wayLength(way: Cell[], free: boolean, grid: Grid): number {
  let total = 0;
  for (let i = 1; i < way.length; i++) total += length(way[i - 1]!, way[i]!, free, grid);
  return total;
}

function marksOf(way: Cell[], free: boolean, grid: Grid): number[] {
  const marks = [0];
  for (let i = 1; i < way.length; i++) marks.push(marks[i - 1]! + length(way[i - 1]!, way[i]!, free, grid));
  return marks;
}

function along(way: Cell[], marks: number[], t: number): Cell {
  for (let i = 0; i + 1 < way.length; i++) {
    if (t <= marks[i + 1]! + 1e-9) {
      const size = marks[i + 1]! - marks[i]!;
      const f = size === 0 ? 0 : (t - marks[i]!) / size;
      const a = way[i]!;
      const b = way[i + 1]!;
      return [round4(a[0] + (b[0] - a[0]) * f), round4(a[1] + (b[1] - a[1]) * f)];
    }
  }
  return way[way.length - 1]!;
}

/** The stretch of a way between two places along it (tkl/standard/plan.py, _part). */
function partOf(way: Cell[], free: boolean, grid: Grid, start: number, end: number): Cell[] {
  const marks = marksOf(way, free, grid);
  const found: Cell[] = [along(way, marks, start)];
  for (let i = 1; i < way.length - 1; i++) if (start + 1e-9 < marks[i]! && marks[i]! < end - 1e-9) found.push(way[i]!);
  found.push(along(way, marks, end));
  return found;
}

export type Geometry = {
  /** Every node's cell: its own in the plan, or where it lies along its track. */
  cells: Map<string, Cell>;
  /** Every piece's way, from its start to its end. */
  paths: Map<string, Cell[]>;
  /** The plan track each piece is drawn in. */
  trackOf: Map<string, number>;
  free: Set<string>;
  /** The pieces at each node. */
  touching: Map<string, string[]>;
};

export function wayOf(plan: FullPlan, track: Track): Cell[] | null {
  const a = plan.nodes[track.start];
  const b = plan.nodes[track.end];
  return a && b ? [a, ...track.via, b] : null;
}

export function isFree(plan: FullPlan, track: Track): boolean {
  const table = plan.turntable?.node ?? null;
  return !!track.free || (table !== null && (track.start === table || track.end === table));
}

export function geometry(model: FullModel): Geometry {
  const plan = model.panel;
  const pieces = new Map(model.pieces.map((p) => [p.id, p]));
  const cells = new Map<string, Cell>(Object.entries(plan.nodes) as [string, Cell][]);
  const paths = new Map<string, Cell[]>();
  const trackOf = new Map<string, number>();
  const free = new Set<string>();
  plan.tracks.forEach((track, index) => {
    const way = wayOf(plan, track);
    if (!way) return;
    const loose = isFree(plan, track);
    const marks = [0, ...track.joints, wayLength(way, loose, plan.grid)];
    track.pieces.forEach((placed, i) => {
      const piece = pieces.get(placed.id);
      if (!piece || i + 1 >= marks.length) return;
      const part = partOf(way, loose, plan.grid, marks[i]!, marks[i + 1]!);
      const path = placed.reversed ? [...part].reverse() : part;
      paths.set(piece.id, path);
      trackOf.set(piece.id, index);
      if (loose) free.add(piece.id);
      if (!cells.has(piece.start)) cells.set(piece.start, path[0]!);
      if (!cells.has(piece.end)) cells.set(piece.end, path[path.length - 1]!);
    });
  });
  const touching = new Map<string, string[]>(model.nodes.map((n) => [n.id, []]));
  for (const piece of model.pieces) {
    for (const node of [piece.start, piece.end]) {
      const list = touching.get(node) ?? [];
      list.push(piece.id);
      touching.set(node, list);
    }
  }
  return { cells, paths, trackOf, free, touching };
}

// --- Points, segments and crossings on the grid ---------------------------------------------

const crossOf = (o: Cell, a: Cell, b: Cell) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

/** Horizontal, vertical or diagonal between cells (STD-26). */
export function straight(a: Cell, b: Cell): boolean {
  const dc = Math.abs(b[0] - a[0]);
  const dr = Math.abs(b[1] - a[1]);
  return dc < EPS || dr < EPS || Math.abs(dc - dr) < EPS;
}

/** p on the segment a–b. */
export function onSegment(p: Cell, a: Cell, b: Cell): boolean {
  if (Math.abs(crossOf(a, b, p)) > EPS * Math.max(1, Math.abs(b[0] - a[0]) + Math.abs(b[1] - a[1]))) return false;
  return Math.min(a[0], b[0]) - EPS <= p[0] && p[0] <= Math.max(a[0], b[0]) + EPS && Math.min(a[1], b[1]) - EPS <= p[1] && p[1] <= Math.max(a[1], b[1]) + EPS;
}

/** Where the segments a–b and c–d meet: a point, an overlap, or nowhere (grid.py, _meeting). */
function meeting(a: Cell, b: Cell, c: Cell, d: Cell): ["point" | "overlap", Cell] | null {
  const d1 = crossOf(c, d, a);
  const d2 = crossOf(c, d, b);
  const d3 = crossOf(a, b, c);
  const d4 = crossOf(a, b, d);
  const scale = Math.max(1, Math.abs(b[0] - a[0]) + Math.abs(b[1] - a[1]), Math.abs(d[0] - c[0]) + Math.abs(d[1] - c[1]));
  const tol = EPS * scale * scale;
  if (Math.abs(d1) <= tol && Math.abs(d2) <= tol) {
    const shared: Cell[] = [];
    for (const p of [...[a, b].filter((p) => onSegment(p, c, d)), ...[c, d].filter((p) => onSegment(p, a, b))]) if (!shared.some((q) => same(p, q))) shared.push(p);
    if (shared.length >= 2) return ["overlap", [(shared[0]![0] + shared[1]![0]) / 2, (shared[0]![1] + shared[1]![1]) / 2]];
    return shared.length ? ["point", shared[0]!] : null;
  }
  if ((d1 > tol && d2 > tol) || (d1 < -tol && d2 < -tol)) return null;
  if ((d3 > tol && d4 > tol) || (d3 < -tol && d4 < -tol)) return null;
  const t = Math.abs(d1 - d2) > 0 ? d1 / (d1 - d2) : 0;
  return ["point", [round4(a[0] + (b[0] - a[0]) * t), round4(a[1] + (b[1] - a[1]) * t)]];
}

/** The end of a drag from `a`, snapped to the nearest of the eight directions on the grid. */
export function snapStraight(a: Cell, b: Cell): Cell {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const angle = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * (Math.PI / 4);
  const ux = Math.round(Math.cos(angle));
  const uy = Math.round(Math.sin(angle));
  const steps = Math.round(Math.max(Math.abs(dx), Math.abs(dy)));
  return [a[0] + ux * steps, a[1] + uy * steps];
}

export function nodeAt(g: Geometry, cell: Cell, reach = 0.35): string | null {
  let best: string | null = null;
  let near = reach;
  for (const [id, c] of g.cells) {
    const d = Math.hypot(c[0] - cell[0], c[1] - cell[1]);
    if (d <= near) {
      near = d;
      best = id;
    }
  }
  return best;
}

/** The nearest place on a piece, within reach: on the grid's points along a straight
 * stretch, anywhere along a free one. */
export function pieceAt(g: Geometry, cell: Cell, reach = 0.4): { piece: string; at: Cell } | null {
  let best: { piece: string; at: Cell; d: number } | null = null;
  for (const [piece, path] of g.paths) {
    for (let i = 1; i < path.length; i++) {
      const a = path[i - 1]!;
      const b = path[i]!;
      const vx = b[0] - a[0];
      const vy = b[1] - a[1];
      const size = vx * vx + vy * vy;
      if (size === 0) continue;
      const s = Math.max(0, Math.min(1, ((cell[0] - a[0]) * vx + (cell[1] - a[1]) * vy) / size));
      const p: Cell = [a[0] + vx * s, a[1] + vy * s];
      const d = Math.hypot(p[0] - cell[0], p[1] - cell[1]);
      if (d > reach || (best && d >= best.d)) continue;
      let at: Cell = [round4(p[0]), round4(p[1])];
      if (!g.free.has(piece) && straight(a, b)) {
        const steps = Math.max(Math.abs(vx), Math.abs(vy));
        const k = Math.round(s * steps);
        at = [round4(a[0] + (vx / steps) * k), round4(a[1] + (vy / steps) * k)];
      }
      best = { piece, at, d };
    }
  }
  return best ? { piece: best.piece, at: best.at } : null;
}

// --- Names and ids ----------------------------------------------------------------------------

function fresh(taken: Set<string>, prefix: string): string {
  let i = 1;
  while (taken.has(`${prefix}${i}`)) i++;
  return `${prefix}${i}`;
}

/** Every number a switch or a slip part has, and every LocoNet address in use. */
function switchNumbers(model: FullModel): Set<string> {
  const found = new Set<string>();
  for (const s of model.switches) {
    found.add(s.number);
    if (s.address) found.add(String(s.address.number));
    for (const part of s.parts ?? []) {
      found.add(part.number);
      if (part.address) found.add(String(part.address.number));
    }
  }
  return found;
}

/** A new switch's number: the lowest free LocoNet address, as the default (STUDIO-19). */
export function nextSwitchNumber(model: FullModel): number {
  const taken = switchNumbers(model);
  let n = 1;
  while (taken.has(String(n))) n++;
  return n;
}

const EXIT_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

function nextExitId(model: FullModel): string {
  const taken = new Set(model.line_exits.map((e) => e.id));
  for (const letter of EXIT_LETTERS) if (!taken.has(letter)) return letter;
  return fresh(taken, "A");
}

/** The parts a lever lays: an ordinary or Y switch's own number, a slip's parts. */
export function partsOf(sw: Switch): string[] {
  return sw.type === "ordinary" || sw.type === "y" ? [sw.number] : (sw.parts ?? []).map((p) => p.number);
}

const SIGNAL_PREFIX: Record<SignalType, string> = { hsi: "H", hdvsi: "H", dvsi: "D", fsi: "F", stop_lamp: "S" };

/** The track a piece belongs to, for names: its number, its station track, or the exit its
 * line leads to. */
export function trackLabel(model: FullModel, g: Geometry, piece: string): string {
  const pieces = new Map(model.pieces.map((p) => [p.id, p]));
  const station = new Map<string, string>();
  for (const t of model.station_tracks) for (const p of t.pieces ?? []) station.set(p, t.id);
  const exits = new Map(model.line_exits.map((e) => [e.node, e.id]));
  const switches = new Set(model.switches.map((s) => s.node));
  const seen = new Set<string>();
  const queue = [piece];
  while (queue.length) {
    const here = queue.shift()!;
    if (seen.has(here)) continue;
    seen.add(here);
    const found = pieces.get(here);
    if (!found) continue;
    const label = found.track ?? station.get(here);
    if (label) return label;
    for (const node of [found.start, found.end]) {
      if (exits.has(node)) return exits.get(node)!;
      if (switches.has(node)) continue;
      for (const next of g.touching.get(node) ?? []) if (!seen.has(next)) queue.push(next);
    }
    if (seen.size > 60) break;
  }
  return "";
}

/** A signal's name after its track and direction (STUDIO-19): H, D, F or S for the type, the
 * track, and ö or v for east or west. */
export function signalName(model: FullModel, g: Geometry, type: SignalType, approach: string, facing: Facing): string {
  const base = `${SIGNAL_PREFIX[type]}${trackLabel(model, g, approach)}${facing === "east" ? "ö" : "v"}`;
  const taken = new Set(model.signals.map((s) => s.name));
  if (!taken.has(base)) return base;
  let i = 2;
  while (taken.has(`${base}${i}`)) i++;
  return `${base}${i}`;
}

// --- Changing the drawing ---------------------------------------------------------------------

const withPlan = (model: FullModel, panel: Partial<FullPlan>): FullModel => ({ ...model, panel: { ...model.panel, ...panel } });

function cellOf(g: Geometry, node: string): Cell {
  const found = g.cells.get(node);
  if (!found) throw new RitaError(`Noden ${node} har ingen ruta.`);
  return found;
}

/** The direction a piece leaves a node, on screen. */
function leaving(model: FullModel, g: Geometry, piece: string, node: string): [number, number] | null {
  const path = g.paths.get(piece);
  const found = model.pieces.find((p) => p.id === piece);
  if (!path || path.length < 2 || !found) return null;
  const [a, b] = found.start === node ? [path[0]!, path[1]!] : [path[path.length - 1]!, path[path.length - 2]!];
  const { dx, dy } = model.panel.grid;
  const vx = (b[0] - a[0]) * dx;
  const vy = (b[1] - a[1]) * dy;
  const size = Math.hypot(vx, vy);
  return size ? [vx / size, vy / size] : null;
}

const dot = (a: [number, number], b: [number, number]) => a[0] * b[0] + a[1] * b[1];

/** Splits a piece at a place along it: the piece keeps its first part and a new piece takes the
 * rest, with everything that named the piece at its far end moved to the new one. The new node
 * is a joint inside the same plan track, or with `pin`, a node of its own that ends the track
 * there. */
export function splitPiece(model: FullModel, piece: string, at: Cell, pin: boolean): { model: FullModel; node: string } {
  const g = geometry(model);
  const path = g.paths.get(piece);
  const old = model.pieces.find((p) => p.id === piece);
  const index = g.trackOf.get(piece);
  if (!path || !old || index === undefined) throw new RitaError("Spåret går inte att dela där.");
  const plan = model.panel;
  const track = plan.tracks[index]!;
  const loose = g.free.has(piece);
  // How far along the piece the place is, in the plan's length and on screen.
  let t = 0;
  let px = 0;
  let found = false;
  const pxOf = (a: Cell, b: Cell) => Math.hypot((b[0] - a[0]) * plan.grid.dx, (b[1] - a[1]) * plan.grid.dy);
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1]!;
    const b = path[i]!;
    if (onSegment(at, a, b)) {
      t += length(a, at, loose, plan.grid);
      px += pxOf(a, at);
      found = true;
      break;
    }
    t += length(a, b, loose, plan.grid);
    px += pxOf(a, b);
  }
  const total = wayLength(path, loose, plan.grid);
  let totalPx = 0;
  for (let i = 1; i < path.length; i++) totalPx += pxOf(path[i - 1]!, path[i]!);
  if (!found || t < 1e-6 || t > total - 1e-6) throw new RitaError("Spåret går inte att dela där.");
  const f = totalPx ? px / totalPx : 0.5;
  const nodes = new Set(model.nodes.map((n) => n.id));
  const node = fresh(nodes, "n");
  const next = fresh(new Set(model.pieces.map((p) => p.id)), "s");
  const end = old.end;
  const [first, second] = splitLine(old.geometry ?? [], f);
  const pieces = model.pieces.flatMap((p) =>
    p.id === piece ? [{ ...p, end: node, geometry: first }, { ...p, id: next, start: node, end, geometry: second }] : [p],
  );
  const atEnd = (name: string | null | undefined, where: string) => (name === piece && where === end ? next : name ?? null);
  const switches = model.switches.map((s) => ({
    ...s,
    trunk: atEnd(s.trunk, s.node),
    straight: atEnd(s.straight, s.node),
    diverging: atEnd(s.diverging, s.node),
    paths: (s.paths ?? []).map((p) => ({ ...p, between: p.between.map((b) => atEnd(b, s.node) ?? b) as [string, string] })),
  }));
  const signals = model.signals.map((s) => (s.approach === piece && s.node === end ? { ...s, approach: next } : s));
  const insert = (list: string[] | undefined) => (list ?? []).flatMap((p) => (p === piece ? [p, next] : [p]));
  // The plan: the new piece follows in the track, with a joint where the piece was split.
  const i = track.pieces.findIndex((p) => p.id === piece);
  const reversed = !!track.pieces[i]?.reversed;
  const startMark = i === 0 ? 0 : track.joints[i - 1]!;
  const pieceLength = i < track.joints.length ? track.joints[i]! - startMark : wayLength(wayOf(plan, track)!, loose, plan.grid) - startMark;
  const joint = round4(startMark + (reversed ? pieceLength - t : t));
  const placedPieces = [...track.pieces];
  placedPieces.splice(reversed ? i : i + 1, 0, { id: next, reversed });
  const joints = [...track.joints, joint].sort((a, b) => a - b);
  const tracks = plan.tracks.map((tr, k) => (k === index ? { ...tr, pieces: placedPieces, joints } : tr));
  const moved = (piece_: string, at_: number): { piece: string; at: number } => {
    if (piece_ !== piece) return { piece: piece_, at: at_ };
    if (at_ <= f + 1e-9) return { piece, at: round4(f ? at_ / f : 0) };
    return { piece: next, at: round4((at_ - f) / (1 - f)) };
  };
  const placements = Object.fromEntries(Object.entries(plan.signals).map(([name, p]) => [name, { ...p, ...moved(p.piece, p.at) }]));
  const trackNames = plan.track_names.map((n) => ({ ...n, ...moved(n.piece, n.at) }));
  const deviation = plan.deviation
    ? {
        ...plan.deviation,
        rewired: insert(plan.deviation.rewired),
        new_pieces: insert(plan.deviation.new_pieces),
        not_shown: plan.deviation.not_shown ? { ...plan.deviation.not_shown, pieces: insert(plan.deviation.not_shown.pieces) } : plan.deviation.not_shown,
      }
    : null;
  let made: FullModel = {
    ...model,
    nodes: [...model.nodes, { id: node, type: "joint" }],
    pieces,
    switches,
    signals,
    track_circuits: model.track_circuits.map((c) => ({ ...c, pieces: insert(c.pieces) })),
    station_tracks: model.station_tracks.map((s) => ({ ...s, pieces: insert(s.pieces) })),
    turntables: model.turntables.map((t) => ({ ...t, tracks: t.tracks.map((r) => (r.piece === piece && t.node === end ? { ...r, piece: next } : r)) })),
    functions: model.functions.map((fn) => ({ ...fn, pieces: insert(fn.pieces) })),
    panel: { ...plan, tracks, signals: placements, track_names: trackNames, deviation },
  };
  if (pin) made = pinNode(made, node);
  return { model: made, node };
}

/** A real shape split at a fraction of its length. */
function splitLine(points: [number, number][], f: number): [[number, number][], [number, number][]] {
  if (points.length < 2) return [[], []];
  const lengths = points.slice(1).map((p, i) => Math.hypot(p[0] - points[i]![0], p[1] - points[i]![1]));
  const total = lengths.reduce((a, b) => a + b, 0);
  let gone = 0;
  for (let i = 0; i < lengths.length; i++) {
    if (gone + lengths[i]! >= f * total) {
      const k = lengths[i]! ? (f * total - gone) / lengths[i]! : 0;
      const a = points[i]!;
      const b = points[i + 1]!;
      const p: [number, number] = [Math.round((a[0] + (b[0] - a[0]) * k) * 10) / 10, Math.round((a[1] + (b[1] - a[1]) * k) * 10) / 10];
      return [[...points.slice(0, i + 1), p], [p, ...points.slice(i + 1)]];
    }
    gone += lengths[i]!;
  }
  return [points, [points[points.length - 1]!]];
}

/** A node gets a cell of its own in the plan, so that tracks can meet there: a joint inside a
 * track splits the track in two. */
export function pinNode(model: FullModel, node: string): FullModel {
  const plan = model.panel;
  if (plan.nodes[node]) return model;
  const g = geometry(model);
  const cell = cellOf(g, node);
  const pieces = new Map(model.pieces.map((p) => [p.id, p]));
  const index = plan.tracks.findIndex((track) => track.pieces.some((placed, k) => k < track.pieces.length - 1 && (placed.reversed ? pieces.get(placed.id)?.start : pieces.get(placed.id)?.end) === node));
  const nodes = { ...plan.nodes, [node]: cell };
  if (index < 0) return withPlan(model, { nodes });
  const track = plan.tracks[index]!;
  const k = track.pieces.findIndex((placed) => (placed.reversed ? pieces.get(placed.id)?.start : pieces.get(placed.id)?.end) === node);
  const way = wayOf(plan, track)!;
  const marks = marksOf(way, isFree(plan, track), plan.grid);
  const j = track.joints[k]!;
  const inside = way.map((c, w) => ({ c, m: marks[w]! })).slice(1, -1);
  const one: Track = { ...track, end: node, pieces: track.pieces.slice(0, k + 1), joints: track.joints.slice(0, k), via: inside.filter((p) => p.m < j - 1e-6).map((p) => p.c) };
  const two: Track = {
    ...track,
    start: node,
    pieces: track.pieces.slice(k + 1),
    joints: track.joints.slice(k + 1).map((v) => round4(v - j)),
    via: inside.filter((p) => p.m > j + 1e-6).map((p) => p.c),
  };
  const tracks = [...plan.tracks.slice(0, index), one, two, ...plan.tracks.slice(index + 1)];
  return withPlan(model, { nodes, tracks });
}

/** The piece whose way runs through a place, exactly. */
export function pieceThrough(g: Geometry, at: Cell): string | null {
  for (const [piece, path] of g.paths) for (let i = 1; i < path.length; i++) if (onSegment(at, path[i - 1]!, path[i]!)) return piece;
  return null;
}

/** The node at a place: one that is there, or a new one on the piece there. */
function pointAt(model: FullModel, at: Cell, pin: boolean): { model: FullModel; node: string } {
  const g = geometry(model);
  const node = nodeAt(g, at, 0.05);
  if (node) return { model: pin ? pinNode(model, node) : model, node };
  const on = pieceThrough(g, at);
  if (on) return splitPiece(model, on, at, pin);
  throw new RitaError("Här finns inget spår.");
}

/** Where a click lands: on a node, on a track at the grid's point nearest it, or in a cell. */
export function snapPoint(g: Geometry, at: Cell): Cell {
  const node = nodeAt(g, at, 0.45);
  if (node) return g.cells.get(node)!;
  const on = pieceAt(g, at, 0.45);
  if (on) return on.at;
  return [Math.round(at[0]), Math.round(at[1])];
}

/** Track: from one cell to another, horizontally, vertically or diagonally. Where it begins or
 * ends on a track, or crosses one, the tracks are joined: a switch where three meet, a
 * crossing where four do (everything else is computed, STUDIO-02). */
export function addTrack(d: FullDrawing, from: Cell, to: Cell): FullDrawing {
  if (same(from, to)) throw new RitaError("Dra spåret från en ruta till en annan.");
  if (!straight(from, to)) throw new RitaError("Ett spår går vågrätt, lodrätt eller diagonalt mellan rutorna.");
  let model = d.model;
  let g = geometry(model);
  const cuts: Cell[] = [from, to];
  for (const cell of g.cells.values()) if (onSegment(cell, from, to) && !cuts.some((c) => same(c, cell))) cuts.push(cell);
  for (const [piece, path] of g.paths) {
    if (g.free.has(piece)) continue;
    for (let i = 1; i < path.length; i++) {
      const met = meeting(from, to, path[i - 1]!, path[i]!);
      if (!met) continue;
      if (met[0] === "overlap") throw new RitaError("Spåret ligger på ett spår som redan finns.");
      if (!cuts.some((c) => same(c, met[1]))) cuts.push(met[1]);
    }
  }
  const measure = (c: Cell) => Math.max(Math.abs(c[0] - from[0]), Math.abs(c[1] - from[1]));
  cuts.sort((a, b) => measure(a) - measure(b));
  const ends: string[] = [];
  for (const cut of cuts) {
    g = geometry(model);
    const node = nodeAt(g, cut, 0.01);
    if (node) {
      model = pinNode(model, node);
      ends.push(node);
      continue;
    }
    const on = pieceThrough(g, cut);
    if (on) {
      const split = splitPiece(model, on, cut, true);
      model = split.model;
      ends.push(split.node);
      continue;
    }
    const id = fresh(new Set(model.nodes.map((n) => n.id)), "n");
    model = withPlan({ ...model, nodes: [...model.nodes, { id, type: "joint" }] }, { nodes: { ...model.panel.nodes, [id]: [round4(cut[0]), round4(cut[1])] } });
    ends.push(id);
  }
  for (let i = 1; i < ends.length; i++) {
    const id = fresh(new Set(model.pieces.map((p) => p.id)), "s");
    const piece: Piece = { id, start: ends[i - 1]!, end: ends[i]!, track: null, geometry: [], origin: originFor(model) };
    const track: Track = { start: ends[i - 1]!, end: ends[i]!, pieces: [{ id, reversed: false }], via: [], joints: [], link: false, free: false };
    model = withPlan({ ...model, pieces: [...model.pieces, piece] }, { tracks: [...model.panel.tracks, track] });
  }
  for (const node of new Set(ends)) model = settle(model, node);
  return { model, proposal: false };
}

/** A node after the tracks at it changed: a switch where three meet, a crossing where four
 * cross straight, and no switch where fewer than its legs remain. */
export function settle(model: FullModel, node: string): FullModel {
  const g = geometry(model);
  const touching = g.touching.get(node) ?? [];
  const sw = model.switches.find((s) => s.node === node);
  const kind = model.nodes.find((n) => n.id === node)?.type;
  if (sw && touching.length < (sw.type === "ordinary" || sw.type === "y" ? 3 : 4)) return withoutSwitch(model, sw);
  if (touching.length === 3 && (!sw || ![sw.trunk, sw.straight, sw.diverging].every((leg) => leg && touching.includes(leg)))) {
    const legs = inferLegs(model, g, node);
    const switches = sw ? model.switches.map((s) => (s === sw ? { ...s, ...legs } : s)) : [...model.switches, newSwitch(model, node, legs)];
    return { ...pinNode(model, node), switches, nodes: typed(model.nodes, node, "switch") };
  }
  if (touching.length === 4 && !sw) {
    const pairs = opposites(model, g, node);
    if (pairs.length === 2) {
      const taken = new Set(model.switches.map((s) => s.number));
      const crossing: Switch = { ...blankSwitch(fresh(taken, "X"), "crossing", node, originFor(model)), paths: pairs.map((between) => ({ between, positions: {} })) };
      return { ...pinNode(model, node), switches: [...model.switches, crossing], nodes: typed(model.nodes, node, "crossing") };
    }
  }
  if (!sw && (kind === "switch" || kind === "crossing")) return { ...model, nodes: typed(model.nodes, node, "joint") };
  return model;
}

const typed = (nodes: ModelNode[], node: string, type: NodeType) => nodes.map((n) => (n.id === node ? { ...n, type } : n));

function blankSwitch(number: string, type: SwitchType, node: string, origin: Origin | null): Switch {
  return { number, type, node, trunk: null, straight: null, diverging: null, parts: [], paths: [], control: "tkl", note: null, design: null, address: null, feedback: null, origin };
}

function newSwitch(model: FullModel, node: string, legs: Legs): Switch {
  return { ...blankSwitch(String(nextSwitchNumber(model)), legs.type, node, originFor(model)), trunk: legs.trunk, straight: legs.straight, diverging: legs.diverging };
}

type Legs = { type: "ordinary" | "y"; trunk: string; straight: string; diverging: string };

/** A switch's legs, read from the drawing: the two that run straight through are the trunk and
 * the straight leg, and the third diverges; the straight leg is the one on the diverging leg's
 * side. With no two straight through it is a Y switch: the trunk is the one opposite the two
 * legs, and the upper leg counts as straight until the owner says otherwise. */
export function inferLegs(model: FullModel, g: Geometry, node: string): Legs {
  const touching = (g.touching.get(node) ?? []).slice(0, 3);
  const dirs = touching.map((p) => leaving(model, g, p, node) ?? ([1, 0] as [number, number]));
  let best = [0, 1];
  let lowest = Infinity;
  for (let i = 0; i < 3; i++)
    for (let j = i + 1; j < 3; j++)
      if (dot(dirs[i]!, dirs[j]!) < lowest) {
        lowest = dot(dirs[i]!, dirs[j]!);
        best = [i, j];
      }
  const [i, j] = best as [number, number];
  const k = 3 - i - j;
  if (lowest < -0.95) {
    const straightIsI = dot(dirs[i]!, dirs[k]!) > dot(dirs[j]!, dirs[k]!);
    return { type: "ordinary", trunk: touching[straightIsI ? j : i]!, straight: touching[straightIsI ? i : j]!, diverging: touching[k]! };
  }
  const sums = [0, 1, 2].map((a) => {
    const others = [0, 1, 2].filter((b) => b !== a);
    const sum: [number, number] = [dirs[others[0]!]![0] + dirs[others[1]!]![0], dirs[others[0]!]![1] + dirs[others[1]!]![1]];
    return dot(dirs[a]!, sum);
  });
  const trunk = sums.indexOf(Math.min(...sums));
  const legs = [0, 1, 2].filter((a) => a !== trunk).sort((a, b) => dirs[a]![1] - dirs[b]![1]);
  return { type: "y", trunk: touching[trunk]!, straight: touching[legs[0]!]!, diverging: touching[legs[1]!]! };
}

/** The pairs of pieces that cross straight through a node, the western end first. */
function opposites(model: FullModel, g: Geometry, node: string): [string, string][] {
  const touching = g.touching.get(node) ?? [];
  const dirs = touching.map((p) => leaving(model, g, p, node));
  const pairs: [string, string][] = [];
  const used = new Set<number>();
  for (let i = 0; i < touching.length; i++)
    for (let j = i + 1; j < touching.length; j++) {
      const a = dirs[i];
      const b = dirs[j];
      if (!a || !b || used.has(i) || used.has(j) || dot(a, b) > -0.95) continue;
      used.add(i).add(j);
      pairs.push(a[0] <= b[0] ? [touching[i]!, touching[j]!] : [touching[j]!, touching[i]!]);
    }
  return pairs;
}

function withoutSwitch(model: FullModel, sw: Switch): FullModel {
  const gone = new Set(partsOf(sw));
  return {
    ...model,
    switches: model.switches.filter((s) => s !== sw),
    levers: dropParts(model.levers, gone),
    nodes: typed(model.nodes, sw.node, "joint"),
  };
}

function dropParts(levers: Lever[], gone: Set<string>): Lever[] {
  return levers
    .map((l) => ({ ...l, plus: without(l.plus, gone), minus: without(l.minus, gone) }))
    .filter((l) => Object.keys(l.plus).some((p) => p in l.minus));
}

function without<T>(map: Record<string, T>, gone: Set<string>): Record<string, T> {
  return Object.fromEntries(Object.entries(map).filter(([k]) => !gone.has(k)));
}

// --- The tools --------------------------------------------------------------------------------

export type Facing = "east" | "west";
export type Side = "ne" | "se" | "nw" | "sw";
const SIDES: Record<Side, Cell> = { ne: [1, -1], se: [1, 1], nw: [-1, -1], sw: [-1, 1] };

/** Switch: on a track, with its type and the side the diverging leg leaves on. On a place where
 * three tracks meet it sets the switch's type; on a crossing, a slip. */
export function placeSwitch(d: FullDrawing, at: Cell, type: SwitchType, side: Side): FullDrawing {
  let { model, node } = pointAt(d.model, at, true);
  const g = geometry(model);
  const count = (g.touching.get(node) ?? []).length;
  if (type === "single_slip" || type === "double_slip" || type === "crossing") {
    if (count !== 4) throw new RitaError("En korsningsväxel sätts där två spår korsar varandra.");
    return { model: slip(settle(model, node), node, type), proposal: false };
  }
  if (count === 2) {
    const cell = cellOf(g, node);
    const [sx, sy] = SIDES[side];
    const drawn = addTrack({ model, proposal: false }, cell, [cell[0] + sx * STUB, cell[1] + sy * STUB]);
    model = drawn.model;
  } else if (count !== 3) {
    throw new RitaError("En växel sätts på ett spår, eller där tre spår möts.");
  }
  model = settle(model, node);
  const legs = inferLegs(model, geometry(model), node);
  const switches = model.switches.map((s) => (s.node === node ? { ...s, type, trunk: legs.trunk, straight: legs.straight, diverging: legs.diverging } : s));
  return { model: { ...model, switches }, proposal: false };
}

/** A crossing made a single or double slip, with two parts and the ways through it, or a
 * slip made a plain crossing again. */
function slip(model: FullModel, node: string, type: SwitchType): FullModel {
  const g = geometry(model);
  const pairs = opposites(model, g, node);
  if (pairs.length !== 2) throw new RitaError("Korsningen har inte två spår rakt igenom.");
  const [[a, c], [b, dd]] = pairs as [[string, string], [string, string]];
  const sw = model.switches.find((s) => s.node === node)!;
  if (type === "crossing") {
    const switches = model.switches.map((s) => (s === sw ? { ...s, type, parts: [], paths: pairs.map((between) => ({ between, positions: {} })) } : s));
    return { ...withoutParts(model, sw), switches, nodes: typed(model.nodes, node, "crossing") };
  }
  const n = sw.type === "crossing" ? nextSwitchNumber(model) : Number.parseInt(sw.parts?.[0]?.number ?? "", 10) || nextSwitchNumber(model);
  const one = String(n);
  const two = String(n + 1);
  const ways: [string, string, Position, Position][] = [
    [a, c, "+", "+"],
    [b, dd, "-", "-"],
    [a, dd, "+", "-"],
  ];
  if (type === "double_slip") ways.push([b, c, "-", "+"]);
  const made: Switch = {
    ...sw,
    number: `${one}/${two}`,
    type,
    parts: [one, two].map((number) => ({ number, address: null, feedback: null })),
    paths: ways.map(([x, y, p, q]) => ({ between: [x, y] as [string, string], positions: { [one]: p, [two]: q } })),
    origin: sw.origin,
  };
  return { ...model, switches: model.switches.map((s) => (s === sw ? made : s)), nodes: typed(model.nodes, node, "switch") };
}

function withoutParts(model: FullModel, sw: Switch): FullModel {
  return { ...model, levers: dropParts(model.levers, new Set(partsOf(sw))) };
}

/** Signal: at a node or on a track, of a type from the catalogue, applying in a direction.
 * Its approach is the track the trains come on; it is named after track and direction. */
export function placeSignal(d: FullDrawing, at: Cell, type: SignalType, facing: Facing, lamps: number | null = null): { drawing: FullDrawing; name: string } {
  const { model, node } = pointAt(d.model, at, false);
  const g = geometry(model);
  const towards: [number, number] = facing === "east" ? [1, -0.001] : [-1, 0.001];
  let approach: string | null = null;
  let lowest = -0.1;
  for (const piece of g.touching.get(node) ?? []) {
    const dir = leaving(model, g, piece, node);
    if (dir && dot(dir, towards) < lowest) {
      lowest = dot(dir, towards);
      approach = piece;
    }
  }
  if (!approach) throw new RitaError(`Inget spår leder hit ${facing === "east" ? "västerifrån" : "österifrån"}: signalen behöver ett spår som tåget kommer på.`);
  const name = signalName(model, g, type, approach, facing);
  const signal: Signal = { name, type, lamps: type === "hsi" ? lamps : null, node, approach, planned: false, address: null, origin: originFor(model) };
  const kind = model.nodes.find((n) => n.id === node)?.type;
  const nodes = kind === "joint" && (g.touching.get(node) ?? []).length === 2 ? typed(model.nodes, node, "signal_point") : model.nodes;
  return { drawing: { ...d, model: { ...model, nodes, signals: [...model.signals, signal] } }, name };
}

/** Track-circuit boundary: a short stroke across a track, where one circuit ends and the next
 * begins. */
export function placeBoundary(d: FullDrawing, at: Cell): FullDrawing {
  const { model, node } = pointAt(d.model, at, false);
  const kind = model.nodes.find((n) => n.id === node)?.type;
  const count = (geometry(model).touching.get(node) ?? []).length;
  if (kind === "signal_point" || model.signals.some((s) => s.node === node)) throw new RitaError("Signalen står redan vid ett blockstreck.");
  if (count !== 2 || (kind !== "joint" && kind !== "module_joint")) throw new RitaError("Ett blockstreck sätts på ett spår, mellan två spårbitar.");
  return { ...d, model: { ...model, nodes: typed(model.nodes, node, "block_boundary") } };
}

function endAt(model: FullModel, at: Cell, word: string): string {
  const g = geometry(model);
  const node = nodeAt(g, at);
  if (!node || (g.touching.get(node) ?? []).length !== 1) throw new RitaError(`${word} sätts där ett spår slutar.`);
  return node;
}

/** Buffer stop: where a track ends. A routes ends at it by the node's name, so a drawn one is
 * called Stoppbock and a number. */
export function placeBufferStop(d: FullDrawing, at: Cell): FullDrawing {
  const node = endAt(d.model, at, "En stoppbock");
  let model = withoutExitAt(d.model, node);
  let id = node;
  if (/^n\d+$/.test(node)) {
    id = fresh(new Set(model.nodes.map((n) => n.id)), "Stoppbock ");
    model = renameNode(model, node, id);
  }
  return { ...d, model: { ...model, nodes: typed(model.nodes, id, "buffer_stop") } };
}

/** A node's id changed everywhere it is named. */
function renameNode(model: FullModel, from: string, to: string): FullModel {
  const swap = (n: string) => (n === from ? to : n);
  return {
    ...model,
    nodes: model.nodes.map((n) => (n.id === from ? { ...n, id: to } : n)),
    pieces: model.pieces.map((p) => ({ ...p, start: swap(p.start), end: swap(p.end) })),
    switches: model.switches.map((s) => ({ ...s, node: swap(s.node) })),
    signals: model.signals.map((s) => ({ ...s, node: swap(s.node) })),
    line_exits: model.line_exits.map((e) => ({ ...e, node: swap(e.node) })),
    functions: model.functions.map((f) => ({ ...f, at: f.at ? swap(f.at) : f.at })),
    panel: {
      ...model.panel,
      nodes: renamedKeys(model.panel.nodes, from, to),
      tracks: model.panel.tracks.map((t) => ({ ...t, start: swap(t.start), end: swap(t.end) })),
      signals: renamedKeys(model.panel.signals, from, to),
    },
  };
}

/** Line exit: where a track leaves the station for the line, with an id and, if known, the
 * neighbouring station. */
export function placeLineExit(d: FullDrawing, at: Cell): { drawing: FullDrawing; id: string } {
  const node = endAt(d.model, at, "En linjeutfart");
  const model = d.model;
  if (model.line_exits.some((e) => e.node === node)) throw new RitaError("Här finns redan en linjeutfart.");
  const id = nextExitId(model);
  const line: LineExit = { id, node, neighbour: null, tracks: [], signals: [], outside_id: null, origin: originFor(model) };
  return { drawing: { ...d, model: { ...model, line_exits: [...model.line_exits, line], nodes: typed(model.nodes, node, "line_exit") } }, id };
}

function withoutExitAt(model: FullModel, node: string): FullModel {
  const gone = model.line_exits.filter((e) => e.node === node).map((e) => e.id);
  if (!gone.length) return model;
  const signals = without(model.panel.signals, new Set(gone));
  return withPlan({ ...model, line_exits: model.line_exits.filter((e) => e.node !== node) }, { signals });
}

// --- Moving and redrawing (STUDIO-30) ----------------------------------------------------------

/** The bends from one cell to another at 45°: the diagonal first where `diagonalFirst`, so a
 * switch's leg leaves it on the slant. */
export function elbow(a: Cell, b: Cell, diagonalFirst = true): Cell[] {
  if (straight(a, b)) return [];
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const sx = Math.sign(dx);
  const sy = Math.sign(dy);
  const n = Math.min(Math.abs(dx), Math.abs(dy));
  if (diagonalFirst) return [[round4(a[0] + sx * n), round4(a[1] + sy * n)]];
  return Math.abs(dx) > Math.abs(dy) ? [[round4(b[0] - sx * n), a[1]]] : [[a[0], round4(b[1] - sy * n)]];
}

/** Moves a switch, a crossing or a track end to another cell. Its tracks follow; one that no
 * longer runs on the grid gets a bend at 45°, and its joints keep their share of the way. A
 * loose end dropped on another node or a track is joined to it (RS7). */
export function moveNode(d: FullDrawing, node: string, to: Cell): FullDrawing {
  let model = d.model;
  const plan = model.panel;
  if (!plan.nodes[node]) throw new RitaError("Bara växlar, korsningar och spårändar flyttas. Ta bort och sätt signaler och blockstreck på nytt.");
  const g = geometry(model);
  const touching = g.touching.get(node) ?? [];
  const other = nodeAt(g, to, 0.05);
  const loose = touching.length === 1 && !model.line_exits.some((e) => e.node === node);
  if (other && other !== node) {
    if (!loose) throw new RitaError("Rutan är upptagen.");
    return { model: join(model, node, other), proposal: false };
  }
  const on = pieceAt(g, to, 0.05);
  if (on && same(on.at, to) && !touching.includes(on.piece)) {
    if (!loose) throw new RitaError("Rutan ligger på ett annat spår.");
    const split = splitPiece(model, on.piece, to, true);
    return { model: join(split.model, node, split.node), proposal: false };
  }
  const nodes = { ...plan.nodes, [node]: [round4(to[0]), round4(to[1])] as Cell };
  const tracks = plan.tracks.map((track) => {
    if (track.start !== node && track.end !== node) return track;
    const before = wayOf(plan, track)!;
    const loose_ = isFree(plan, track);
    const oldLength = wayLength(before, loose_, plan.grid);
    let next: Track = track;
    const after = wayOf({ ...plan, nodes }, track)!;
    if (!loose_ && !after.every((c, i) => i === 0 || straight(after[i - 1]!, c))) {
      const a = nodes[track.start]!;
      const b = nodes[track.end]!;
      const switchAtStart = model.switches.some((s) => s.node === track.start);
      next = { ...track, via: elbow(a, b, switchAtStart || !model.switches.some((s) => s.node === track.end)) };
    }
    const newLength = wayLength(wayOf({ ...plan, nodes }, next)!, loose_, plan.grid);
    const scale = oldLength ? newLength / oldLength : 1;
    return { ...next, joints: next.joints.map((j) => round4(j * scale)) };
  });
  return { model: withPlan(model, { nodes, tracks }), proposal: false };
}

/** A loose end joined to another node: its track ends there instead. */
function join(model: FullModel, loose: string, into: string): FullModel {
  const swap = (n: string) => (n === loose ? into : n);
  let made: FullModel = {
    ...model,
    nodes: model.nodes.filter((n) => n.id !== loose),
    pieces: model.pieces.map((p) => ({ ...p, start: swap(p.start), end: swap(p.end) })),
    signals: model.signals.map((s) => ({ ...s, node: swap(s.node) })),
    panel: {
      ...model.panel,
      nodes: without(model.panel.nodes, new Set([loose])),
      tracks: model.panel.tracks.map((t) => ({ ...t, start: swap(t.start), end: swap(t.end) })),
    },
  };
  made = pinNode(made, into);
  return settle(made, into);
}

/** A bend in a track moved, or a new one: the way over the grid redrawn. Its joints keep their
 * share of the way. */
export function bendTrack(d: FullDrawing, piece: string, from: Cell, to: Cell): FullDrawing {
  const model = d.model;
  const plan = model.panel;
  const g = geometry(model);
  const index = g.trackOf.get(piece);
  if (index === undefined) throw new RitaError("Spåret finns inte.");
  const track = plan.tracks[index]!;
  const way = wayOf(plan, track)!;
  let via = [...track.via];
  const near = via.findIndex((c) => Math.hypot(c[0] - from[0], c[1] - from[1]) < 0.4);
  if (near >= 0) via[near] = [round4(to[0]), round4(to[1])];
  else {
    let segment = 0;
    let best = Infinity;
    for (let i = 1; i < way.length; i++) {
      const a = way[i - 1]!;
      const b = way[i]!;
      const vx = b[0] - a[0];
      const vy = b[1] - a[1];
      const size = vx * vx + vy * vy || 1;
      const s = Math.max(0, Math.min(1, ((from[0] - a[0]) * vx + (from[1] - a[1]) * vy) / size));
      const dist = Math.hypot(a[0] + vx * s - from[0], a[1] + vy * s - from[1]);
      if (dist < best) {
        best = dist;
        segment = i - 1;
      }
    }
    via.splice(segment, 0, [round4(to[0]), round4(to[1])]);
  }
  via = via.filter((c, i) => !(same(c, plan.nodes[track.start]!) || same(c, plan.nodes[track.end]!) || (i > 0 && same(c, via[i - 1]!))));
  return { model: rerouted(model, index, via), proposal: false };
}

/** A track straightened: its bends taken away, or one bend at 45° where it must turn. */
export function straighten(d: FullDrawing, piece: string): FullDrawing {
  const model = d.model;
  const index = geometry(model).trackOf.get(piece);
  if (index === undefined) throw new RitaError("Spåret finns inte.");
  const track = model.panel.tracks[index]!;
  const a = model.panel.nodes[track.start]!;
  const b = model.panel.nodes[track.end]!;
  return { model: rerouted(model, index, elbow(a, b, model.switches.some((s) => s.node === track.start))), proposal: false };
}

function rerouted(model: FullModel, index: number, via: Cell[]): FullModel {
  const plan = model.panel;
  const track = plan.tracks[index]!;
  const free = isFree(plan, track);
  const before = wayLength(wayOf(plan, track)!, free, plan.grid);
  const next = { ...track, via };
  const after = wayLength(wayOf(plan, next)!, free, plan.grid);
  const scale = before ? after / before : 1;
  const tracks = plan.tracks.map((t, i) => (i === index ? { ...next, joints: next.joints.map((j) => round4(j * scale)) } : t));
  return withPlan(model, { tracks });
}

// --- Deleting ---------------------------------------------------------------------------------

/** Takes away a whole track, from node to node, and what stood only on it. */
export function removeTrack(d: FullDrawing, piece: string): FullDrawing {
  const index = geometry(d.model).trackOf.get(piece);
  if (index === undefined) throw new RitaError("Spåret finns inte.");
  const gone = new Set(d.model.panel.tracks[index]!.pieces.map((p) => p.id));
  return { model: removePieces(d.model, gone), proposal: false };
}

function removePieces(model: FullModel, gone: Set<string>): FullModel {
  const pieces = model.pieces.filter((p) => !gone.has(p.id));
  const counts = new Map<string, number>();
  for (const p of pieces) for (const n of [p.start, p.end]) counts.set(n, (counts.get(n) ?? 0) + 1);
  const left = new Set(model.nodes.filter((n) => (counts.get(n.id) ?? 0) > 0).map((n) => n.id));
  const signals = model.signals.filter((s) => !gone.has(s.approach) && left.has(s.node));
  const exits = model.line_exits.filter((e) => left.has(e.node));
  const goneNames = new Set([...model.signals.filter((s) => !signals.includes(s)).map((s) => s.name), ...model.line_exits.filter((e) => !exits.includes(e)).map((e) => e.id)]);
  let made: FullModel = {
    ...model,
    pieces,
    nodes: model.nodes.filter((n) => left.has(n.id)),
    signals,
    line_exits: exits.map((e) => ({ ...e, signals: (e.signals ?? []).filter((s) => !goneNames.has(s)) })),
    track_circuits: model.track_circuits.map((c) => ({ ...c, pieces: c.pieces.filter((p) => !gone.has(p)) })).filter((c) => c.pieces.length),
    station_tracks: model.station_tracks.map((s) => ({ ...s, pieces: (s.pieces ?? []).filter((p) => !gone.has(p)) })).filter((s) => s.pieces.length),
    turntables: model.turntables.map((t) => ({ ...t, tracks: t.tracks.filter((r) => !gone.has(r.piece)) })),
    functions: model.functions.map((f) => ({ ...f, pieces: (f.pieces ?? []).filter((p) => !gone.has(p)), signals: (f.signals ?? []).filter((s) => !goneNames.has(s)) })),
    panel: {
      ...model.panel,
      nodes: Object.fromEntries(Object.entries(model.panel.nodes).filter(([n]) => left.has(n))),
      tracks: model.panel.tracks.map((t) => ({ ...t, pieces: t.pieces.filter((p) => !gone.has(p.id)) })).filter((t) => t.pieces.length),
      signals: Object.fromEntries(Object.entries(model.panel.signals).filter(([name, p]) => !gone.has(p.piece) && !goneNames.has(name))),
      track_names: model.panel.track_names.filter((n) => !gone.has(n.piece)),
    },
  };
  for (const sw of made.switches) if (!left.has(sw.node)) made = withoutSwitch(made, sw);
  const signalled = new Set(made.signals.map((s) => s.node));
  made = { ...made, nodes: made.nodes.map((n) => (n.type === "signal_point" && !signalled.has(n.id) ? { ...n, type: "joint" as NodeType } : n)) };
  const touched = new Set(model.pieces.filter((p) => gone.has(p.id)).flatMap((p) => [p.start, p.end]));
  for (const node of touched) if (left.has(node)) made = settle(made, node);
  return made;
}

/** Takes away what the selection is: a signal, a boundary, a buffer stop, a line exit, or a
 * switch with its diverging track. A slip becomes a plain crossing. */
export function removeAt(d: FullDrawing, ref: Ref): FullDrawing {
  const model = d.model;
  if (ref.kind === "signal") {
    const signal = model.signals.find((s) => s.name === ref.id);
    if (!signal) return d;
    const signals = model.signals.filter((s) => s !== signal);
    const nodes = model.nodes.map((n) => (n.id === signal.node && n.type === "signal_point" && !signals.some((s) => s.node === n.id) ? { ...n, type: "joint" as NodeType } : n));
    const made = withPlan({ ...model, signals, nodes, line_exits: model.line_exits.map((e) => ({ ...e, signals: (e.signals ?? []).filter((s) => s !== signal.name) })) }, { signals: without(model.panel.signals, new Set([signal.name])) });
    return { ...d, model: made };
  }
  if (ref.kind === "piece") return removeTrack(d, ref.id);
  if (ref.kind === "lever") return { ...d, model: { ...model, levers: model.levers.filter((l) => l.id !== ref.id) } };
  if (ref.kind === "exit") {
    const line = model.line_exits.find((e) => e.id === ref.id);
    if (!line) return d;
    const made = withoutExitAt(model, line.node);
    return { ...d, model: { ...made, nodes: typed(made.nodes, line.node, "joint") } };
  }
  const node = ref.kind === "switch" ? model.switches.find((s) => s.number === ref.id)?.node : ref.id;
  if (!node) return d;
  const sw = model.switches.find((s) => s.node === node);
  if (sw) {
    if (sw.type === "single_slip" || sw.type === "double_slip") return { model: slip(model, node, "crossing"), proposal: false };
    if (sw.type === "crossing") throw new RitaError("En korsning tas bort med ett av spåren som korsar.");
    if (!sw.diverging) return { ...d, model: withoutSwitch(model, sw) };
    return removeTrack(d, sw.diverging);
  }
  const kind = model.nodes.find((n) => n.id === node)?.type;
  if (model.line_exits.some((e) => e.node === node)) return removeAt(d, { kind: "exit", id: model.line_exits.find((e) => e.node === node)!.id });
  if (kind === "block_boundary" || kind === "buffer_stop" || kind === "stop_point") return { ...d, model: { ...model, nodes: typed(model.nodes, node, "joint") } };
  return d;
}

// --- Names, numbers and types ----------------------------------------------------------------

export type RefKind = "node" | "piece" | "switch" | "signal" | "circuit" | "lever" | "exit";
export type Ref = { kind: RefKind; id: string };

function renamedKeys<T>(map: Record<string, T>, from: string, to: string): Record<string, T> {
  return Object.fromEntries(Object.entries(map).map(([k, v]) => [k === from ? to : k, v]));
}

/** A switch's number (STUDIO-19): its LocoNet address by default, and the owner's to change. */
export function renameSwitch(d: FullDrawing, node: string, number: string): FullDrawing {
  const model = d.model;
  const sw = model.switches.find((s) => s.node === node);
  const to = number.trim();
  if (!sw || to === sw.number) return d;
  if (!to) throw new RitaError("Växeln behöver ett nummer.");
  if (model.switches.some((s) => s !== sw && (s.number === to || partsOf(s).includes(to)))) throw new RitaError(`Numret ${to} finns redan.`);
  const from = sw.number;
  const plain = sw.type === "ordinary" || sw.type === "y";
  const levers = plain ? model.levers.map((l) => ({ ...l, id: l.id === from ? to : l.id, plus: renamedKeys(l.plus, from, to), minus: renamedKeys(l.minus, from, to) })) : model.levers;
  const functions = plain ? model.functions.map((f) => ({ ...f, switches: (f.switches ?? []).map((s) => (s === from ? to : s)), locked: renamedKeys(f.locked ?? {}, from, to) })) : model.functions;
  const switches = model.switches.map((s) => (s === sw ? { ...s, number: to } : s));
  return { ...d, model: { ...model, switches, levers, functions } };
}

/** The switch's LocoNet address; its number follows while it is the address (STUDIO-19). */
export function setSwitchAddress(d: FullDrawing, node: string, address: number | null): FullDrawing {
  const sw = d.model.switches.find((s) => s.node === node);
  if (!sw) return d;
  const follows = sw.address ? sw.number === String(sw.address.number) : /^\d+$/.test(sw.number);
  const switches = d.model.switches.map((s) => (s === sw ? { ...s, address: address === null ? null : { bus: "LocoNet", number: address, reversed: false, origin: null } } : s));
  const made = { ...d, model: { ...d.model, switches } };
  return follows && address !== null && String(address) !== sw.number ? renameSwitch(made, node, String(address)) : made;
}

export function setSwitchType(d: FullDrawing, node: string, type: SwitchType): FullDrawing {
  const sw = d.model.switches.find((s) => s.node === node);
  if (!sw || sw.type === type) return d;
  if (type === "single_slip" || type === "double_slip" || type === "crossing") return { model: slip(d.model, node, type), proposal: d.proposal };
  if (sw.type !== "ordinary" && sw.type !== "y") throw new RitaError("En korsning blir inte en vanlig växel.");
  return { ...d, model: { ...d.model, switches: d.model.switches.map((s) => (s === sw ? { ...s, type } : s)) } };
}

/** Byt rakt och avvikande: the straight leg is the one that gets + (RS1). */
export function swapLegs(d: FullDrawing, node: string): FullDrawing {
  const switches = d.model.switches.map((s) => (s.node === node && s.straight && s.diverging ? { ...s, straight: s.diverging, diverging: s.straight } : s));
  return { ...d, model: { ...d.model, switches } };
}

export function setControl(d: FullDrawing, node: string, control: SwitchControl): FullDrawing {
  const switches = d.model.switches.map((s) => (s.node === node ? { ...s, control, note: control === "tkl" ? null : s.note } : s));
  return { ...d, model: { ...d.model, switches } };
}

export function renameSignal(d: FullDrawing, name: string, to: string): FullDrawing {
  const model = d.model;
  const next = to.trim();
  if (!next || next === name) return d;
  if (model.signals.some((s) => s.name === next)) throw new RitaError(`Det finns redan en signal som heter ${next}.`);
  const swap = (s: string) => (s === name ? next : s);
  const made = withPlan(
    {
      ...model,
      signals: model.signals.map((s) => (s.name === name ? { ...s, name: next } : s)),
      line_exits: model.line_exits.map((e) => ({ ...e, signals: (e.signals ?? []).map(swap) })),
      functions: model.functions.map((f) => ({ ...f, signals: (f.signals ?? []).map(swap) })),
    },
    { signals: renamedKeys(model.panel.signals, name, next) },
  );
  return { ...d, model: made };
}

export function setSignal(d: FullDrawing, name: string, change: { type?: SignalType; lamps?: number | null; planned?: boolean }): FullDrawing {
  const signals = d.model.signals.map((s) => {
    if (s.name !== name) return s;
    const type = change.type ?? s.type;
    return { ...s, ...change, type, lamps: type === "hsi" ? (change.lamps !== undefined ? change.lamps : s.lamps) : null };
  });
  return { ...d, model: { ...d.model, signals } };
}

/** The signal turned to apply the other way: its approach is the track on the other side. */
export function flipSignal(d: FullDrawing, name: string): FullDrawing {
  const model = d.model;
  const signal = model.signals.find((s) => s.name === name);
  if (!signal) return d;
  const g = geometry(model);
  const now = leaving(model, g, signal.approach, signal.node);
  let approach: string | null = null;
  let lowest = 0;
  for (const piece of g.touching.get(signal.node) ?? []) {
    if (piece === signal.approach) continue;
    const dir = leaving(model, g, piece, signal.node);
    if (dir && now && dot(dir, now) < lowest) {
      lowest = dot(dir, now);
      approach = piece;
    }
  }
  if (!approach) throw new RitaError("Det finns inget spår på andra sidan signalen.");
  const made = withPlan({ ...model, signals: model.signals.map((s) => (s === signal ? { ...s, approach: approach! } : s)) }, { signals: without(model.panel.signals, new Set([name])) });
  return { ...d, model: made };
}

export function renameExit(d: FullDrawing, id: string, to: string, neighbour?: string | null): FullDrawing {
  const model = d.model;
  const next = to.trim();
  if (!next) throw new RitaError("Linjeutfarten behöver ett id.");
  if (next !== id && model.line_exits.some((e) => e.id === next)) throw new RitaError(`Det finns redan en linjeutfart ${next}.`);
  const line_exits = model.line_exits.map((e) => (e.id === id ? { ...e, id: next, neighbour: neighbour === undefined ? e.neighbour : neighbour?.trim() || null } : e));
  return { ...d, model: withPlan({ ...model, line_exits }, { signals: renamedKeys(model.panel.signals, id, next) }) };
}

/** Bekräfta (RS7): what was assumed is confirmed by the owner, and no longer yellow. */
export function confirm(d: FullDrawing, ref: Ref): FullDrawing {
  const ok = (o: Origin | null | undefined): Origin => ({ ...(o ?? DRAWN), confirmed: true });
  const model = d.model;
  if (ref.kind === "signal") return { ...d, model: { ...model, signals: model.signals.map((s) => (s.name === ref.id ? { ...s, origin: ok(s.origin) } : s)) } };
  const node = ref.kind === "switch" ? model.switches.find((s) => s.number === ref.id)?.node : ref.id;
  return { ...d, model: { ...model, switches: model.switches.map((s) => (s.node === node ? { ...s, origin: ok(s.origin) } : s)) } };
}

/** The note on everything Studio proposed from an uploaded drawing (tkl/studio/rita.py, READ). */
export const READ = "Förslag ur en uppladdad ritning";

const fromRead = (o: Origin | null | undefined): boolean => !!o && o.note === READ && !o.confirmed;

/** How many things proposed from an uploaded drawing the owner has not confirmed: Använd
 * ritningen waits for them (TKL27). */
export function proposed(model: FullModel): number {
  return [...model.pieces, ...model.switches, ...model.signals, ...model.line_exits].filter((item) => fromRead(item.origin)).length;
}

/** Bekräfta förslaget: everything proposed from the drawing is the owner's, and no longer
 * yellow. */
export function confirmAll(d: FullDrawing): FullDrawing {
  const ok = <T extends { origin?: Origin | null }>(item: T): T => (fromRead(item.origin) ? { ...item, origin: { ...item.origin!, confirmed: true } } : item);
  const model = d.model;
  return { ...d, model: { ...model, pieces: model.pieces.map(ok), switches: model.switches.map(ok), signals: model.signals.map(ok), line_exits: model.line_exits.map(ok) } };
}

/** Yellow in Rita: what is assumed and not yet confirmed (RS5, RS7). */
export function assumed(origin: Origin | null | undefined): boolean {
  return origin?.source === "assumed" && !origin.confirmed;
}

// --- Levers: Lägg tillsammans (STUDIO-02, STUDIO-34) -------------------------------------------

/** The lever's own parts: those it names in both positions. */
export function ownParts(lever: Lever): string[] {
  return Object.keys(lever.plus).filter((p) => p in lever.minus);
}

/** Lägg tillsammans: two or more switch parts on one lever, laid together. They leave the
 * levers they were on. */
export function joinTogether(d: FullDrawing, parts: string[]): { drawing: FullDrawing; id: string } {
  const unique = [...new Set(parts)];
  if (unique.length < 2) throw new RitaError("Välj två eller flera växlar att lägga tillsammans.");
  const known = new Set(d.model.switches.flatMap(partsOf));
  const missing = unique.filter((p) => !known.has(p));
  if (missing.length) throw new RitaError(`Växel ${missing.join(", ")} finns inte.`);
  const levers = dropParts(d.model.levers, new Set(unique));
  const taken = new Set(levers.map((l) => l.id));
  let id = unique.join("/");
  for (let i = 2; taken.has(id); i++) id = `${unique.join("/")} (${i})`;
  const lever: Lever = { id, plus: Object.fromEntries(unique.map((p) => [p, "+" as Position])), minus: Object.fromEntries(unique.map((p) => [p, "-" as Position])) };
  return { drawing: { ...d, model: { ...d.model, levers: [...levers, lever] } }, id };
}

/** A part that lies reversed on its lever: - when the lever is +, and + when it is - (STUDIO-34). */
export function setReversed(d: FullDrawing, leverId: string, part: string, reversed: boolean): FullDrawing {
  const levers = d.model.levers.map((l) =>
    l.id === leverId && part in l.plus && part in l.minus ? { ...l, plus: { ...l.plus, [part]: (reversed ? "-" : "+") as Position }, minus: { ...l.minus, [part]: (reversed ? "+" : "-") as Position } } : l,
  );
  return { ...d, model: { ...d.model, levers } };
}

export function isReversed(lever: Lever, part: string): boolean {
  return lever.plus[part] === "-";
}

/** Drar med (STUDIO-34, TKL104): in one of its positions the lever drags another switch along,
 * into the position given, and not the other way. */
export function addDrag(d: FullDrawing, leverId: string, when: Position, part: string, position: Position): FullDrawing {
  const lever = d.model.levers.find((l) => l.id === leverId);
  if (!lever) throw new RitaError("Spaken finns inte.");
  if (ownParts(lever).includes(part)) throw new RitaError(`Växel ${part} ligger redan på spaken.`);
  if (!d.model.switches.flatMap(partsOf).includes(part)) throw new RitaError(`Växel ${part} finns inte.`);
  const side = when === "+" ? "plus" : "minus";
  const levers = d.model.levers.map((l) => (l === lever ? { ...l, [side]: { ...l[side], [part]: position } } : l));
  return { ...d, model: { ...d.model, levers } };
}

export function removeDrag(d: FullDrawing, leverId: string, when: Position, part: string): FullDrawing {
  const side = when === "+" ? "plus" : "minus";
  const levers = d.model.levers.map((l) => (l.id === leverId && !ownParts(l).includes(part) ? { ...l, [side]: without(l[side], new Set([part])) } : l));
  return { ...d, model: { ...d.model, levers } };
}

/** The switches a lever drags along: in which of its positions, and into which. */
export function drags(lever: Lever): { when: Position; part: string; position: Position }[] {
  const own = new Set(ownParts(lever));
  return [
    ...Object.entries(lever.plus).filter(([p]) => !own.has(p)).map(([part, position]) => ({ when: "+" as Position, part, position })),
    ...Object.entries(lever.minus).filter(([p]) => !own.has(p)).map(([part, position]) => ({ when: "-" as Position, part, position })),
  ];
}

// --- Station tracks, track circuits and exits ----------------------------------------------------

/** The run of track a piece is in, between switches, crossings and ends. */
export function runOf(model: FullModel, piece: string): string[] {
  const g = geometry(model);
  const pieces = new Map(model.pieces.map((p) => [p.id, p]));
  const stops = new Set(model.switches.map((s) => s.node));
  const seen = new Set<string>();
  const queue = [piece];
  while (queue.length) {
    const here = queue.shift()!;
    if (seen.has(here) || !pieces.has(here)) continue;
    seen.add(here);
    const p = pieces.get(here)!;
    for (const node of [p.start, p.end]) {
      const touching = g.touching.get(node) ?? [];
      if (stops.has(node) || touching.length !== 2) continue;
      for (const next of touching) if (!seen.has(next)) queue.push(next);
    }
  }
  return model.pieces.filter((p) => seen.has(p.id)).map((p) => p.id);
}

/** Stationsspår: the run of track a piece is in becomes a station track, with an id and a label
 * (TKL92). Its pieces get its number where they have none. */
export function markStationTrack(d: FullDrawing, piece: string, id?: string, label?: string): FullDrawing {
  const model = d.model;
  if (model.station_tracks.some((t) => (t.pieces ?? []).includes(piece))) throw new RitaError("Spåret är redan ett stationsspår.");
  const run = runOf(model, piece);
  const taken = new Set(model.station_tracks.map((t) => t.id));
  let made = id?.trim() || "";
  if (!made) {
    let n = 1;
    while (taken.has(String(n))) n++;
    made = String(n);
  }
  if (taken.has(made)) throw new RitaError(`Det finns redan ett stationsspår ${made}.`);
  const track: StationTrack = { id: made, label: label?.trim() || `Spår ${made}`, pieces: run, outside_id: null };
  const inRun = new Set(run);
  const pieces = model.pieces.map((p) => (inRun.has(p.id) && !p.track ? { ...p, track: made } : p));
  return { ...d, model: { ...model, pieces, station_tracks: [...model.station_tracks, track] } };
}

export function unmarkStationTrack(d: FullDrawing, id: string): FullDrawing {
  const model = d.model;
  const track = model.station_tracks.find((t) => t.id === id);
  if (!track) return d;
  const inRun = new Set(track.pieces ?? []);
  const pieces = model.pieces.map((p) => (inRun.has(p.id) && p.track === id ? { ...p, track: null } : p));
  return {
    ...d,
    model: withPlan(
      { ...model, pieces, station_tracks: model.station_tracks.filter((t) => t !== track), line_exits: model.line_exits.map((e) => ({ ...e, tracks: (e.tracks ?? []).filter((t) => t !== id) })) },
      { track_names: model.panel.track_names.filter((n) => n.name !== id) },
    ),
  };
}

export function renameStationTrack(d: FullDrawing, id: string, to: string, label: string): FullDrawing {
  const model = d.model;
  const next = to.trim();
  if (!next) throw new RitaError("Stationsspåret behöver ett id.");
  if (next !== id && model.station_tracks.some((t) => t.id === next)) throw new RitaError(`Det finns redan ett stationsspår ${next}.`);
  const track = model.station_tracks.find((t) => t.id === id);
  if (!track) return d;
  const inRun = new Set(track.pieces ?? []);
  return {
    ...d,
    model: withPlan(
      {
        ...model,
        station_tracks: model.station_tracks.map((t) => (t === track ? { ...t, id: next, label: label.trim() || `Spår ${next}` } : t)),
        pieces: model.pieces.map((p) => (inRun.has(p.id) && p.track === id ? { ...p, track: next } : p)),
        line_exits: model.line_exits.map((e) => ({ ...e, tracks: (e.tracks ?? []).map((t) => (t === id ? next : t)) })),
      },
      { track_names: model.panel.track_names.map((n) => (n.name === id ? { ...n, name: next } : n)) },
    ),
  };
}

/** A track circuit's name: the circuit TKL computed for these pieces gets it (STUDIO-19). */
export function renameCircuit(d: FullDrawing, pieces: string[], name: string): FullDrawing {
  const next = name.trim();
  if (!next) throw new RitaError("Spårledningen behöver ett namn.");
  const inside = new Set(pieces);
  const kept = d.model.track_circuits.filter((c) => !c.pieces.some((p) => inside.has(p)));
  if (kept.some((c) => c.name === next)) throw new RitaError(`Det finns redan en spårledning ${next}.`);
  const circuit: TrackCircuit = { name: next, pieces, detection: null, origin: originFor(d.model) };
  return { ...d, model: { ...d.model, track_circuits: [...kept, circuit] } };
}

// --- What Rita shows ----------------------------------------------------------------------------

const ENDS: NodeType[] = ["buffer_stop", "line_exit", "stop_point", "turntable"];

/** Where a track ends without reaching anything: the red dots (RS7). */
export function looseEnds(model: FullModel): string[] {
  const g = geometry(model);
  return model.nodes.filter((n) => {
    const count = (g.touching.get(n.id) ?? []).length;
    return count === 0 || (count === 1 && !ENDS.includes(n.type));
  }).map((n) => n.id);
}

/** Where a finding's object is, to select it: a node, a piece, or the node of a switch, a
 * signal or an exit. */
export function refOf(target: { kind: string; id: string } | null | undefined): Ref | null {
  if (!target) return null;
  const kinds: RefKind[] = ["node", "piece", "switch", "signal", "circuit", "lever", "exit"];
  return kinds.includes(target.kind as RefKind) ? { kind: target.kind as RefKind, id: target.id } : null;
}

/** The nodes and pieces a selection lights up. */
export function litBy(model: FullModel, ref: Ref | null, circuits: TrackCircuit[] = []): { nodes: Set<string>; pieces: Set<string> } {
  const nodes = new Set<string>();
  const pieces = new Set<string>();
  if (!ref) return { nodes, pieces };
  if (ref.kind === "node") nodes.add(ref.id);
  if (ref.kind === "piece") pieces.add(ref.id);
  if (ref.kind === "switch") {
    const sw = model.switches.find((s) => s.number === ref.id || partsOf(s).includes(ref.id));
    if (sw) nodes.add(sw.node);
  }
  if (ref.kind === "signal") {
    const signal = model.signals.find((s) => s.name === ref.id);
    if (signal) {
      nodes.add(signal.node);
      pieces.add(signal.approach);
    }
  }
  if (ref.kind === "exit") {
    const line = model.line_exits.find((e) => e.id === ref.id);
    if (line) nodes.add(line.node);
  }
  if (ref.kind === "circuit") for (const p of circuits.find((c) => c.name === ref.id)?.pieces ?? []) pieces.add(p);
  if (ref.kind === "lever") {
    const lever = model.levers.find((l) => l.id === ref.id);
    for (const part of lever ? Object.keys({ ...lever.plus, ...lever.minus }) : []) {
      const sw = model.switches.find((s) => partsOf(s).includes(part));
      if (sw) nodes.add(sw.node);
    }
  }
  return { nodes, pieces };
}

/** What the canvas covers, in cells: the drawing and room around it to draw more. */
export function extent(model: FullModel, g: Geometry = geometry(model)): { x: number; y: number; width: number; height: number } {
  const cells = [...g.cells.values(), ...[...g.paths.values()].flat()];
  const xs = cells.map((c) => c[0]);
  const ys = cells.map((c) => c[1]);
  const x = Math.floor(Math.min(0, ...xs)) - 1;
  const y = Math.floor(Math.min(0, ...ys)) - 1;
  const width = Math.max(36, Math.ceil(Math.max(0, ...xs)) + 6) - x;
  const height = Math.max(12, Math.ceil(Math.max(0, ...ys)) + 4) - y;
  return { x, y, width, height };
}

// --- The editor: undo and redo for the session ------------------------------------------------

export type Editor = { drawing: FullDrawing; past: FullDrawing[]; future: FullDrawing[] };
export const HISTORY = 200;

export function editor(drawing: FullDrawing): Editor {
  return { drawing, past: [], future: [] };
}

/** A change made: the one before can be undone, and what was undone is gone. */
export function changed(state: Editor, next: FullDrawing): Editor {
  if (next === state.drawing) return state;
  return { drawing: next, past: [...state.past, state.drawing].slice(-HISTORY), future: [] };
}

export function undo(state: Editor): Editor {
  const before = state.past[state.past.length - 1];
  if (!before) return state;
  return { drawing: before, past: state.past.slice(0, -1), future: [state.drawing, ...state.future] };
}

export function redo(state: Editor): Editor {
  const after = state.future[0];
  if (!after) return state;
  return { drawing: after, past: [...state.past, state.drawing], future: state.future.slice(1) };
}

/** The drawing as TKL's server takes it. */
export function toDrawing(d: FullDrawing): Drawing {
  return { model: d.model, proposal: d.proposal };
}

