// Ställverket at level 1–2 (#84): what the panel shows and how a click goes, without React. The
// panel's geometry comes from the station's Panel (the engine's layout or the plan, #83) and the
// state from the interlocking (GET /stallverk); this module puts the two together in logical
// terms (free, train route, occupied, stop, end …), and the skin (skal.ts) says how each looks.
// The interlocking is the one place where safety is decided (STV-43): a click asks it, and its
// yes or no, with the reason in Swedish, is what the page shows.
import type { FunctionAsk, FunctionShown, Interlocking, InterlockingAnswer, Panel, PanelSignal, RouteKind, Snapshot, Targets, TrainPut } from "./api";
import { Problem } from "./api";
import type { Say } from "./texter";

export type Cell = [number, number];
export type TrackState = "free" | "train" | "shunting" | "occupied" | "local" | "out_of_service" | "programming";
export type SignalType = PanelSignal["type"];
export type Target = NonNullable<Targets["targets"]>[number];
export type SetRoute = NonNullable<Interlocking["routes"]>[number];
type NumberShown = NonNullable<Interlocking["numbers"]>[number];

// --- geometry on the grid ------------------------------------------------------------------------

const distance = (a: Cell, b: Cell) => Math.hypot(a[0] - b[0], a[1] - b[1]);

export function lengthOf(cells: Cell[]): number {
  let total = 0;
  for (let i = 1; i < cells.length; i++) total += distance(cells[i - 1] as Cell, cells[i] as Cell);
  return total;
}

/** The polyline from `from` to `to` along it, in cells from its start. */
export function slice(cells: Cell[], from: number, to: number): Cell[] {
  const found: Cell[] = [];
  let walked = 0;
  for (let i = 1; i < cells.length; i++) {
    const a = cells[i - 1] as Cell;
    const b = cells[i] as Cell;
    const step = distance(a, b);
    const at = (d: number): Cell => {
      const t = step ? (d - walked) / step : 0;
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    };
    if (walked + step >= from && walked <= to) {
      if (!found.length) found.push(at(Math.max(from, walked)));
      found.push(at(Math.min(to, walked + step)));
    }
    walked += step;
  }
  return found;
}

/** The line with a gap cut at its start, its end or both: at most 45 % of it each. */
export function cut(cells: Cell[], start: number, end: number): Cell[] {
  const total = lengthOf(cells);
  return slice(cells, Math.min(start, total * 0.45), total - Math.min(end, total * 0.45));
}

/** The first `length` cells of a line from the end that touches the knot. */
export function fromKnot(cells: Cell[], knot: Cell, length: number): Cell[] {
  const first = cells[0] as Cell;
  const last = cells[cells.length - 1] as Cell;
  const way = distance(first, knot) <= distance(last, knot) ? cells : [...cells].reverse();
  return slice(way, 0, Math.min(length, lengthOf(way) * 0.5));
}

/** Where a train number stands over a piece: mid on it, above the track (as the reference
 * interlockings' train number fields). */
function above(cells: Cell[], lift: number): Cell {
  const total = lengthOf(cells);
  const half = slice(cells, 0, total / 2);
  const p = half[half.length - 1] ?? (cells[0] as Cell);
  const ahead = slice(cells, total / 2, Math.min(total, total / 2 + 0.25));
  const q = ahead[ahead.length - 1] ?? p;
  let nx = -(q[1] - p[1]);
  let ny = q[0] - p[0];
  const n = Math.hypot(nx, ny);
  if (!n) return [p[0], p[1] - lift];
  nx /= n;
  ny /= n;
  if (ny > 0 || (ny === 0 && nx > 0)) {
    nx = -nx;
    ny = -ny;
  }
  return [p[0] + nx * lift, p[1] + ny * lift];
}

// --- the state, with its defaults ----------------------------------------------------------------

export type Filled = Required<Pick<Interlocking, "switches" | "levers" | "routes" | "trains" | "signals" | "pieces" | "numbers" | "exits" | "tracks" | "events" | "functions" | "sections">> & Interlocking;

