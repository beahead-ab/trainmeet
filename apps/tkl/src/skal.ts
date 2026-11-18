// Skalen (STV-12, STV-41, STV-45): a skin is the symbols, colours, line widths and fonts that
// are laid over the panel's geometry, which is the same in every skin. The drawing
// (stallverk.ts) says what each thing is in logical terms; the skin says how it looks. 85
// follows TDOK 2014:0693 and 95 TDOK 2021:0552, both on a black background (STV-13, STV-42);
// 59 is SJ's signal interlocking model 59, an illuminated track plan operated with toggle
// switches (STV-36). Manöver and Foto are listed and come later. The values are the skins
// document's tables (trainmeet-spec docs/trainmeet-tkl-skalen.md), in its units: 24 to a cell.
// The choice of skin, proportion and view is per screen and kept in this browser (STV-05); a
// change never sends an order (STV-18).
import type { SignalType, TrackState } from "./stallverk";

export type SkinId = "85" | "95" | "59" | "manover" | "foto";
/** Every skin by name, in the order they are offered; only the ones in SKINS can be chosen. */
export const SKIN_NAMES: Record<SkinId, string> = { "85": "85", "95": "95", "59": "59", manover: "Manöver", foto: "Foto" };
export const SKIN_ORDER: SkinId[] = ["85", "95", "59", "manover", "foto"];

/** A shape in the symbol's own frame: x along the direction the signal applies, y across it
 * towards the side its id stands on, in cells. */
export type Shape = { points: [number, number][]; closed: boolean; fill: string | null; stroke: string | null; width: number };

export type SignalLook = { type: SignalType; aspect: "stop" | "proceed" | "shunt" | "local"; end: boolean; blocked: boolean };

/** How the track plan is drawn: as a screen, with the states in the track's colour (85, 95), or
 * as model 59's illuminated plan, with lamps, arrows and toggle switches. */
export type SkinStyle = "screen" | "lamps";

export type Lamps = {
  front: string;
  /** The light metal frame around the plan (infattning). */
  frame: string;
  /** A track circuit's white lamp, lit while it is free; a dark lens when it is not. */
  lit: string;
  lens: string;
  rim: string;
  /** The switch's blue lamp, in the leg it lies in. */
  position: string;
  /** The arrows of a set route: green for a train route, yellow and smaller for shunting. */
  train: string;
  shunting: string;
  red: string;
  /** The dimmed frame of what model 59 does not have: dwarf signals and the number window. */
  added: string;
  window: { ground: string; edge: string; digits: string };
};

export type Skin = {
  id: SkinId;
  style: SkinStyle;
  ground: string;
  /** Platforms, under the track: a shade of the ground. */
  platform: string;
  /** The track's colour per state. */
  tracks: Record<TrackState, string>;
  /** A switch locked as protection: short at the knot, in the leg it lies in (STV-20). */
  protection: string;
  /** A switch freed for the people on the place: short and blue at the knot (FR41). */
  local: string;
  /** Line width, in cells: free, and in a state (the same in 85, wider in 95). */
  width: number;
  stateWidth: number;
  /** The gap in the leg a switch does not lie in, from the knot, in cells. */
  gap: number;
  font: string;
  /** Text height, in cells, and whether texts are in capitals. */
  text: number;
  upper: boolean;
  signalId: string;
  switchNumber: string;
  trackName: string;
  label: string;
  endLabel: string;
  numbers: { red: string; green: string | null; frame: string; size: number; font: string; weight: number; edge: string | null };
  /** How a train number is written: five digits with leading zeros in 85 (TDOK 2014:0693 7.37). */
  numberText: (number: string) => string;
  /** The symbol and the gap it leaves in the track around it, along the track. */
  signal: (look: SignalLook) => { shapes: Shape[]; gap: [number, number] | null };
  /** Model 59: the symbol stands beside the track at its mast, and the id further out. */
  beside: { label: number; along: number } | null;
  buffer: (end: boolean) => Shape[];
  /** The panel function's lamp: red for a stop, blue for a released area, else lit. */
  lamps: { stop: string; local: string; on: string; off: string };
  /** The choice of a route: the start's ring per kind (STV-24), and the goals. */
  rings: { train: string; shunting: string; goal: string; blocked: string; chosen: string };
  /** Model 59 only: its lamps, arrows and toggles. */
  plan59: Lamps | null;
  /** The key of its name and legend in texter.ts. */
  legend: "legend85" | "legend95" | "legend59";
};

