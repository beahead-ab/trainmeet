// The module's geometry in the web app, the same maths as cad/geometry.py and cad/graph.py: the
// curve from the string and the sagitta, the lines of a curve, and a preview of the track graph
// while the measures are typed. Coordinates are the module's own, as the station model's: x from
// gable A along Kant 1, y away from Kant 1, in mm, y down the drawing.
import type { Shape } from "./api";

export type Point = [number, number];
export type Bend = { radius: number; angle: number };
export type Line = { kind: "line"; start: Point; end: Point };
export type Arc = { kind: "arc"; start: Point; end: Point; center: Point; radius: number; clockwise: boolean };
export type Seg = Line | Arc;

/** Track 1's radius and angle from the string (chord) and its sagitta: R = (c² + 4s²) / 8s, kept
 * exactly as computed (CAD16, CAD-35). */
export function fromChord(chord: number, sagitta: number): Bend | null {
  if (!(chord > 0) || !(sagitta > 0) || sagitta >= chord / 2) return null;
  const radius = (chord * chord + 4 * sagitta * sagitta) / (8 * sagitta);
  const angle = (2 * Math.asin(Math.min(1, chord / (2 * radius))) * 180) / Math.PI;
  return { radius, angle };
}

/** The string and sagitta of an arc: the other way. */
export function toChord(radius: number, angle: number): { chord: number; sagitta: number } {
  const half = ((angle * Math.PI) / 180) / 2;
  return { chord: 2 * radius * Math.sin(half), sagitta: radius * (1 - Math.cos(half)) };
}

export function arcLength(radius: number, angle: number): number {
  return (radius * angle * Math.PI) / 180;
}

type CurveShape = { radius: number; angle: number; width: number; edge?: string };

function outer(curve: CurveShape): boolean {
  return (curve.edge ?? "outer") === "outer";
}

/** Kant 1's radius, from track 1's radius and its distance from Kant 1. */
export function edgeRadius(curve: CurveShape, track1: number): number {
  return outer(curve) ? curve.radius + track1 : curve.radius - track1;
}

/** The radius of the line offset mm from Kant 1. */
export function lineRadius(curve: CurveShape, track1: number, offset: number): number {
  const edge = edgeRadius(curve, track1);
  return outer(curve) ? edge - offset : edge + offset;
}

export function centre(curve: CurveShape, track1: number): Point {
  const edge = edgeRadius(curve, track1);
  return outer(curve) ? [0, edge] : [0, -edge];
}

/** The point offset mm from Kant 1, angle degrees from gable A. */
export function pointOn(curve: CurveShape, track1: number, offset: number, angle: number): Point {
  const [cx, cy] = centre(curve, track1);
  const r = lineRadius(curve, track1, offset);
  const phi = (angle * Math.PI) / 180;
  return outer(curve) ? [cx + r * Math.sin(phi), cy - r * Math.cos(phi)] : [cx + r * Math.sin(phi), cy + r * Math.cos(phi)];
}

function same(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((x, i) => Math.abs(x - (b[i] ?? NaN)) <= 0.5);
}

export type Preview = { pieces: Seg[]; ends: { gable: "A" | "B"; at: Point }[]; complete: boolean };

/** The track graph a module from measures gets, as cad/graph.py makes it: one track per gable
 * track when both gables agree, else only the ends at the gables. */
export function preview(shape: Shape, a: number[], b: number[]): Preview {
  const track1 = a[0] ?? 0;
  const at = (gable: "A" | "B", offset: number): Point => {
    if (shape.kind === "curve") return pointOn(shape, track1, offset, gable === "A" ? 0 : shape.angle);
    const shift = shape.kind === "trapezoid" && gable === "B" ? (shape.offset ?? 0) : 0;
    return [gable === "A" ? 0 : shape.length, shift + offset];
  };
  const ends = [
    ...a.map((offset) => ({ gable: "A" as const, at: at("A", offset) })),
    ...b.map((offset) => ({ gable: "B" as const, at: at("B", offset) })),
  ];
  const through = same(a, b);
  const pieces: Seg[] = through
    ? a.map((offset) =>
        shape.kind === "curve"
          ? {
              kind: "arc",
              start: at("A", offset),
              end: at("B", offset),
              center: centre(shape, track1),
              radius: lineRadius(shape, track1, offset),
              clockwise: outer(shape),
            }
          : { kind: "line", start: at("A", offset), end: at("B", offset) },
      )
    : [];
  return { pieces, ends, complete: through || (a.length === 0 && b.length === 0) };
}

/** A length for people: 1 500 mm, 10,1 m. */
export function mm(value: number): string {
  return `${Math.round(value).toLocaleString("sv-SE")} mm`;
}

export function metres(value: number): string {
  return `${(value / 1000).toLocaleString("sv-SE", { maximumFractionDigits: 1 })} m`;
}

// --- Ritningen (#89 del b): the gables as lines, distances along the module, and the segments.

/** A gable as a line: its corner at Kant 1, the direction along it from Kant 1, the direction into
 * the module, and its width; as cad/geometry.py's GableLine. */
export type GableLine = { corner: Point; along: Point; inward: Point; width: number };

export function gableLine(shape: Shape, track1: number, end: "A" | "B"): GableLine {
  const width = shape.kind === "trapezoid" ? (end === "A" ? shape.width_a : shape.width_b) : shape.width;
  if (shape.kind === "curve") {
    const angle = end === "A" ? 0 : shape.angle;
    const corner = pointOn(shape, track1, 0, angle);
    const far = pointOn(shape, track1, 1, angle);
    const phi = (angle * Math.PI) / 180;
    const tangent: Point = outer(shape) ? [Math.cos(phi), Math.sin(phi)] : [Math.cos(phi), -Math.sin(phi)];
    return { corner, along: [far[0] - corner[0], far[1] - corner[1]], inward: end === "A" ? tangent : [-tangent[0], -tangent[1]], width };
  }
  if (end === "A") return { corner: [0, 0], along: [0, 1], inward: [1, 0], width };
  const shift = shape.kind === "trapezoid" ? (shape.offset ?? 0) : 0;
  return { corner: [shape.length, shift], along: [0, 1], inward: [-1, 0], width };
}