/** The interlocking's state with every list and map there: the server always sends them. */
export function filled(state: Interlocking): Filled {
  return {
    ...state,
    switches: state.switches ?? {},
    levers: state.levers ?? {},
    routes: state.routes ?? [],
    trains: state.trains ?? [],
    signals: state.signals ?? {},
    pieces: state.pieces ?? {},
    numbers: state.numbers ?? [],
    exits: state.exits ?? [],
    tracks: state.tracks ?? {},
    events: state.events ?? [],
    functions: state.functions ?? [],
    sections: state.sections ?? {},
  };
}

// --- the drawing in logical terms ----------------------------------------------------------------

export type DrawnLine = { piece: string; cells: Cell[]; state: TrackState; route: number | null; line: boolean; cut: { start: boolean; end: boolean } };
export type DrawnSwitch = {
  number: string;
  /** The switch parts in the interlocking: one, or a slip's two. */
  parts: string[];
  cell: Cell;
  label: Cell;
  position: "+" | "-" | null;
  laid: boolean;
  routes: number[];
  protection: boolean;
  /** Freed for the people on the place: laid with the module's button (TKL44, FR41). */
  local: boolean;
  /** The pieces in the leg it lies in and its trunk, for the short yellow (STV-20). */
  lies: Cell[] | null;
  trunk: Cell[] | null;
  /** The pieces in the leg it does not lie in, for model 59's dark lens. */
  other: Cell[] | null;
};
export type Aspect = "stop" | "proceed" | "shunt" | "local";
export type DrawnSignal = {
  name: string;
  type: SignalType;
  symbol: Cell;
  toward: Cell;
  label: Cell;
  side: "over" | "under";
  planned: boolean;
  aspect: Aspect;
  end: boolean;
  /** Blocked at stop: in a signal stop, or an entry signal to a locally released area. */
  blocked: boolean;
  /** A set route starts or ends here: model 59's toggle is folded in the train's direction. */
  folded: boolean;
};
export type DrawnBuffer = { id: string; cell: Cell; toward: Cell; end: boolean };
export type DrawnPoint = { name: string; cell: Cell };
/** A train number: centred at `at`, or for a train on the line beside its exit's name, which
 * then stands at `at` with `after` characters, on the side `anchor` says. */
export type DrawnNumber = {
  key: string;
  train: number;
  number: string | null;
  colour: "red" | "green";
  at: Cell;
  anchor: "middle" | "start" | "end";
  after: number;
  estimated: boolean;
  route: number | null;
};
export type DrawnName = { name: string; cell: Cell; hidden: boolean };
export type DrawnLabel = { text: string; kind: "exit" | "point"; cell: Cell; anchor: "start" | "middle" | "end"; end: boolean };
/** A panel function's button in the track plan, beside its node (STV-53). */
export type DrawnButton = { name: string; type: FunctionShown["type"]; cell: Cell; side: "over" | "under"; on: boolean; mode: string | null };
/** Model 59's arrow in the track at a set route's start or end, in the train's direction. */
export type DrawnArrow = { route: number; kind: RouteKind; at: Cell; toward: Cell };
/** Model 59's white lamp in a track circuit, lit while it is free (SJH s. 152). */
export type DrawnLamp = { section: string; at: Cell; free: boolean };
/** Where two track circuits meet in a track: model 59 breaks the line there (SJH s. 152). */
export type DrawnBoundary = { at: Cell; toward: Cell };
/** A track at the turntable: a click on it turns the bridge to it, through the turntable's
 * function (STV-04). Its line on the grid and in the real shape, from the turntable outwards. */
export type TableTrack = { piece: string; label: string; cells: Cell[]; real: Cell[] };
/** The turntable (RS4): the pit as a circle and the bridge as a line at its angle. The bridge
 * points at `piece`, the track the interlocking says; until it has been turned it is not known,
 * and the bridge is drawn towards the first track, dashed. A set route over it holds it. */
export type DrawnTable = {
  id: string;
  cell: Cell;
  /** The pit's radius, in cells across. */
  radius: number;
  real: Cell | null;
  realRadius: number | null;
  piece: string | null;
  known: boolean;
  /** The bridge's direction, a unit vector on the panel (in its pixels) and in the real shape. */
  toward: Cell;
  realToward: Cell | null;
  held: RouteKind | null;
  /** The turntable's function, which turns it; none, and it cannot be turned from the panel. */
  function: string | null;
  tracks: TableTrack[];
};
export type Drawing = {
  lines: DrawnLine[];
  switches: DrawnSwitch[];
  signals: DrawnSignal[];
  buffers: DrawnBuffer[];
  points: DrawnPoint[];
  numbers: DrawnNumber[];
  names: DrawnName[];
  labels: DrawnLabel[];
  buttons: DrawnButton[];
  arrows: DrawnArrow[];
  lamps: DrawnLamp[];
  boundaries: DrawnBoundary[];
  tables: DrawnTable[];
};

