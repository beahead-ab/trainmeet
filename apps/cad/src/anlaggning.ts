// Anläggningar and Till TKL Studio (#89 del d2, CAD-06, CAD-10, CAD-15, CAD-21): the assembly as
// CAD's API gives it, and the changes the page makes to it, as pure functions so that the tests
// read them without a browser. CAD places the modules, checks the joints and joins the graph
// (cad/assembly.py); the page only says which modules, which gables meet and at what angle.
import type { components } from "../../../contracts/cad";
import { API, call, type ModuleBrief, type TrackGraph } from "./api";

type Schemas = components["schemas"];
export type Assembly = Schemas["trainmeet.cad-1.assembly"];
export type AssemblyBrief = Schemas["trainmeet.cad-1.assembly-brief"];
export type AssemblyChange = Schemas["trainmeet.cad-1.assembly-change"];
export type AssemblyPart = NonNullable<AssemblyChange["modules"]>[number];
export type NewAssembly = Schemas["trainmeet.cad-1.new-assembly"];
export type Joint = NonNullable<Assembly["joints"]>[number];
export type JointEnd = Joint["a"];
export type AssemblyModule = NonNullable<Assembly["parts"]>[number];
export type GableAt = NonNullable<AssemblyModule["gables"]>[number];
export type JointCheck = NonNullable<Assembly["checks"]>[number];
export type StationUse = NonNullable<Assembly["stations"]>[number];
export type StudioGraph = Schemas["trainmeet.cad-1.studio-graph"];
export type End = "A" | "B";
type Point = [number, number];

export const assemblyApi = {
  list: () => call<AssemblyBrief[]>("GET", `${API}/assemblies`),
  create: (body: NewAssembly) => call<Assembly>("POST", `${API}/assemblies`, body),
  read: (id: string) => call<Assembly>("GET", `${API}/assemblies/${id}`),
  save: (id: string, body: AssemblyChange) => call<Assembly>("PUT", `${API}/assemblies/${id}`, body),
  remove: (id: string) => call<{ id: string }>("DELETE", `${API}/assemblies/${id}`),
  studio: (id: string) => call<StudioGraph>("GET", `${API}/studio/assembly/${id}`),
};

/** The assembly as a change that keeps everything: the versions pinned, the placement CAD made. */
export function changeOf(assembly: Assembly): AssemblyChange {
  return {
    base: assembly.revision,
    name: assembly.name,
    modules: (assembly.modules ?? []).map((m) => ({ module: m.module, version: m.version, at: m.at, angle: m.angle })),
    joints: (assembly.joints ?? []).map((j) => ({ a: { ...j.a }, b: { ...j.b }, angle: j.angle ?? 0 })),
  };
}

const parts = (change: AssemblyChange): AssemblyPart[] => change.modules ?? [];
const joints = (change: AssemblyChange): Joint[] => change.joints ?? [];

/** Where a module the owner puts down freely lies: to the right of everything there is. */
export function besideAll(assembly: Assembly): Point {
  const xs = (assembly.parts ?? []).flatMap((p) => (p.outline ?? []).map((q) => q[0]));
  const ys = (assembly.parts ?? []).flatMap((p) => (p.outline ?? []).map((q) => q[1]));
  if (!xs.length) return [0, 0];
  return [Math.round(Math.max(...xs) + 300), Math.round(Math.min(...ys))];
}

/** Lägg till modul: at its newest approved version, at a free gable or free beside the rest. */
export function addModule(assembly: Assembly, module: string, at: JointEnd | null, own: End = "A"): AssemblyChange {
  const change = changeOf(assembly);
  const placed: AssemblyPart = { module, version: null, at: besideAll(assembly), angle: 0 };
  return {
    ...change,
    modules: [...parts(change), placed],
    joints: at ? [...joints(change), { a: at, b: { module, gable: own }, angle: 0 }] : joints(change),
  };
}

/** Ta bort: the module and its joints. */
export function removeModule(assembly: Assembly, module: string): AssemblyChange {
  const change = changeOf(assembly);
  return {
    ...change,
    modules: parts(change).filter((m) => m.module !== module),
    joints: joints(change).filter((j) => j.a.module !== module && j.b.module !== module),
  };
}

/** Skarva: two free gables together, flush. */
export function join(assembly: Assembly, a: JointEnd, b: JointEnd): AssemblyChange {
  const change = changeOf(assembly);
  return { ...change, joints: [...joints(change), { a, b, angle: 0 }] };
}

export function unjoin(assembly: Assembly, index: number): AssemblyChange {
  const change = changeOf(assembly);
  return { ...change, joints: joints(change).filter((_, i) => i !== index) };
}

export function jointAngle(assembly: Assembly, index: number, angle: number): AssemblyChange {
  const change = changeOf(assembly);
  return { ...change, joints: joints(change).map((j, i) => (i === index ? { ...j, angle } : j)) };
}

/** The angle of a module that no joint places: the first, or one lying free. */
export function moduleAngle(assembly: Assembly, module: string, angle: number): AssemblyChange {
  const change = changeOf(assembly);
  return { ...change, modules: parts(change).map((m) => (m.module === module ? { ...m, angle } : m)) };
}

