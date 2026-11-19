// Ritningen's state in the web app (#89 del b): the change set on top of the version it builds on,
// with undo and redo, the tools, the operations as CAD's API takes them (contracts/cad.py, EditOp),
// and snapping to ends and to the gables' tracks. CAD replays the whole list on the version for
// every change and draws the result; nothing here measures what CAD measures.
import type { DrawingView, EditOp, GraphNode, LockRadii, Smoothing, TrackGraph } from "./api";
import { gableLine, gableDepth, gableOffset, onGable, projectPath, type Point, type Seg } from "./geometry";

export type Tool = "select" | "switch" | "line" | "arc" | "lock" | "measure" | "text";

export const TOOLS: { tool: Tool; label: string; hint: string }[] = [
  { tool: "select", label: "Välj", hint: "Klicka på en växel, ett spår eller en text. Dra en ände eller ett spår för att flytta det." },
  { tool: "switch", label: "Flytta växel", hint: "Dra en växel längs sitt spår." },
  { tool: "line", label: "Rakt spår", hint: "Dra från en ände, ett gavelspår eller mitt på ett spår (då blir det en växel)." },
  { tool: "arc", label: "Båge", hint: "Dra en båge. Håll Skift för frihand: linjen jämnas ut enligt Utjämning." },
  { tool: "lock", label: "Lås mått", hint: "Lås ett gavelmått och räkna om kurvan." },
  { tool: "measure", label: "Mät", hint: "Dra för att mäta avståndet i mm." },
  { tool: "text", label: "Text", hint: "Klicka på ett spår, en växel eller en plats och skriv texten." },
];

/** The change set: the module and the version it builds on, the operations, and those undone. */
export type Editor = { module: string; base: number; ops: EditOp[]; undone: EditOp[] };

export function startEditor(module: string, base: number): Editor {
  return { module, base, ops: [], undone: [] };
}

export function push(editor: Editor, ...ops: EditOp[]): Editor {
  return { ...editor, ops: [...editor.ops, ...ops], undone: [] };
}

export function undo(editor: Editor): Editor {
  const last = editor.ops[editor.ops.length - 1];
  if (!last) return editor;
  return { ...editor, ops: editor.ops.slice(0, -1), undone: [last, ...editor.undone] };
}

export function redo(editor: Editor): Editor {
  const next = editor.undone[0];
  if (!next) return editor;
  return { ...editor, ops: [...editor.ops, next], undone: editor.undone.slice(1) };
}

const r = (n: number) => Math.round(n * 10) / 10;
const pt = (p: Point): [number, number] => [r(p[0]), r(p[1])];

/** The operations, with every field CAD's API has. */
export const op = {
  line: (start: Point, end: Point, startNode: string | null, endNode: string | null): EditOp => ({
    op: "line",
    start: pt(start),
    end: pt(end),
    start_node: startNode,
    end_node: endNode,
  }),
  arc: (start: Point, through: Point, end: Point, startNode: string | null, endNode: string | null): EditOp => ({
    op: "arc",
    start: pt(start),
    through: pt(through),
    end: pt(end),
    start_node: startNode,
    end_node: endNode,
    radius: null,
    angle: null,
    heading: null,
  }),
  polyline: (points: Point[], startNode: string | null, endNode: string | null): EditOp => ({
    op: "polyline",
    points: points.map(pt),
    start_node: startNode,
    end_node: endNode,
  }),
  switchTo: (piece: string, fromA: number, radius: number, to: Point, toNode: string | null): EditOp => ({
    op: "switch",
    piece,
    from_a: r(fromA),
    radius,
    angle: null,
    side: null,
    toward: "B",
    design: null,
    tail: 0,
    to: pt(to),
    to_node: toNode,
  }),
  moveSwitch: (id: string, fromA: number): EditOp => ({ op: "move_switch", switch: id, from_a: r(Math.max(0, fromA)) }),
  move: (target: string, by: Point): EditOp => ({ op: "move", target, by: pt(by) }),
  remove: (target: string): EditOp => ({ op: "delete", target }),
  label: (target: string | null, at: Point | null, text: string): EditOp => ({ op: "label", target, at: at ? pt(at) : null, text }),
  end: (node: string, type: "buffer_stop" | "joint"): EditOp => ({ op: "end", node, type }),
  setSwitch: (id: string, change: { radius?: number; design?: string; locked?: boolean }): EditOp => ({
    op: "set_switch",
    switch: id,
    radius: change.radius ?? null,
    design: change.design ?? null,
    locked: change.locked ?? null,
  }),
  answer: (key: string, answer: string): EditOp => ({ op: "answer", key, answer }),
  smoothing: (level: Smoothing): EditOp => ({ op: "smoothing", level }),
  lock: (piece: string | null, a: number | null, b: number | null, radii: LockRadii): EditOp => ({ op: "lock", piece, a, b, radii }),
};