/** The exits whose line has a train on it in the hub's picture (STV-54): the piece outside the
 * entry signal belongs to the line and shows its state. */
export function busyLines(state: Filled, snapshot: Snapshot | null): Set<string> {
  const busy = new Set<string>();
  if (!snapshot) return busy;
  for (const exit of state.exits) {
    if (snapshot.sections.some((s) => s.exit === exit.outside && s.occupied)) busy.add(exit.exit);
  }
  return busy;
}

/** Everything the panel draws, from the panel's geometry, the interlocking's state, the hub's
 * picture of the lines and the route ends a click can choose. */
export function drawing(panel: Panel, state: Filled, lines: Set<string>, ends: Set<string>): Drawing {
  const cuts = new Map<string, { start: boolean; end: boolean }>();
  // The leg a switch does not lie in, and its trunk: occupied is red in the leg that lies only
  // (TDOK 2014:0693 s. 22), though the interlocking says the whole section.
  const offLegs = new Map<string, string>();
  const byPiece = new Map(panel.lines.map((line) => [line.piece, line]));
  const switches: DrawnSwitch[] = [];
  for (const s of panel.switches ?? []) {
    const parts = s.number in state.switches ? [s.number] : s.number.split("/").filter((p) => p in state.switches);
    const shown = parts.length ? state.switches[parts[0] as string] : undefined;
    const position = shown?.position ?? null;
    let lies: Cell[] | null = null;
    let trunk: Cell[] | null = null;
    let other: Cell[] | null = null;
    if (position && s.trunk && s.straight && s.diverging) {
      const off = byPiece.get(position === "+" ? s.diverging : s.straight);
      if (off) {
        const atStart = distance(off.cells[0] as Cell, s.cell) <= distance(off.cells[off.cells.length - 1] as Cell, s.cell);
        const was = cuts.get(off.piece) ?? { start: false, end: false };
        cuts.set(off.piece, atStart ? { ...was, start: true } : { ...was, end: true });
        offLegs.set(off.piece, s.trunk);
        other = off.cells;
      }
      lies = byPiece.get(position === "+" ? s.straight : s.diverging)?.cells ?? null;
      trunk = byPiece.get(s.trunk)?.cells ?? null;
    }
    switches.push({
      number: s.number,
      parts,
      cell: s.cell,
      label: s.label,
      position,
      laid: (s.laid ?? true) && (shown?.control ?? "tkl") === "tkl",
      routes: [...new Set(parts.flatMap((p) => state.switches[p]?.routes ?? []))],
      protection: parts.some((p) => state.switches[p]?.protection),
      local: parts.some((p) => state.switches[p]?.local),
      lies,
      trunk,
      other,
    });
  }
  const outside = new Map(state.exits.flatMap((exit) => (exit.pieces ?? []).map((piece) => [piece, exit.exit] as const)));
  const drawnLines: DrawnLine[] = panel.lines.map((line) => {
    const shown = state.pieces[line.piece];
    const exit = outside.get(line.piece);
    let found: TrackState = shown?.state ?? "free";
    if (exit !== undefined && found !== "occupied") found = lines.has(exit) ? "occupied" : "free";
    const trunk = offLegs.get(line.piece);
    if (found === "occupied" && trunk !== undefined && state.pieces[trunk]?.state === "occupied") found = "free";
    return { piece: line.piece, cells: line.cells, state: found, route: exit === undefined ? (shown?.route ?? null) : null, line: exit !== undefined, cut: cuts.get(line.piece) ?? { start: false, end: false } };
  });
  const routeEnds = new Set(state.routes.map((r) => r.end));
  const folded = new Set(state.routes.flatMap((r) => [r.start, r.end]));
  const signals: DrawnSignal[] = (panel.signals ?? []).map((s) => {
    const shown = state.signals[s.name];
    return {
      name: s.name,
      type: s.type,
      symbol: s.symbol,
      toward: s.toward,
      label: s.label,
      side: s.side,
      planned: s.planned ?? false,
      aspect: shown?.aspect ?? "stop",
      end: shown?.end ?? false,
      blocked: shown?.blocked ?? false,
      folded: folded.has(s.name),
    };
  });
  const signalNames = new Set(signals.map((s) => s.name));
  const buffers: DrawnBuffer[] = [];
  const points: DrawnPoint[] = [];
  for (const node of panel.nodes) {
    if (node.type === "buffer_stop") {
      const line = panel.lines.find((l) => sameCell(l.cells[0], node.cell) || sameCell(l.cells[l.cells.length - 1], node.cell));
      let toward: Cell = [1, 0];
      if (line) {
        const way = sameCell(line.cells[line.cells.length - 1], node.cell) ? line.cells : [...line.cells].reverse();
        const a = way[way.length - 2] as Cell;
        const b = way[way.length - 1] as Cell;
        const n = distance(a, b) || 1;
        toward = [(b[0] - a[0]) / n, (b[1] - a[1]) / n];
      }
      buffers.push({ id: node.id, cell: node.cell, toward, end: routeEnds.has(node.id) });
    }
    if (ends.has(node.id) && !signalNames.has(node.id)) points.push({ name: node.id, cell: node.cell });
  }
  const names: DrawnName[] = (panel.track_names ?? []).map((t) => ({ name: t.name, cell: t.cell, hidden: false }));
  const numbers: DrawnNumber[] = [];
  for (const n of state.numbers) {
    const spot = numberSpot(panel, n, names);
    if (spot) numbers.push({ key: `${n.train}-${n.colour}`, train: n.train, number: n.number, colour: n.colour, ...spot, estimated: n.estimated, route: n.route });
  }
  const labels: DrawnLabel[] = (panel.labels ?? []).map((l) => ({ text: l.text, kind: l.kind, cell: l.cell, anchor: l.anchor ?? "middle", end: l.kind === "point" && routeEnds.has(l.text) }));
  const shownFunctions = new Map(state.functions.map((f) => [f.name, f]));
  const buttons: DrawnButton[] = (panel.functions ?? []).map((b) => {
    const f = shownFunctions.get(b.name);
    return { name: b.name, type: b.type, cell: b.cell, side: b.side, on: f?.on ?? false, mode: f?.mode ?? null };
  });
  return { lines: drawnLines, switches, signals, buffers, points, numbers, names, labels, buttons, arrows: arrows(panel, state), ...lamps(drawnLines, state), tables: tables(panel, state) };
}

