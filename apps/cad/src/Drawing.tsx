// The module drawn from its track graph in SVG: the board, Kant 1, the tracks and the gables with
// their norm. A curve is turned so that its string lies level, as in the view Kurvmodul.
import type { GableLabel, Shape, TrackGraph } from "./api";
import { pointOn, preview, type Point, type Seg } from "./geometry";

type Props = {
  shape: Shape;
  /** The gables' tracks from Kant 1, A first. */
  tracks: [number[], number[]];
  /** The module's graph from CAD; without it the preview from the measures is drawn. */
  graph?: TrackGraph | null;
  /** Labels at the gables, such as "FREMO dubbelspår". */
  gables?: GableLabel[] | [string, string];
  /** A small picture for the library: no texts. */
  small?: boolean;
  title?: string;
};

export type Turn = (p: Point) => Point;

/** The turn that lays a curve's string level; nothing for the other shapes. */
export function turnDegrees(shape: Shape): number {
  if (shape.kind !== "curve") return 0;
  return (shape.angle / 2) * ((shape.edge ?? "outer") === "outer" ? -1 : 1);
}

export function turner(shape: Shape): Turn {
  if (shape.kind !== "curve") return (p) => p;
  // Turn the curve by half its angle so that the string between the gables lies level.
  const half = ((shape.angle / 2) * Math.PI) / 180 * ((shape.edge ?? "outer") === "outer" ? -1 : 1);
  const cos = Math.cos(half);
  const sin = Math.sin(half);
  return ([x, y]) => [x * cos - y * sin, x * sin + y * cos];
}

export function outline(shape: Shape, track1: number): Point[] {
  if (shape.kind === "straight") return [[0, 0], [shape.length, 0], [shape.length, shape.width], [0, shape.width]];
  if (shape.kind === "trapezoid") {
    const o = shape.offset ?? 0;
    return [[0, 0], [shape.length, o], [shape.length, o + shape.width_b], [0, shape.width_a]];
  }
  const steps = 24;
  const edge: Point[] = [];
  const far: Point[] = [];
  const bent = (shape.sides ?? "bent") === "bent";
  for (let k = 0; k <= steps; k += 1) {
    if (!bent && k !== 0 && k !== steps) continue;
    const angle = (shape.angle * k) / steps;
    edge.push(pointOn(shape, track1, 0, angle));
    far.push(pointOn(shape, track1, shape.width, angle));
  }
  return [...edge, ...far.reverse()];
}

export function kantOne(shape: Shape, track1: number): Point[] {
  if (shape.kind === "trapezoid") return [[0, 0], [shape.length, shape.offset ?? 0]];
  if (shape.kind !== "curve") return [[0, 0], [shape.length, 0]];
  const steps = 24;
  return Array.from({ length: steps + 1 }, (_, k) => pointOn(shape, track1, 0, (shape.angle * k) / steps));
}

export function segsOf(graph: TrackGraph): Seg[] {
  return (graph.pieces ?? []).flatMap((piece) =>
    piece.segments.map((s): Seg =>
      s.kind === "arc"
        ? { kind: "arc", start: s.start, end: s.end, center: s.center, radius: s.radius, clockwise: s.clockwise }
        : { kind: "line", start: s.start, end: s.end },
    ),
  );
}

export const f = (n: number) => (Math.round(n * 10) / 10).toString();

export function pathOf(seg: Seg, turn: Turn): string {
  const [x0, y0] = turn(seg.start);
  const [x1, y1] = turn(seg.end);
  if (seg.kind === "line") return `M${f(x0)} ${f(y0)}L${f(x1)} ${f(y1)}`;
  return `M${f(x0)} ${f(y0)}A${f(seg.radius)} ${f(seg.radius)} 0 0 ${seg.clockwise ? 1 : 0} ${f(x1)} ${f(y1)}`;
}

export function poly(points: Point[], turn: Turn, close: boolean): string {
  return points.map((p, i) => `${i ? "L" : "M"}${f(turn(p)[0])} ${f(turn(p)[1])}`).join("") + (close ? "Z" : "");
}