const UNIT = 1 / 24; // the skins document counts 24 units to a cell

const triangle = (from: number, to: number, half: number): [number, number][] => [
  [from, half],
  [from, -half],
  [to, 0],
];
const arrow = (from: number, to: number, half: number): [number, number][] => [
  [from, half],
  [to, 0],
  [from, -half],
  [from + (to - from) * 0.42, 0],
];
const angle = (from: number, to: number, half: number): [number, number][] => [
  [from, half],
  [to, 0],
  [from, -half],
];
const box = (from: number, to: number, y: number, half: number): [number, number][] => [
  [from, y - half],
  [to, y - half],
  [to, y + half],
  [from, y + half],
];

export function ring(radius: number, x = 0, y = 0): [number, number][] {
  return Array.from({ length: 16 }, (_, i): [number, number] => {
    const a = (i / 16) * 2 * Math.PI;
    return [x + Math.cos(a) * radius, y + Math.sin(a) * radius];
  });
}

// --- 85 · TDOK 2014:0693 (BVS 544.40001) -----------------------------------------------------------

// TDOK 2014:0693's logical colours as read from its figures (s. 4), the background black (TKL83).
const GREY = "#969696";
const GREEN = "#98cc00";
const YELLOW = "#feff00";
const RED = "#fe0000";
const BLUE = "#3664ff";