/** A line's way out from a centre: its points from the end nearest the centre. */
function outwards(cells: Cell[], centre: Cell, scale: Cell = [1, 1]): Cell[] {
  const far = (c: Cell) => Math.hypot((c[0] - centre[0]) * scale[0], (c[1] - centre[1]) * scale[1]);
  return far(cells[0] as Cell) <= far(cells[cells.length - 1] as Cell) ? cells : [...cells].reverse();
}

/** The way a track at the turntable leaves it: the direction of its first stretch from the end
 * nearest the centre, which is the angle of the track in the model (TurntableTrack.angle). A
 * unit vector after `scale`, the cell's size in pixels on the panel. */
function directionOf(cells: Cell[], centre: Cell, scale: Cell = [1, 1]): Cell | null {
  const way = outwards(cells, centre, scale);
  const size = (v: Cell) => Math.hypot(v[0] * scale[0], v[1] * scale[1]);
  const first = way[0] as Cell;
  for (const point of way.slice(1)) {
    const v: Cell = [point[0] - first[0], point[1] - first[1]];
    const n = size(v);
    if (n > 1e-6) return [(v[0] * scale[0]) / n, (v[1] * scale[1]) / n];
  }
  return null;
}

/** A direction as the model gives a turntable track's angle: degrees counter-clockwise from
 * east, 0 to 360, to a tenth. */
export function angleOf(v: Cell): number {
  const a = (Math.atan2(-v[1], v[0]) * 180) / Math.PI;
  return Math.round(((a + 360) % 360) * 10) / 10 || 0;
}