function labelOf(gable: GableLabel | string | undefined): string {
  if (!gable) return "";
  return typeof gable === "string" ? gable : gable.label;
}

/** The module seen from above (ovanifrån). */
export function ModuleDrawing({ shape, tracks, graph, gables, small = false, title }: Props) {
  const [a, b] = tracks;
  const track1 = a[0] ?? 0;
  const turn = turner(shape);
  const local = preview(shape, a, b);
  const segs = graph ? segsOf(graph) : local.pieces;
  const complete = graph ? graph.complete : local.complete;
  const board = outline(shape, track1);
  const turned = board.map(turn);
  const xs = turned.map((p) => p[0]);
  const ys = turned.map((p) => p[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const w = Math.max(...xs) - minX;
  const h = Math.max(...ys) - minY;
  const pad = small ? Math.max(w, h) * 0.04 : Math.max(w, h) * 0.12;
  const view = `${f(minX - pad)} ${f(minY - pad * (small ? 1 : 1.6))} ${f(w + 2 * pad)} ${f(h + pad * (small ? 2 : 3.2))}`;
  const unit = Math.max(w, h) / 100;
  // Where the tracks between the gables are not known, a short solid stub at each gable and a
  // dashed line onwards: "okänt" (the view Rak modul).
  const stubs = complete
    ? []
    : local.ends.map((end) => {
        const length = shape.kind === "curve" ? 0 : shape.length * 0.18;
        const dir = end.gable === "A" ? 1 : -1;
        const to: Point = [end.at[0] + dir * length, end.at[1]];
        return { from: end.at, to, gable: end.gable };
      });
  const labelA = labelOf(gables?.[0]);
  const labelB = labelOf(gables?.[1]);
  const gableA = turn([0, 0]);
  const endB: Point = shape.kind === "curve" ? pointOn(shape, track1, 0, shape.angle) : [shape.length, shape.kind === "trapezoid" ? (shape.offset ?? 0) : 0];
  const gableB = turn(endB);
  return (
    <svg
      className={small ? "cad-ritning liten" : "cad-ritning"}
      viewBox={view}
      role="img"
      aria-label={title ?? "Modulen ovanifrån"}
      preserveAspectRatio="xMidYMid meet"
    >
      <path className="cad-skiva" d={poly(board, turn, true)} strokeWidth={unit * (small ? 0.6 : 0.25)} />
      <path className="cad-kant1" d={poly(kantOne(shape, track1), turn, false)} strokeWidth={unit * (small ? 1.6 : 0.9)} />
      {segs.map((seg, i) => (
        <path key={`s${i}`} className="cad-spar" d={pathOf(seg, turn)} strokeWidth={unit * (small ? 1.4 : 0.55)} />
      ))}
      {stubs.map((stub, i) => (
        <g key={`t${i}`}>
          <path className="cad-spar" d={pathOf({ kind: "line", start: stub.from, end: stub.to }, turn)} strokeWidth={unit * (small ? 1.4 : 0.55)} />
          {shape.kind !== "curve" ? (
            <path
              className="cad-okant"
              d={pathOf({ kind: "line", start: stub.to, end: [stub.to[0] + (stub.gable === "A" ? 1 : -1) * shape.length * 0.12, stub.to[1]] }, turn)}
              strokeWidth={unit * (small ? 1 : 0.45)}
              strokeDasharray={`${unit * 1.5} ${unit * 1.2}`}
            />
          ) : null}
        </g>
      ))}
      {!small ? (
        <g className="cad-texter" fontSize={unit * 2.6}>
          {shape.kind === "curve" ? (
            <text x={minX + w / 2} y={minY - unit * 2.4} textAnchor="middle" className="cad-kant1-text">
              KANT 1
            </text>
          ) : (
            <text x={gableA[0]} y={gableA[1] - unit * 2.4} textAnchor="start" className="cad-kant1-text">
              KANT 1
            </text>
          )}
          <text x={gableA[0]} y={minY + h + pad * 0.9} textAnchor="start" className="cad-gavel-text">
            GAVEL A{labelA ? ` · ${labelA}` : ""}
          </text>
          <text x={gableB[0]} y={minY + h + pad * 0.9} textAnchor="end" className="cad-gavel-text">
            GAVEL B{labelB ? ` · ${labelB}` : ""}
          </text>
        </g>
      ) : null}
    </svg>
  );
}

/** A gable seen from outside: the board's end, Kant 1 and the tracks, with the measures as a
 * chain from Kant 1 (Kant 1 → spår 1, spår 1 → spår 2 …), as in the view Rak modul. */
export function GableView({ end, width, tracks }: { end: "A" | "B"; width: number; tracks: number[] }) {
  const height = Math.max(40, width * 0.16);
  const pad = width * 0.06;
  const font = height * 0.3;
  // Gable A is seen with Kant 1 to the left, gable B with Kant 1 to the right.
  const x = (offset: number) => (end === "A" ? offset : width - offset);
  const steps = tracks.map((t, i) => ({ from: i === 0 ? 0 : (tracks[i - 1] ?? 0), to: t }));
  return (
    <svg className="cad-gavelbild" viewBox={`${-pad} ${-height * 1.9} ${width + 2 * pad} ${height * 3.7}`} role="img" aria-label={`Gavel ${end} sedd utifrån`}>
      <rect className="cad-skiva" x={0} y={0} width={width} height={height} strokeWidth={width * 0.004} />
      <rect className="cad-kant1-fyllning" x={end === "A" ? 0 : width - width * 0.012} y={0} width={width * 0.012} height={height} />
      {steps.map((step, i) => {
        // A narrow step gets its number higher up, so that two numbers never overlap.
        const narrow = Math.abs(step.to - step.from) < font * 2.4;
        const y = -height * (narrow && i % 2 ? 1.35 : 0.7);
        const mid = x((step.from + step.to) / 2);
        return (
          <g key={i}>
            <path className="cad-mattlinje" d={`M${x(step.from)} ${-height * 0.45}H${x(step.to)}`} strokeWidth={width * 0.003} />
            <path className="cad-mattlinje" d={`M${x(step.to)} ${-height * 0.6}V${-height * 0.1}`} strokeWidth={width * 0.002} />
            <text x={mid} y={y} fontSize={font} textAnchor="middle" className="cad-matt">
              {Math.round(step.to - step.from)}
            </text>
          </g>
        );
      })}
      {tracks.map((offset, i) => (
        <g key={i}>
          <rect className="cad-sliper" x={x(offset) - width * 0.02} y={-height * 0.12} width={width * 0.04} height={height * 0.12} />
          <text x={x(offset)} y={height * 0.62} fontSize={font} textAnchor="middle">
            {i + 1}
          </text>
        </g>
      ))}
      <text x={end === "A" ? 0 : width} y={height * 1.5} fontSize={font} textAnchor={end === "A" ? "start" : "end"} className="cad-kant1-text">
        KANT 1
      </text>
    </svg>
  );
}

/** A gable profile's tracks as dots on a bar: solid where the position is fixed or measured,
 * dashed where it is given per module (the view Gavelprofiler). */
export function ProfileBar({ width, positions }: { width: number; positions: (number | null)[] }) {
  const known = positions.filter((p): p is number => p != null);
  const span = Math.max(width, ...known.map((p) => p + 40));
  const open = positions.length - known.length;
  const start = known.length ? Math.max(...known) + span * 0.12 : span * 0.4;
  return (
    <svg className="cad-profilbar" viewBox={`0 0 ${span} 60`} role="img" aria-label={`${positions.length} spår`} preserveAspectRatio="none">
      <rect className="cad-skiva" x={0} y={14} width={span} height={32} rx={4} />
      <rect className="cad-kant1-fyllning" x={0} y={14} width={span * 0.012} height={32} />
      {positions.map((p, i) => {
        const cx = p ?? start + (i - known.length) * span * (open > 1 ? 0.12 : 0);
        return <circle key={i} className={p == null ? "cad-prick oppen" : "cad-prick"} cx={cx} cy={30} r={9} />;
      })}
    </svg>
  );
}
