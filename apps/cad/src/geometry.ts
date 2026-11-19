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

export const RADIUS_STEP = 10;
export const ANGLE_STEP = 0.5;

/** Track 1's radius and angle from the string (chord) and its sagitta: R = (c² + 4s²) / 8s. */
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

/** The nearest round values: R to 10 mm and the angle to half a degree. */
export function rounded(bend: Bend): Bend {
  return {
    radius: Math.round(bend.radius / RADIUS_STEP) * RADIUS_STEP,
    angle: Math.round(bend.angle / ANGLE_STEP) * ANGLE_STEP,
  };
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
    return [gable === "A" ? 0 : shape.length, offset];
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