/** The turntables, with the bridge where the interlocking says (STV-04, RS4). */
export function tables(panel: Panel, state: Filled): DrawnTable[] {
  const byPiece = new Map(panel.lines.map((line) => [line.piece, line]));
  const scale = panel.cell as Cell;
  return (panel.tables ?? []).map((t) => {
    const fn = state.functions.find((f) => f.type === "turntable" && (f.at === t.id || f.at === t.node)) ?? null;
    const tracks: TableTrack[] = [];
    for (const mode of fn?.modes ?? []) {
      const line = byPiece.get(mode.value);
      if (!line) continue;
      tracks.push({ piece: mode.value, label: mode.label, cells: outwards(line.cells, t.cell, scale), real: t.real && (line.real ?? []).length > 1 ? outwards(line.real ?? [], t.real) : [] });
    }
    const piece = state.turntables?.[t.id] ?? null;
    const pointing = tracks.find((k) => k.piece === piece) ?? tracks[0] ?? null;
    const toward = (pointing && directionOf(pointing.cells, t.cell, scale)) ?? [1, 0];
    const realToward = pointing && t.real && pointing.real.length ? directionOf(pointing.real, t.real) : null;
    const pieces = new Set(tracks.map((k) => k.piece));
    const held = state.routes.find((r) => r.turntable && pieces.has(r.turntable))?.kind ?? null;
    return {
      id: t.id,
      cell: t.cell,
      radius: t.radius,
      real: t.real ?? null,
      realRadius: t.real_radius ?? null,
      piece,
      known: piece !== null && pointing?.piece === piece,
      toward,
      realToward,
      held,
      function: fn?.name ?? null,
      tracks,
    };
  });
}

/** Model 59's track circuit lamps, one to four per track circuit on its longest piece, by its
 * length, and the breaks where two track circuits meet in a track. */
export function lamps(lines: DrawnLine[], state: Filled, spacing = 5): { lamps: DrawnLamp[]; boundaries: DrawnBoundary[] } {
  const byPiece = new Map(lines.map((l) => [l.piece, l]));
  const sectionOf = new Map(Object.entries(state.sections).flatMap(([section, pieces]) => pieces.map((p) => [p, section] as const)));
  const found: DrawnLamp[] = [];
  for (const [section, pieces] of Object.entries(state.sections)) {
    const drawn = pieces.map((p) => byPiece.get(p)).filter((l): l is DrawnLine => !!l);
    if (!drawn.length) continue;
    const longest = drawn.reduce((best, l) => (lengthOf(l.cells) > lengthOf(best.cells) ? l : best));
    const length = lengthOf(longest.cells);
    const total = drawn.reduce((sum, l) => sum + lengthOf(l.cells), 0);
    const n = Math.max(1, Math.min(4, Math.round(total / spacing), Math.floor(length / 1.2)));
    const free = !drawn.some((l) => l.state === "occupied");
    for (let i = 0; i < n; i++) {
      const here = slice(longest.cells, 0, (length * (i + 0.5)) / n);
      found.push({ section, at: here[here.length - 1] as Cell, free });
    }
  }
  const ends = new Map<string, { line: DrawnLine; toward: Cell }[]>();
  for (const l of lines) {
    for (const [a, b] of [
      [l.cells[0], l.cells[1]],
      [l.cells[l.cells.length - 1], l.cells[l.cells.length - 2]],
    ] as [Cell, Cell][]) {
      const key = `${a[0].toFixed(3)},${a[1].toFixed(3)}`;
      const n = distance(a, b) || 1;
      ends.set(key, [...(ends.get(key) ?? []), { line: l, toward: [(b[0] - a[0]) / n, (b[1] - a[1]) / n] }]);
    }
  }
  const boundaries: DrawnBoundary[] = [];
  for (const [key, meeting] of ends) {
    if (meeting.length !== 2) continue;
    const [first, second] = meeting as [{ line: DrawnLine; toward: Cell }, { line: DrawnLine; toward: Cell }];
    const a = sectionOf.get(first.line.piece);
    const b = sectionOf.get(second.line.piece);
    if (!a || !b || a === b) continue;
    const [x, y] = key.split(",").map(Number) as [number, number];
    boundaries.push({ at: [x, y], toward: first.toward });
  }
  return { lamps: found, boundaries };
}

