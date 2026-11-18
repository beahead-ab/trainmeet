// Spårplan (#83): what the page works out from the station's panel, without React. The panel is
// the engine's proposal on the grid or the panel built from the station's own track plan; both
// come from TKL's server (contracts/tkl.py) and are only drawn here.
import type { Panel, PanelLine, Route } from "./api";

export type Form = "schematic" | "soft";
export type Box = { x: number; y: number; width: number; height: number };

const STATION_MODEL = "trainmeet.station-model/1";
/** The largest model file TKL takes (tkl/app.py). */
export const MODEL_LIMIT = 8 * 1024 * 1024;

/** A model file as the import reads it: its text when it may go to TKL, or why not. */
export function readModelFile(text: string): { text: string; name: string } | { error: string } {
  if (text.length > MODEL_LIMIT) return { error: "Filen är för stor för en stationsmodell." };
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { error: "Filen är inte JSON. Välj en stationsmodell, <station>.tkl.json." };
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { error: "Filen är inte en stationsmodell." };
  }
  const found = data as { format?: unknown; name?: unknown };
  if (found.format !== STATION_MODEL) {
    return { error: `Filen är inte en stationsmodell: formatet ska vara ${STATION_MODEL}.` };
  }
  return { text, name: typeof found.name === "string" ? found.name : "stationen" };
}

/** The routes by kind, train routes first, each in the order the engine gives. */
export function routesByKind(routes: Route[]): { train: Route[]; shunting: Route[] } {
  return { train: routes.filter((r) => r.kind === "train"), shunting: routes.filter((r) => r.kind === "shunting") };
}

export function routeName(route: Route): string {
  return `${route.start} → ${route.end}`;
}

/** The lines a route runs over, to draw in the route's colour. */
export function routeLines(panel: Panel, route: Route | null): PanelLine[] {
  if (!route) return [];
  const pieces = new Set(route.pieces);
  return panel.lines.filter((line) => pieces.has(line.piece));
}

/** What the view shows: the whole panel, or one field of it (STD-03), in the drawing's units:
 * pixels for the schematic view, millimetres for the soft one. */
export function viewBox(panel: Panel, form: Form, field: number | null): Box {
  if (form === "soft" && panel.real_box) {
    const [x, y, width, height] = panel.real_box;
    const pad = Math.max(width, height) * 0.03 + 20;
    return { x: x - pad, y: y - pad, width: width + 2 * pad, height: height + 2 * pad };
  }
  const [dx, dy] = panel.cell;
  const chosen = field === null ? null : (panel.fields ?? [])[field];
  if (chosen) return { x: chosen.start * dx, y: 0, width: (chosen.end - chosen.start) * dx, height: panel.height * dy };
  const { min, max } = extent(panel);
  const pad = 1.5;
  return { x: (min[0] - pad) * dx, y: (min[1] - pad) * dy, width: (max[0] - min[0] + 2 * pad) * dx, height: (max[1] - min[1] + 2 * pad) * dy };
}

function extent(panel: Panel): { min: [number, number]; max: [number, number] } {
  const points: [number, number][] = [
    ...panel.lines.flatMap((line) => line.cells),
    ...(panel.signals ?? []).map((s) => s.label),
    ...(panel.labels ?? []).map((l) => l.cell),
    ...(panel.track_names ?? []).map((t) => t.cell),
    ...(panel.platforms ?? []).flatMap(([x1, y1, x2, y2]): [number, number][] => [
      [x1, y1],
      [x2, y2],
    ]),
  ];
  if (panel.building) points.push([panel.building.cells[0], panel.building.cells[1]], [panel.building.cells[2], panel.building.cells[3]]);
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return { min: [Math.min(...xs, 0), Math.min(...ys, 0)], max: [Math.max(...xs, panel.width), Math.max(...ys, 1)] };
}

/** "x,y x,y …" for an SVG polyline, in the view's units. */
export function points(cells: [number, number][], scale: [number, number] = [1, 1]): string {
  return cells.map(([x, y]) => `${round(x * scale[0])},${round(y * scale[1])}`).join(" ");
}

export function round(value: number): number {
  return Math.round(value * 100) / 100;
}

export const SIGNAL_NAMES: Record<string, string> = {
  hsi: "huvudsignal",
  hdvsi: "huvuddvärgsignal",
  dvsi: "dvärgsignal",
  fsi: "försignal",
  stop_lamp: "slutpunktsstopplykta",
};

export const LEVELS: Record<number, string> = {
  1: "Nivå 1 · spårplan",
  2: "Nivå 2 · signaler och spårledningar",
  3: "Nivå 3 · LocoNet",
};