export function segsOf(graph: TrackGraph, piece: string): Seg[] {
  const found = (graph.pieces ?? []).find((p) => p.id === piece);
  return (found?.segments ?? []).map((s): Seg =>
    s.kind === "arc"
      ? { kind: "arc", start: s.start, end: s.end, center: s.center, radius: s.radius, clockwise: s.clockwise }
      : { kind: "line", start: s.start, end: s.end },
  );
}

/** How many pieces start or end at the node. */
export function piecesAt(graph: TrackGraph, node: string): number {
  return (graph.pieces ?? []).reduce((n, p) => n + (p.start === node ? 1 : 0) + (p.end === node ? 1 : 0), 0);
}

/** A node a new track may end in: a free end, or a gable track with nothing on it. */
export function isFree(graph: TrackGraph, node: GraphNode): boolean {
  const count = piecesAt(graph, node.id);
  if (node.type === "joint") return count <= 1;
  if (node.type === "module_joint") return count === 0;
  return false;
}

export type Snap = { at: Point; node: string | null; piece: string | null; kind: "end" | "gable" | "track" | "free" };

/** Where a pointer at p lands, within tolerance mm: a free end, a gable's track position, the
 * gable itself, the middle of a track (a switch), or just the point. */
export function snap(view: DrawingView, p: Point, tolerance: number, avoid: string | null = null): Snap {
  const graph = view.graph;
  let best: Snap | null = null;
  let bestDistance = tolerance;
  for (const node of graph.nodes ?? []) {
    if (node.id === avoid || !isFree(graph, node)) continue;
    const d = Math.hypot(node.at[0] - p[0], node.at[1] - p[1]);
    if (d <= bestDistance) {
      best = { at: node.at, node: node.id, piece: null, kind: "end" };
      bestDistance = d;
    }
  }
  if (best) return best;
  const track1 = view.gables[0]?.tracks?.[0] ?? 0;
  for (const gable of view.gables) {
    const line = gableLine(view.shape, track1, gable.end);
    for (const offset of gable.tracks ?? []) {
      const at = onGable(line, offset);
      const d = Math.hypot(at[0] - p[0], at[1] - p[1]);
      if (d <= bestDistance) {
        best = { at, node: null, piece: null, kind: "gable" };
        bestDistance = d;
      }
    }
  }
  if (best) return best;
  for (const piece of graph.pieces ?? []) {
    const found = projectPath(segsOf(graph, piece.id), p);
    const nearEnd = (graph.nodes ?? []).some((n) => (n.id === piece.start || n.id === piece.end) && Math.hypot(n.at[0] - found.at[0], n.at[1] - found.at[1]) < tolerance * 2);
    if (found.distance <= bestDistance && !nearEnd) {
      best = { at: found.at, node: null, piece: piece.id, kind: "track" };
      bestDistance = found.distance;
    }
  }
  if (best) return best;
  for (const end of ["A", "B"] as const) {
    const line = gableLine(view.shape, track1, end);
    const offset = gableOffset(line, p);
    if (Math.abs(gableDepth(line, p)) <= tolerance && offset >= 0 && offset <= line.width) {
      return { at: onGable(line, Math.round(offset)), node: null, piece: null, kind: "gable" };
    }
  }
  return { at: p, node: null, piece: null, kind: "free" };
}

/** The short word a check's marker gets on the drawing: "passbit?", "radie?". */
export function markerWord(kind: string): string {
  return (
    {
      short_rail: "passbit?",
      open_end: "ände?",
      switch_radius: "radie?",
      switch_assumed: "typ?",
      kink: "knyck?",
      tight_radius: "radie?",
      gable_position: "gavelmått?",
      question: "fråga",
    } as Record<string, string>
  )[kind] ?? "?";
}

/** The default radius of a switch drawn by hand: the scale's smallest known type, else twice the
 * minimum radius. It is a switch of type Okänd until the owner chooses, and Att kolla asks. */
export function drawnSwitchRadius(view: DrawingView): number {
  const known = (view.designs ?? []).map((d) => d.radius ?? 0).filter((x) => x > 0);
  return known.length ? Math.min(...known) : view.limits.min_radius * 2;
}

export function sourceBadge(source: string | undefined): { text: string; kind: string } {
  if (source === "photo") return { text: "AI-förslag", kind: "forslag" };
  if (source === "drawn") return { text: "Ritad", kind: "ritad" };
  return { text: "Ur måtten", kind: "matt" };
}