/** Model 59's arrows (SJH s. 157): in the track near the route's start and its end, in the
 * train's direction, for every set route. The route's pieces are walked in order, each turned
 * so that it goes on into the next. */
export function arrows(panel: Panel, state: Filled, inset = 0.62): DrawnArrow[] {
  const byPiece = new Map(panel.lines.map((line) => [line.piece, line.cells]));
  const found: DrawnArrow[] = [];
  for (const route of state.routes) {
    const pieces = route.sections.flatMap((s) => s.pieces).filter((p) => byPiece.has(p));
    if (!pieces.length) continue;
    const path: Cell[] = [];
    pieces.forEach((piece, i) => {
      let cells = byPiece.get(piece) as Cell[];
      const next = byPiece.get(pieces[i + 1] ?? "");
      if (next) {
        const end = cells[cells.length - 1] as Cell;
        if (!sameCell(next[0], end) && !sameCell(next[next.length - 1], end)) cells = [...cells].reverse();
      } else if (path.length) {
        if (!sameCell(cells[0], path[path.length - 1] as Cell)) cells = [...cells].reverse();
      } else {
        const start = panel.signals?.find((s) => s.name === route.start);
        const [a, b] = [cells[0] as Cell, cells[cells.length - 1] as Cell];
        if (start && (b[0] - a[0]) * start.toward[0] + (b[1] - a[1]) * start.toward[1] < 0) cells = [...cells].reverse();
      }
      path.push(...(path.length ? cells.slice(1) : cells));
    });
    const total = lengthOf(path);
    const at = (d: number): [Cell, Cell] => {
      const here = slice(path, 0, d);
      const p = here[here.length - 1] ?? (path[0] as Cell);
      const ahead = slice(path, d, Math.min(total, d + 0.1));
      const q = ahead[ahead.length - 1] ?? p;
      const n = distance(p, q) || 1;
      return [p, [(q[0] - p[0]) / n, (q[1] - p[1]) / n]];
    };
    const d = Math.min(inset, total / 3);
    for (const where of [d, total - d - 0.1]) {
      const [p, toward] = at(where);
      found.push({ route: route.id, kind: route.kind, at: p, toward });
    }
  }
  return found;
}

const sameCell = (a: Cell | undefined, b: Cell) => !!a && Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6;

type Spot = { at: Cell; anchor: DrawnNumber["anchor"]; after: number };

/** Where a number stands: in its station track's train number field, whose name is then hidden
 * (STV-57); beside the exit's name for a train on the line (STV-02: on its way here it stands on
 * the line outside the entry signal); else over the longest piece of its section, one field per
 * section (STV-06). */
function numberSpot(panel: Panel, shown: NumberShown, names: DrawnName[]): Spot | null {
  const track = shown.track ? (panel.track_names ?? []).find((t) => t.name === shown.track) : undefined;
  if (track) {
    for (const name of names) if (name.name === track.name) name.hidden = true;
    return { at: [track.train_number[0] + 1.5, track.train_number[1] + 0.55], anchor: "middle", after: 0 };
  }
  const label = shown.exit ? (panel.labels ?? []).find((l) => l.kind === "exit" && l.text === shown.exit) : undefined;
  if (label && label.anchor !== "middle") return { at: label.cell, anchor: label.anchor ?? "start", after: label.text.length };
  const wanted = new Set(shown.pieces ?? []);
  const lines = panel.lines.filter((line) => wanted.has(line.piece));
  if (!lines.length) return null;
  const longest = lines.reduce((best, line) => (lengthOf(line.cells) > lengthOf(best.cells) ? line : best));
  return { at: above(longest.cells, 0.7), anchor: "middle", after: 0 };
}

/** The route ends a click can choose: every start and goal the engine found. */
export function routeEnds(routes: { start: string; end: string }[]): Set<string> {
  return new Set(routes.flatMap((r) => [r.start, r.end]));
}

/** A route's name as the interlocking says it. */
export const routeName = (route: Pick<SetRoute, "start" | "end">) => `${route.start} → ${route.end}`;

// --- the click flow (STV-01, STV-03, STV-24) -----------------------------------------------------