/** 85 · TDOK 2014:0693 (BVS 544.40001): the skins document's table for 85. */
const SKIN_85: Skin = {
  id: "85",
  style: "screen",
  ground: "#000000",
  platform: "#161616",
  // Lokalt frigivet område blue (s. 4, prio 6; s. 36); out of service dashed in the free grey.
  tracks: { free: GREY, train: GREEN, shunting: YELLOW, occupied: RED, local: BLUE, out_of_service: GREY, programming: BLUE },
  protection: YELLOW,
  local: BLUE,
  width: 4.5 * UNIT,
  stateWidth: 4.5 * UNIT,
  gap: 0.42,
  font: "var(--tm-mono)",
  text: 0.62,
  upper: false,
  signalId: YELLOW,
  switchNumber: GREY,
  trackName: "#c8c8c8",
  label: "#c8c8c8",
  endLabel: RED,
  numbers: { red: RED, green: GREEN, frame: GREY, size: 0.58, font: "var(--tm-mono)", weight: 700, edge: null },
  numberText: (number) => (/^\d+$/.test(number) ? number.padStart(5, "0") : number),
  signal: ({ type, aspect, end, blocked }) => {
    const contour = 3.6 * UNIT;
    // Grey in stop, green in proceed, red as the end of a set route; a signal that ends one
    // route and starts the next shows the next one's aspect (Benny 8 November). Blocked at
    // stop: the main signal filled red, the dwarf a filled yellow triangle (s. 6, 8, 10).
    // Snett höger, shunting in a locally released area, is blue (s. 10, FR41).
    const main = aspect === "proceed" ? GREEN : end || blocked ? RED : GREY;
    const dwarf = aspect === "local" ? BLUE : aspect !== "stop" ? GREEN : end ? RED : GREY;
    switch (type) {
      case "dvsi": // dvärgsignal: fylld pil (s. 10)
        if (blocked && aspect === "stop") return { shapes: [{ points: triangle(-0.42, 0.42, 0.38), closed: true, fill: YELLOW, stroke: null, width: 0 }], gap: [-0.62, 0.62] };
        return { shapes: [{ points: arrow(-0.42, 0.42, 0.38), closed: true, fill: dwarf, stroke: null, width: 0 }], gap: [-0.62, 0.62] };
      case "hdvsi": // huvuddvärgsignal: pilen bakom triangeln, var sin färg (s. 8)
        return {
          shapes: [
            { points: arrow(-0.78, -0.08, 0.36), closed: true, fill: blocked && aspect === "stop" ? GREY : dwarf, stroke: null, width: 0 },
            { points: triangle(0.04, 0.78, 0.36), closed: true, fill: blocked && aspect !== "proceed" ? RED : "#000000", stroke: main, width: contour },
          ],
          gap: [-0.98, 0.98],
        };
      case "stop_lamp": // slutpunktsstopplykta: liten triangel bredvid spåret, aldrig kör (s. 12)
        return { shapes: [{ points: triangle(-0.3, 0.32, 0.26), closed: true, fill: "#000000", stroke: end ? RED : GREY, width: contour }], gap: null };
      case "fsi": // försignal: finns inte i dokumentets symboler; en ring i spårets grå
        return { shapes: [{ points: ring(0.28), closed: true, fill: "#000000", stroke: GREY, width: contour }], gap: [-0.45, 0.45] };
      default: // huvudsignal: triangel med kraftig kontur som pekar i rörelseriktningen (s. 6)
        return { shapes: [{ points: triangle(-0.42, 0.42, 0.36), closed: true, fill: blocked && aspect !== "proceed" ? RED : "#000000", stroke: main, width: contour }], gap: [-0.62, 0.62] };
    }
  },
  beside: null,
  // Stoppbock: kort stump med tvärslå, skild från spåret; grå, röd som slutpunkt (s. 16).
  buffer: (end) => {
    const colour = end ? RED : GREY;
    return [
      { points: [[-0.85, 0], [-0.55, 0]], closed: false, fill: null, stroke: "#000000", width: 4.5 * UNIT + 0.12 },
      { points: [[-0.55, 0], [0, 0]], closed: false, fill: null, stroke: colour, width: 4.5 * UNIT },
      { points: [[0.06, 0.42], [0.06, -0.42]], closed: false, fill: null, stroke: colour, width: 3.8 * UNIT },
    ];
  },
  lamps: { stop: RED, local: BLUE, on: GREEN, off: "#3a3a3a" },
  // Vald start: blå för tågväg, gul för växlingsväg (the reference interlockings, STV-24).
  rings: { train: "#2256c3", shunting: "#d9a400", goal: "#60a5fa", blocked: "#4b5563", chosen: "#ffffff" },
  plan59: null,
  legend: "legend85",
};

// --- 95 · TDOK 2021:0552 v2.0 ------------------------------------------------------------------

// The document gives logical colours without values (s. 9–10, 13); the skins document's values.
const M = {
  free: "#d3d6d9",
  train: "#2db84c",
  shunting: "#f5d90a",
  occupied: "#e8312a",
  stop: "#b5babf",
  text: "#f2f4f5",
  dim: "#c4c8cc",
  // Frigivet för växling, as the reference interlockings draw 95 (the document's blue).
  local: "#4da3ff",
};