/** Använd version n: the newer approved version, on the owner's word; never taken silently. */
export function takeNewer(assembly: Assembly, module: string): AssemblyChange {
  const change = changeOf(assembly);
  return { ...change, modules: parts(change).map((m) => (m.module === module ? { ...m, version: null } : m)) };
}

export function rename(assembly: Assembly, name: string): AssemblyChange {
  return { ...changeOf(assembly), name };
}

/** A module's name as the page writes it: "M-001 Linje 1", or that it is not seen. */
export function title(part: AssemblyModule | undefined): string {
  if (!part) return "Modulen";
  return part.seen ? `${part.number ?? ""} ${part.name ?? ""}`.trim() : "En modul du inte ser";
}

export type FreeGable = { end: JointEnd; text: string; at: Point };

/** The gables no joint uses: where the next module can go. */
export function freeGables(assembly: Assembly): FreeGable[] {
  return (assembly.parts ?? []).flatMap((part) =>
    (part.gables ?? [])
      .filter((g) => !g.joined && part.seen)
      .map((g) => ({
        end: { module: part.module, gable: g.end },
        text: `${title(part)} · gavel ${g.end} · ${g.label}`,
        at: middle(g.tracks?.length ? g.tracks : [g.corner, g.far]),
      })),
  );
}

export function middle(points: Point[]): Point {
  const n = points.length || 1;
  return [points.reduce((s, p) => s + p[0], 0) / n, points.reduce((s, p) => s + p[1], 0) / n];
}

export const endKey = (end: JointEnd): string => `${end.module}:${end.gable}`;

export function endOf(key: string): JointEnd | null {
  const at = key.lastIndexOf(":");
  const gable = key.slice(at + 1);
  return at > 0 && (gable === "A" || gable === "B") ? { module: key.slice(0, at), gable } : null;
}

/** A joint as the page writes it: "M-001 Linje 1 B – M-002 Linje 2 A". */
export function jointText(assembly: Assembly, joint: Joint): string {
  const named = (end: JointEnd) => `${title((assembly.parts ?? []).find((p) => p.module === end.module))} ${end.gable}`;
  return `${named(joint.a)} – ${named(joint.b)}`;
}

/** The modules that may be put in: approved, in the assembly's scale, not in it already. */
export function candidates(assembly: Assembly, modules: ModuleBrief[]): ModuleBrief[] {
  const taken = new Set((assembly.modules ?? []).map((m) => m.module));
  return modules.filter((m) => m.status === "approved" && m.scale === assembly.scale && !taken.has(m.id));
}

export type Follows = { pieces: number; switches: number; crossings: number; exits: number; ends: number; metres: number };

/** Det här följer med (CAD-10): the track graph only, counted. A track at a free gable is the
 * station's border, one that ends inside a module a buffer stop: Studio decides both. */
export function follows(graph: TrackGraph): Follows {
  const touching = new Map<string, number>();
  for (const p of graph.pieces ?? []) for (const e of [p.start, p.end]) touching.set(e, (touching.get(e) ?? 0) + 1);
  const nodes = graph.nodes ?? [];
  const once = (n: (typeof nodes)[number]) => touching.get(n.id) === 1;
  const length = (graph.pieces ?? []).reduce(
    (sum, p) =>
      sum +
      p.segments.reduce((s, seg) => {
        if (seg.kind !== "arc") return s + Math.hypot(seg.end[0] - seg.start[0], seg.end[1] - seg.start[1]);
        const chord = Math.hypot(seg.end[0] - seg.start[0], seg.end[1] - seg.start[1]);
        return s + 2 * seg.radius * Math.asin(Math.min(1, chord / (2 * seg.radius)));
      }, 0),
    0,
  );
  return {
    pieces: (graph.pieces ?? []).length,
    switches: (graph.switches ?? []).length,
    crossings: nodes.filter((n) => n.type === "crossing").length,
    exits: nodes.filter((n) => n.type === "module_joint" && once(n)).length,
    ends: nodes.filter((n) => n.type !== "module_joint" && once(n)).length,
    metres: Math.round(length / 100) / 10,
  };
}

/** The box around everything, with a margin: the drawing's viewBox. */
export function box(points: Point[], margin = 0.06): { x: number; y: number; w: number; h: number } {
  if (!points.length) return { x: 0, y: 0, w: 1000, h: 500 };
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const w = Math.max(...xs) - Math.min(...xs) || 1;
  const h = Math.max(...ys) - Math.min(...ys) || 1;
  const pad = Math.max(w, h) * margin;
  return { x: Math.min(...xs) - pad, y: Math.min(...ys) - pad, w: w + 2 * pad, h: h + 2 * pad };
}

/** TKL Studio's Rita, where Från CAD is: the test environment's, or TKL's own. */
export function studioHref(host: string): string {
  const test = host.startsWith("test.") || host.startsWith("localhost") || host.startsWith("127.");
  return test ? "https://test.tkl.trainmeet.app/studio/rita" : "https://tkl.trainmeet.app/studio/rita";
}