export type Calls = {
  targets: (start: string) => Promise<Targets>;
  setRoute: (start: string, end: string, kind: RouteKind | null) => Promise<InterlockingAnswer>;
  release: (route: number) => Promise<InterlockingAnswer>;
  emergencyRelease: (route: number, confirm: boolean) => Promise<InterlockingAnswer>;
  layLever: (sw: string) => Promise<InterlockingAnswer>;
  step: (route: number) => Promise<InterlockingAnswer>;
  arrive: (route: number) => Promise<InterlockingAnswer>;
  depart: (route: number) => Promise<InterlockingAnswer>;
  putTrain: (put: TrainPut) => Promise<InterlockingAnswer>;
  removeTrain: (train: number) => Promise<InterlockingAnswer>;
  panelFunction: (ask: FunctionAsk) => Promise<InterlockingAnswer>;
};

/** The start chosen and the goals from it, of the kind the next click sets. */
export type Choice = { start: string; kind: RouteKind; kinds: RouteKind[]; targets: Target[] };
/** What the interlocking said last: yes, or no with its reason. */
export type Said = { text: string; ok: boolean; at: string };
/** The panel's choice: a start being chosen, the route chosen for the buttons, an emergency
 * release waiting for its confirmation, and what was said last. */
export type Valet = { choice: Choice | null; route: number | null; confirm: number | null; said: Said | null };
export type Done = { valet: Valet; state?: Interlocking; refused?: Said };
export type Act = "step" | "arrive" | "depart" | "release";

export const NOTHING: Valet = { choice: null, route: null, confirm: null, said: null };

const said = (text: string, ok: boolean, now: () => Date): Said => ({ text, ok, at: now().toISOString() });

function heard(error: unknown): string {
  return error instanceof Problem ? error.message : error instanceof Error ? error.message : "Något gick fel.";
}

/** An answer from the interlocking: the new state, and its words as yes or no. */
function answered(valet: Valet, answer: InterlockingAnswer, now: () => Date, route: number | null): Done {
  const told = said(answer.message, answer.accepted, now);
  return { valet: { ...valet, said: told, route }, state: answer.state, refused: answer.accepted ? undefined : told };
}

/** The route the train in `old` goes on in, when `old` is gone: the next set route it took. */
function follow(old: number | null, before: SetRoute[], state: Interlocking): number | null {
  if (old === null) return null;
  const routes = state.routes ?? [];
  if (routes.some((r) => r.id === old)) return old;
  const train = before.find((r) => r.id === old)?.train ?? null;
  return train === null ? null : (routes.find((r) => r.train === train)?.id ?? null);
}

/** A click on a signal or another route end: choose it as the start, toggle the kind with a
 * second click (STV-24), or set the route to it as the goal (STV-01, STV-03). */
export async function clickPoint(valet: Valet, name: string, calls: Calls, say: Say, now: () => Date = () => new Date()): Promise<Done> {
  const choice = valet.choice;
  if (choice && choice.start === name) {
    if (choice.kind === "train" && choice.kinds.includes("shunting")) return { valet: { ...valet, choice: { ...choice, kind: "shunting" } } };
    return { valet: { ...valet, choice: null } };
  }
  if (choice) {
    try {
      const answer = await calls.setRoute(choice.start, name, choice.kind);
      return answered({ ...valet, choice: null, confirm: null }, answer, now, answer.accepted ? (answer.route ?? valet.route) : valet.route);
    } catch (error) {
      const told = said(heard(error), false, now);
      return { valet: { ...valet, choice: null, said: told }, refused: told };
    }
  }
  try {
    const found = await calls.targets(name);
    const kinds = found.kinds ?? [];
    if (!kinds.length) {
      const told = said(say("noTargets", { start: name }), false, now);
      return { valet: { ...valet, choice: null, said: told }, refused: told };
    }
    const kind = kinds[0] as RouteKind;
    return { valet: { ...valet, choice: { start: name, kind, kinds, targets: found.targets ?? [] }, confirm: null } };
  } catch (error) {
    const told = said(heard(error), false, now);
    return { valet: { ...valet, choice: null, said: told }, refused: told };
  }
}

/** Esc: the choice of a start is cancelled, and so is a waiting confirmation. */
export function escape(valet: Valet): Valet {
  return { ...valet, choice: null, confirm: null };
}