/** 95 · TDOK 2021:0552 v2.0: the skins document's table for 95. */
const SKIN_95: Skin = {
  id: "95",
  style: "screen",
  ground: "#000000",
  platform: "#161616",
  tracks: { free: M.free, train: M.train, shunting: M.shunting, occupied: M.occupied, local: M.local, out_of_service: M.free, programming: M.local },
  protection: M.shunting,
  local: M.local,
  // Ledigt 4 enheter, tillstånd 7 (s. 73–75, the skins document's values).
  width: 4 * UNIT,
  stateWidth: 7 * UNIT,
  gap: 0.42,
  font: "Inter, system-ui, sans-serif",
  text: 0.62,
  upper: false,
  // TKL37: signal ids grey, track numbers (the track circuit's id) yellow, switch numbers white.
  signalId: M.dim,
  switchNumber: M.text,
  trackName: M.shunting,
  label: M.text,
  endLabel: M.occupied,
  // JetBrains Mono 800 in lighter shades with a thin dark edge; the frame of an estimated
  // position is black (s. 12, 132).
  numbers: { red: "#ff4b3e", green: "#47d870", frame: "#000000", size: 0.6, font: "var(--tm-mono)", weight: 800, edge: "#2a2e32" },
  numberText: (number) => number,
  signal: ({ type, aspect, end, blocked }) => {
    const contour = 2.2 * UNIT;
    // Grey in normal stop, green in proceed (main) and free movement (dwarf), the signal's own
    // contour red as the end of a set route (s. 84–89). Blocked at stop: the main signal
    // filled red, a combined signal's angle grey, the dwarf a filled yellow angle (s. 84–89).
    const main = aspect === "proceed" ? M.train : end || blocked ? M.occupied : M.stop;
    const dwarf = aspect === "local" ? M.local : aspect !== "stop" ? M.train : end ? M.occupied : M.stop;
    const filled = blocked && aspect !== "proceed";
    switch (type) {
      case "dvsi": // dvärgsignal: öppen vinkel (s. 88–89, fig. 59)
        if (blocked && aspect === "stop") return { shapes: [{ points: arrow(-0.42, 0.42, 0.36), closed: true, fill: M.shunting, stroke: null, width: 0 }], gap: [-0.62, 0.62] };
        return { shapes: [{ points: angle(-0.42, 0.42, 0.36), closed: false, fill: null, stroke: dwarf, width: 2.4 * UNIT }], gap: [-0.62, 0.62] };
      case "hdvsi": // kombinerad: vinkeln bakom triangeln, var sin färg (s. 86–87, fig. 58)
        return {
          shapes: [
            { points: angle(-0.78, -0.12, 0.32), closed: false, fill: null, stroke: filled ? M.stop : dwarf, width: contour },
            { points: triangle(0.04, 0.78, 0.36), closed: true, fill: filled ? M.occupied : "#000000", stroke: main, width: contour },
          ],
          gap: [-0.98, 0.98],
        };
      case "stop_lamp": // slutpunktsstopplykta: liten öppen triangel till vänster om spåret
        return { shapes: [{ points: triangle(-0.3, 0.32, 0.26), closed: true, fill: "#000000", stroke: end ? M.occupied : M.stop, width: contour }], gap: null };
      case "fsi":
        return { shapes: [{ points: ring(0.28), closed: true, fill: "#000000", stroke: M.stop, width: contour }], gap: [-0.45, 0.45] };
      default: // huvudsignal: öppen triangel i spårlinjen, kontur 2,2 enheter (s. 84–85, fig. 57)
        return { shapes: [{ points: triangle(-0.42, 0.42, 0.36), closed: true, fill: filled ? M.occupied : "#000000", stroke: main, width: contour }], gap: [-0.62, 0.62] };
    }
  },
  beside: null,
  // Stoppbock: en tvärslå i spårets färg, röd som slutpunkt (the reference interlockings).
  buffer: (end) => [{ points: [[0.08, 0.38], [0.08, -0.38]], closed: false, fill: null, stroke: end ? M.occupied : M.free, width: 4 * UNIT }],
  // The prototype's row: signal stop red, local release yellow (tkl-skal.html, funktioner).
  lamps: { stop: M.occupied, local: M.shunting, on: M.train, off: "#3a3d40" },
  rings: { train: "#2256c3", shunting: "#d9a400", goal: "#60a5fa", blocked: "#4b5563", chosen: "#ffffff" },
  plan59: null,
  legend: "legend95",
};

// --- 59 · signalställverk modell 59, illuminerad spårplan ------------------------------------------

