// Skalen (STV-12, STV-41, STV-45): a skin is the symbols, colours, line widths and fonts that
// are laid over the panel's geometry, which is the same in every skin. The drawing
// (stallverk.ts) says what each thing is in logical terms; the skin says how it looks. 85
// follows TDOK 2014:0693 on a black background (STV-13, STV-42) and is built first (STV-41);
// 95, 59, Manöver and Foto are listed and come later. The choice of skin, proportion and view
// is per screen and kept in this browser (STV-05); a change never sends an order (STV-18).
import type { SignalType, TrackState } from "./stallverk";

export type SkinId = "85" | "95" | "59" | "manover" | "foto";
/** Every skin by name, in the order they are offered; only the ones in SKINS can be chosen. */
export const SKIN_NAMES: Record<SkinId, string> = { "85": "85", "95": "95", "59": "59", manover: "Manöver", foto: "Foto" };
export const SKIN_ORDER: SkinId[] = ["85", "95", "59", "manover", "foto"];

/** A shape in the symbol's own frame: x along the direction the signal applies, y across it
 * to the left of that direction, in cells. */
export type Shape = { points: [number, number][]; closed: boolean; fill: string | null; stroke: string | null; width: number };

export type SignalLook = { type: SignalType; aspect: "stop" | "proceed" | "shunt"; end: boolean };

export type Skin = {
  id: SkinId;
  ground: string;
  /** Platforms, under the track: a shade of the ground. */
  platform: string;
  /** The track's colour per state; the same width in every state (TDOK 2014:0693 s. 4). */
  tracks: Record<TrackState, string>;
  /** A switch locked as protection: short at the knot, in the leg it lies in (STV-20). */
  protection: string;
  /** Line width, in cells. */
  width: number;
  /** The gap in the leg a switch does not lie in, from the knot, in cells. */
  gap: number;
  font: string;
  /** Text height, in cells. */
  text: number;
  signalId: string;
  switchNumber: string;
  trackName: string;
  label: string;
  endLabel: string;
  numbers: { red: string; green: string; frame: string; size: number };
  /** How a train number is written: five digits with leading zeros in 85 (TDOK 2014:0693 7.37). */
  numberText: (number: string) => string;
  /** The symbol and the gap it leaves in the track around it, along the track. */
  signal: (look: SignalLook) => { shapes: Shape[]; gap: [number, number] | null };
  buffer: (end: boolean) => Shape[];
  /** The choice of a route: the start's ring per kind (STV-24), and the goals. */
  rings: { train: string; shunting: string; goal: string; blocked: string; chosen: string };
};

// TDOK 2014:0693's logical colours as read from its figures (s. 4), the background black (TKL83).
const GREY = "#969696";
const GREEN = "#98cc00";
const YELLOW = "#feff00";
const RED = "#fe0000";
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

/** 85 · TDOK 2014:0693 (BVS 544.40001): the skins document's table for 85. */
const SKIN_85: Skin = {
  id: "85",
  ground: "#000000",
  platform: "#161616",
  tracks: { free: GREY, train: GREEN, shunting: YELLOW, occupied: RED },
  protection: YELLOW,
  width: 4.5 * UNIT,
  gap: 0.42,
  font: "var(--tm-mono)",
  text: 0.62,
  signalId: YELLOW,
  switchNumber: GREY,
  trackName: "#c8c8c8",
  label: "#c8c8c8",
  endLabel: RED,
  numbers: { red: RED, green: GREEN, frame: GREY, size: 0.58 },
  numberText: (number) => (/^\d+$/.test(number) ? number.padStart(5, "0") : number),
  signal: ({ type, aspect, end }) => {
    const contour = 3.6 * UNIT;
    // Grey in stop, green in proceed, red as the end of a set route; a signal that ends one
    // route and starts the next shows the next one's aspect (Benny 8 November).
    const main = aspect === "proceed" ? GREEN : end ? RED : GREY;
    const dwarf = aspect !== "stop" ? GREEN : end ? RED : GREY;
    switch (type) {
      case "dvsi": // dvärgsignal: fylld pil (s. 10)
        return { shapes: [{ points: arrow(-0.42, 0.42, 0.38), closed: true, fill: dwarf, stroke: null, width: 0 }], gap: [-0.62, 0.62] };
      case "hdvsi": // huvuddvärgsignal: pilen bakom triangeln, var sin färg (s. 8)
        return {
          shapes: [
            { points: arrow(-0.78, -0.08, 0.36), closed: true, fill: dwarf, stroke: null, width: 0 },
            { points: triangle(0.04, 0.78, 0.36), closed: true, fill: "#000000", stroke: main, width: contour },
          ],
          gap: [-0.98, 0.98],
        };
      case "stop_lamp": // slutpunktsstopplykta: liten triangel bredvid spåret, aldrig kör (s. 12)
        return { shapes: [{ points: triangle(-0.3, 0.32, 0.26), closed: true, fill: "#000000", stroke: end ? RED : GREY, width: contour }], gap: null };
      case "fsi": // försignal: finns inte i dokumentets symboler; en ring i spårets grå
        return { shapes: [{ points: ring(0.28), closed: true, fill: "#000000", stroke: GREY, width: contour }], gap: [-0.45, 0.45] };
      default: // huvudsignal: triangel med kraftig kontur som pekar i rörelseriktningen (s. 6)
        return { shapes: [{ points: triangle(-0.42, 0.42, 0.36), closed: true, fill: "#000000", stroke: main, width: contour }], gap: [-0.62, 0.62] };
    }
  },
  // Stoppbock: kort stump med tvärslå, skild från spåret; grå, röd som slutpunkt (s. 16).
  buffer: (end) => {
    const colour = end ? RED : GREY;
    return [
      { points: [[-0.85, 0], [-0.55, 0]], closed: false, fill: null, stroke: "#000000", width: 4.5 * UNIT + 0.12 },
      { points: [[-0.55, 0], [0, 0]], closed: false, fill: null, stroke: colour, width: 4.5 * UNIT },
      { points: [[0.06, 0.42], [0.06, -0.42]], closed: false, fill: null, stroke: colour, width: 3.8 * UNIT },
    ];
  },
  // Vald start: blå för tågväg, gul för växlingsväg (the reference interlockings, STV-24).
  rings: { train: "#2256c3", shunting: "#d9a400", goal: "#60a5fa", blocked: "#4b5563", chosen: "#ffffff" },
};

function ring(radius: number): [number, number][] {
  return Array.from({ length: 16 }, (_, i): [number, number] => {
    const a = (i / 16) * 2 * Math.PI;
    return [Math.cos(a) * radius, Math.sin(a) * radius];
  });
}

/** The skins that can be chosen now. The rest are listed as coming. */
export const SKINS: Partial<Record<SkinId, Skin>> = { "85": SKIN_85 };

export function skinOf(id: SkinId): Skin {
  return SKINS[id] ?? SKIN_85;
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