/** A click on a switch lays its whole lever (STV-01, STV-52). */
export async function clickSwitch(valet: Valet, part: string, calls: Calls, now: () => Date = () => new Date()): Promise<Done> {
  try {
    return answered({ ...valet, choice: null }, await calls.layLever(part), now, valet.route);
  } catch (error) {
    const told = said(heard(error), false, now);
    return { valet: { ...valet, said: told }, refused: told };
  }
}

/** Kör, Ankommit, Avgått and Lös ut on the chosen route (STV-01, STV-06, STV-16). */
export async function act(valet: Valet, what: Act, routes: SetRoute[], calls: Calls, now: () => Date = () => new Date()): Promise<Done> {
  const route = valet.route;
  if (route === null) return { valet };
  const call = { step: calls.step, arrive: calls.arrive, depart: calls.depart, release: calls.release }[what];
  try {
    const answer = await call(route);
    return answered({ ...valet, choice: null, confirm: null }, answer, now, follow(route, routes, answer.state));
  } catch (error) {
    const told = said(heard(error), false, now);
    return { valet: { ...valet, said: told }, refused: told };
  }
}

/** Nödutlös: the first press asks for the confirmation, the second releases (STV-01). */
export async function emergency(valet: Valet, confirmed: boolean, calls: Calls, now: () => Date = () => new Date()): Promise<Done> {
  const route = valet.route;
  if (route === null) return { valet };
  if (!confirmed) return { valet: { ...valet, confirm: route } };
  try {
    const answer = await calls.emergencyRelease(route, true);
    return answered({ ...valet, confirm: null }, answer, now, (answer.state.routes ?? []).some((r) => r.id === route) ? route : null);
  } catch (error) {
    const told = said(heard(error), false, now);
    return { valet: { ...valet, confirm: null, said: told }, refused: told };
  }
}

/** Put a train number, or take one away (STV-10, STV-15). */
export async function trainCall(valet: Valet, work: () => Promise<InterlockingAnswer>, now: () => Date = () => new Date()): Promise<Done> {
  try {
    return answered(valet, await work(), now, valet.route);
  } catch (error) {
    const told = said(heard(error), false, now);
    return { valet: { ...valet, said: told }, refused: told };
  }
}

/** Model 59's toggle at a signal (STV-36): flipped at the start and then at the goal, the same
 * choice as a click (STV-01, STV-24); flipped back at the start of a set route, it releases the
 * route. Every flip asks the interlocking's same operations. */
export async function clickToggle(valet: Valet, name: string, routes: SetRoute[], calls: Calls, say: Say, now: () => Date = () => new Date()): Promise<Done> {
  const set = routes.find((r) => r.start === name);
  if (!valet.choice && set) {
    try {
      const answer = await calls.release(set.id);
      return answered({ ...valet, confirm: null }, answer, now, valet.route === set.id && answer.accepted ? null : valet.route);
    } catch (error) {
      const told = said(heard(error), false, now);
      return { valet: { ...valet, said: told }, refused: told };
    }
  }
  return clickPoint(valet, name, calls, say, now);
}

/** A panel function from the catalogue (STV-04, STV-53): switched on or off, a mode chosen, a
 * local switch laid with the module's button, or an emergency release confirmed. */
export async function functionCall(valet: Valet, ask: FunctionAsk, calls: Calls, now: () => Date = () => new Date()): Promise<Done> {
  try {
    return answered({ ...valet, choice: null }, await calls.panelFunction(ask), now, valet.route);
  } catch (error) {
    const told = said(heard(error), false, now);
    return { valet: { ...valet, said: told }, refused: told };
  }
}

/** What the page says under the panel about the choice in progress. */
export function guidance(valet: Valet, say: Say, toggles = false): string {
  const choice = valet.choice;
  if (!choice) return say(toggles ? "chooseStart59" : "chooseStart");
  if (choice.kind === "shunting") return say("chooseShunting", { start: choice.start });
  if (toggles && choice.kinds.includes("shunting")) return say("chooseTrain59", { start: choice.start });
  return say(choice.kinds.includes("shunting") ? "chooseTrain" : "chooseTrainOnly", { start: choice.start });
}

/** The goals of the chosen kind, to light up on the panel. */
export function goals(choice: Choice | null): Target[] {
  return choice ? choice.targets.filter((t) => t.kind === choice.kind) : [];
}