const P59: Lamps = {
  front: "#0c0d0d",
  frame: "linear-gradient(180deg, #dfe2e4, #a9adb0)",
  lit: "#fff4d6",
  lens: "#3c4041",
  rim: "#141616",
  position: "#4f8fff",
  train: "#46f57a",
  shunting: "#f0b432",
  red: "#ff3b2e",
  added: "#8e918d",
  window: { ground: "#050606", edge: "#4a4e50", digits: "#d8d3c3" },
};
const LABEL_59 = "#e6e4dc";
const ROW = 0.75; // the symbol's row beside the track, from the track, in cells
const LAMP = 0.14;

/** 59 · SJ:s modell 59 (SJH 325.1 s. 151–158; Västra Torup, VMJF s. 12): the skins
 * document's table for 59. Dwarf signals, shunting routes and the number window are TKL's
 * additions, drawn dimmed. */
const SKIN_59: Skin = {
  id: "59",
  style: "lamps",
  ground: P59.front,
  platform: "#161818",
  // The plan's lines are all light; a state shows in the lamps and arrows, not the line.
  tracks: { free: "#d3d3cb", train: "#d3d3cb", shunting: "#d3d3cb", occupied: "#d3d3cb", local: "#d3d3cb", out_of_service: "#d3d3cb", programming: "#d3d3cb" },
  protection: "#d3d3cb",
  local: P59.position,
  width: 6 * UNIT,
  stateWidth: 6 * UNIT,
  gap: 0,
  font: "'Barlow Condensed', 'Arial Narrow', 'Roboto Condensed', sans-serif",
  text: 0.6,
  upper: true,
  signalId: LABEL_59,
  switchNumber: LABEL_59,
  trackName: LABEL_59,
  label: LABEL_59,
  endLabel: LABEL_59,
  // Model 59 has no number fields: a black window with light digits (a TKL addition), and no
  // green number ahead of the train.
  numbers: { red: P59.window.digits, green: null, frame: P59.window.edge, size: 0.52, font: "'Barlow Condensed', 'Arial Narrow', sans-serif", weight: 700, edge: null },
  numberText: (number) => number,
  signal: ({ type, aspect, end }) => {
    // Beside the track at a short mast (⊢), in the direction the signal applies. Main: an
    // oblong symbol with two lamp openings, red nearest the mast at stop, green in the outer
    // at proceed (VMJF s. 12; SJH s. 151). Dwarf: a small square lantern, dimmed (TKL
    // addition): green proceed, blue shunting in a released area, red stop.
    const mast: Shape[] = [
      { points: [[0, ROW - 0.26], [0, ROW + 0.26]], closed: false, fill: null, stroke: LABEL_59, width: 0.07 },
      { points: [[0, ROW], [0.15, ROW]], closed: false, fill: null, stroke: LABEL_59, width: 0.07 },
    ];
    const lamp = (x: number, colour: string, r = LAMP): Shape => ({ points: ring(r, x, ROW), closed: true, fill: colour, stroke: P59.rim, width: 0.03 });
    const main = (from: number): Shape[] => [
      { points: box(from, from + 0.9, ROW, 0.26), closed: true, fill: "#141616", stroke: LABEL_59, width: 0.055 },
      lamp(from + 0.25, aspect === "proceed" ? P59.lens : P59.red),
      lamp(from + 0.65, aspect === "proceed" ? P59.train : P59.lens),
    ];
    const dwarfColour = aspect === "local" ? P59.position : aspect !== "stop" ? P59.train : P59.red;
    const dwarf = (from: number): Shape[] => [
      { points: box(from, from + 0.32, ROW, 0.16), closed: true, fill: "#141616", stroke: P59.added, width: 0.04 },
      lamp(from + 0.16, dwarfColour, 0.08),
    ];
    switch (type) {
      case "dvsi":
        return { shapes: [...mast.map((s) => ({ ...s, stroke: P59.added })), ...dwarf(0.15)], gap: null };
      case "hdvsi":
        return { shapes: [...mast, ...main(0.15), ...dwarf(1.1)], gap: null };
      case "stop_lamp": // a small round lamp: red when a route ends there, else dark (TKL addition)
        return {
          shapes: [
            { points: ring(0.2), closed: true, fill: "#1a1c1d", stroke: P59.added, width: 0.05 },
            { points: ring(0.12), closed: true, fill: end ? P59.red : P59.lens, stroke: P59.rim, width: 0.03 },
          ],
          gap: null,
        };
      default:
        return { shapes: [...mast, ...main(0.15)], gap: null };
    }
  },
  beside: { label: 1.5, along: 0.6 },
  buffer: () => [{ points: [[0.08, 0.38], [0.08, -0.38]], closed: false, fill: null, stroke: "#d3d3cb", width: 4 * UNIT }],
  // Signal stop and emergency release have a red lamp (SJH s. 152, 158); the rest white.
  lamps: { stop: P59.red, local: P59.shunting, on: P59.lit, off: P59.lens },
  rings: { train: "#2256c3", shunting: "#d9a400", goal: "#60a5fa", blocked: "#4b5563", chosen: "#ffffff" },
  plan59: P59,
  legend: "legend59",
};