export function onGable(line: GableLine, offset: number): Point {
  return [line.corner[0] + line.along[0] * offset, line.corner[1] + line.along[1] * offset];
}

export function gableOffset(line: GableLine, p: Point): number {
  return (p[0] - line.corner[0]) * line.along[0] + (p[1] - line.corner[1]) * line.along[1];
}

export function gableDepth(line: GableLine, p: Point): number {
  return (p[0] - line.corner[0]) * line.inward[0] + (p[1] - line.corner[1]) * line.inward[1];
}

/** How far p lies from gable A along the module: x, or on a curve the arc at p's own radius. */
export function fromA(shape: Shape, track1: number, p: Point): number {
  if (shape.kind !== "curve") return p[0];
  const [cx, cy] = centre(shape, track1);
  const r = Math.hypot(p[0] - cx, p[1] - cy);
  const polar = Math.atan2(p[1] - cy, p[0] - cx);
  return r * (outer(shape) ? polar + Math.PI / 2 : Math.PI / 2 - polar);
}

function sweepOf(arc: Arc): number {
  const a0 = Math.atan2(arc.start[1] - arc.center[1], arc.start[0] - arc.center[0]);
  const a1 = Math.atan2(arc.end[1] - arc.center[1], arc.end[0] - arc.center[0]);
  const turn = arc.clockwise ? a1 - a0 : a0 - a1;
  const found = ((turn % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  return found > 1e-9 ? found : 2 * Math.PI;
}

export function segLength(seg: Seg): number {
  return seg.kind === "line" ? Math.hypot(seg.end[0] - seg.start[0], seg.end[1] - seg.start[1]) : seg.radius * sweepOf(seg);
}

/** The nearest point on the segment to p, and the distance. */
export function project(seg: Seg, p: Point): { at: Point; distance: number } {
  if (seg.kind === "line") {
    const dx = seg.end[0] - seg.start[0];
    const dy = seg.end[1] - seg.start[1];
    const total = dx * dx + dy * dy;
    const t = total === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - seg.start[0]) * dx + (p[1] - seg.start[1]) * dy) / total));
    const at: Point = [seg.start[0] + dx * t, seg.start[1] + dy * t];
    return { at, distance: Math.hypot(p[0] - at[0], p[1] - at[1]) };
  }
  const total = sweepOf(seg);
  const a0 = Math.atan2(seg.start[1] - seg.center[1], seg.start[0] - seg.center[0]);
  const ap = Math.atan2(p[1] - seg.center[1], p[0] - seg.center[0]);
  const raw = seg.clockwise ? ap - a0 : a0 - ap;
  const turn = ((raw % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  if (turn <= total) {
    const phi = a0 + (seg.clockwise ? turn : -turn);
    const at: Point = [seg.center[0] + seg.radius * Math.cos(phi), seg.center[1] + seg.radius * Math.sin(phi)];
    return { at, distance: Math.hypot(p[0] - at[0], p[1] - at[1]) };
  }
  const toStart = Math.hypot(p[0] - seg.start[0], p[1] - seg.start[1]);
  const toEnd = Math.hypot(p[0] - seg.end[0], p[1] - seg.end[1]);
  return toStart <= toEnd ? { at: seg.start, distance: toStart } : { at: seg.end, distance: toEnd };
}

/** The nearest point on a chain of segments. */
export function projectPath(segs: Seg[], p: Point): { at: Point; distance: number } {
  let best = { at: p, distance: Infinity };
  for (const seg of segs) {
    const found = project(seg, p);
    if (found.distance < best.distance) best = found;
  }
  return best;
}

/** The point of a drawn path furthest from its chord: the third point of an arc drawn by hand. */
export function furthestFromChord(path: Point[]): { at: Point; distance: number } {
  const a = path[0];
  const b = path[path.length - 1];
  if (!a || !b) return { at: [0, 0], distance: 0 };
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const length = Math.hypot(dx, dy) || 1;
  let best = { at: a, distance: 0 };
  for (const p of path) {
    const distance = Math.abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / length;
    if (distance > best.distance) best = { at: p, distance };
  }
  return best;
}

/** The arc through three points, or null when they lie in a row (then it is a line). */
export function arcThrough(a: Point, m: Point, b: Point): Arc | null {
  const d = 2 * (a[0] * (b[1] - m[1]) + b[0] * (m[1] - a[1]) + m[0] * (a[1] - b[1]));
  if (Math.abs(d) < 1e-9) return null;
  const sq = (p: Point) => p[0] * p[0] + p[1] * p[1];
  const ux = (sq(a) * (b[1] - m[1]) + sq(b) * (m[1] - a[1]) + sq(m) * (a[1] - b[1])) / d;
  const uy = (sq(a) * (m[0] - b[0]) + sq(b) * (a[0] - m[0]) + sq(m) * (b[0] - a[0])) / d;
  const turn = (m[0] - a[0]) * (b[1] - m[1]) - (m[1] - a[1]) * (b[0] - m[0]);
  return { kind: "arc", start: a, end: b, center: [ux, uy], radius: Math.hypot(a[0] - ux, a[1] - uy), clockwise: turn > 0 };
}

/** "308", or "1 213" for a length in mm. */
export function mmText(value: number): string {
  return Math.round(value).toLocaleString("sv-SE");
}