/** The skins that can be chosen now. The rest are listed as coming. */
export const SKINS: Partial<Record<SkinId, Skin>> = { "85": SKIN_85, "95": SKIN_95, "59": SKIN_59 };

export function skinOf(id: SkinId): Skin {
  return SKINS[id] ?? SKIN_85;
}

/** A panel function's code in a skin, such as L01 in 85 and 95 and L1 in 59 (FR41). */
export function codeIn(codes: Record<string, string> | undefined, skin: SkinId): string | null {
  return codes?.[skin] ?? null;
}

// --- Per screen (STV-05): which view, skin and proportion, kept in this browser -----------------

export type ScreenView = "all" | "panel" | "row";
export type Screen = { view: ScreenView; skin: SkinId; proportion: number };
export const PROPORTION = { min: 30, max: 90, start: 62 } as const;
const DEFAULT: Screen = { view: "all", skin: "85", proportion: PROPORTION.start };

/** The screen this window is: ?skarm=2 for a second screen, else the first. */
export function screenNumber(search: string): number {
  const found = Number(new URLSearchParams(search).get("skarm"));
  return Number.isInteger(found) && found >= 1 && found <= 9 ? found : 1;
}

const key = (screen: number) => `tkl.skarm.${screen}`;

/** A screen's settings. A skin that cannot be chosen yet, or anything unreadable, is 85. */
export function readScreen(screen: number, storage: Pick<Storage, "getItem"> | null): Screen {
  let found: Partial<Screen> = {};
  try {
    const raw = storage?.getItem(key(screen));
    found = raw ? (JSON.parse(raw) as Partial<Screen>) : {};
  } catch {
    found = {};
  }
  const view: ScreenView = found.view === "panel" || found.view === "row" ? found.view : DEFAULT.view;
  const skin: SkinId = found.skin && found.skin in SKINS ? found.skin : DEFAULT.skin;
  const number = Number(found.proportion);
  const proportion = Number.isFinite(number) ? Math.min(PROPORTION.max, Math.max(PROPORTION.min, Math.round(number))) : DEFAULT.proportion;
  return { view, skin, proportion };
}

export function saveScreen(screen: number, settings: Screen, storage: Pick<Storage, "setItem"> | null): void {
  storage?.setItem(key(screen), JSON.stringify(settings));
}

/** A change of the screen's settings: kept in this browser, and nothing else. A skin change
 * never sends an order to the interlocking (STV-18). */
export function changeScreen(screen: number, settings: Screen, next: Partial<Screen>, storage: Pick<Storage, "setItem"> | null): Screen {
  const made: Screen = { ...settings, ...next };
  if (!(made.skin in SKINS)) made.skin = settings.skin;
  saveScreen(screen, made, storage);
  return made;
}
