// Mätbilden under in Foto (#89 del d4, CAD-33, STV-18): a station from CAD shows its modules'
// measuring images under the tracks when it has chosen to, each image moved by its matrix into the
// station's mm and clipped to its board; off by default, and grey with the reason without images.
// The station is made up: two straight modules of 1500 × 500 mm in a row with one track 140 mm
// from Kant 1, the second turned half a turn in its photo. Nothing here names a real station.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ImageUnder, Interlocking, Panel } from "./api";
import { applyMatrix, imagesOf, onPhoto, trackOnPhoto, type Pt } from "./foto";
import { Foto } from "./Foto";
import { skinOf } from "./skal";
import { drawing, filled } from "./stallverk";
import { text, type Say } from "./texter";

const say: Say = (key, vars) => text("sv", key, vars);

const panel: Panel = {
  source: "engine",
  width: 10,
  height: 4,
  cell: [24, 24],
  angle: "45",
  rows: 1,
  shortened: false,
  fields: [],
  lines: [
    { piece: "m1:s1", track: "1", cells: [[0, 1], [5, 1]], real: [[0, 140], [1500, 140]], free: false },
    { piece: "m2:s1", track: "1", cells: [[5, 1], [10, 1]], real: [[1500, 140], [3000, 140]], free: false },
    { piece: "fri", track: null, cells: [[10, 1], [12, 1]], real: [[3000, 140], [3600, 140]], free: false },
  ],
  nodes: [
    { id: "V", type: "line_exit", cell: [0, 1], real: [0, 140] },
    { id: "m", type: "module_joint", cell: [5, 1], real: [1500, 140] },
    { id: "s", type: "module_joint", cell: [10, 1], real: [3000, 140] },
    { id: "O", type: "line_exit", cell: [12, 1], real: [3600, 140] },
  ],
  switches: [],
  signals: [],
  labels: [],
  track_names: [],
  tables: [],
  platforms: [],
  building: null,
  real_box: [0, 140, 3600, 0],
};

const quiet: Interlocking = {
  station_id: "provby",
  level: 2,
  model: "abc",
  revision: 1,
  problem: null,
  switches: {},
  levers: {},
  turntables: {},
  routes: [],
  trains: [],
  signals: {},
  pieces: {},
  numbers: [],
  exits: [],
  tracks: {},
  sections: {},
  functions: [],
  events: [],
  last_id: 0,
  field: null,
};

/** The first module photographed as it lies, at 10 mm per pixel with 20 mm of margin; the second
 * read the other way round: its image turned half a turn into the module. */
function under(on: boolean): ImageUnder {
  const board = (x: number): [number, number][] => [
    [x, 0],
    [x + 1500, 0],
    [x + 1500, 500],
    [x, 500],
  ];
  return {
    available: true,
    reason: null,
    on,
    images: [
      { module: "m1", version: 1, job: "j1", title: "M-001 Infart", width: 154, height: 54, matrix: [10, 0, 0, 10, -20, -20], outline: board(0), bytes: 1000, url: "/api/tkl/1/matbilden/m1/1?bild=j1" },
      { module: "m2", version: 2, job: "j2", title: "M-002 Linje", width: 154, height: 54, matrix: [-10, 0, 0, -10, 3020, 520], outline: board(1500), bytes: 1000, url: "/api/tkl/1/matbilden/m2/2?bild=j2" },
    ],
    missing: ["M-003 Bortom: Modulen är inte fotad i TrainMeet CAD; Foto ritar den som vektorer."],
    gauge: 16.5,
    bytes: 2000,
    limit: 32 * 2 ** 20,
  };
}

function foto(shown: ImageUnder | null, onUnder?: (on: boolean) => void): string {
  const state = filled(quiet);
  return renderToStaticMarkup(<Foto panel={panel} drawn={drawing(panel, state, new Set(), new Set())} state={state} skin={skinOf("foto")} say={say} under={shown} onUnder={onUnder} />);
}

describe("Mätbilden under in Foto (#89 del d4, CAD-33)", () => {
  it("puts a known corner of each image on its module's corner, turned and all", () => {
    const [first, second] = under(true).images ?? [];
    if (!first || !second) throw new Error("two images");
    // The image's pixel at its margin's end is the board's corner at gable A and Kant 1.
    expect(applyMatrix(first.matrix, [2, 2])).toEqual([0, 0]);
    expect(applyMatrix(first.matrix, [152, 52])).toEqual([1500, 500]);
    // Turned half a turn: the image's far corner is the second board's first.
    expect(applyMatrix(second.matrix, [152, 52])).toEqual([1500, 0]);
    expect(applyMatrix(second.matrix, [2, 2])).toEqual([3000, 500]);
    // The track 140 mm from Kant 1 is on the image's row 16, 14 from the turned one's far edge.
    expect(applyMatrix(second.matrix, [77, 54 - 16])[1]).toBe(140);
    const images = imagesOf(under(true));
    expect(images.map((i) => i.transform)).toEqual(["matrix(10 0 0 10 -20 -20)", "matrix(-10 0 0 -10 3020 520)"]);
    expect(onPhoto(images, [750, 250])).toBe(true);
    expect(onPhoto(images, [3300, 140])).toBe(false);
    expect(trackOnPhoto(images, panel.lines[1]?.real as Pt[])).toBe(true);
    expect(trackOnPhoto(images, panel.lines[2]?.real as Pt[])).toBe(false);
  });

  it("draws the images under the tracks, clipped to their boards, only when the station has chosen it", () => {
    const off = foto(under(false), () => undefined);
    expect(off).not.toContain("<image");
    expect(off).toMatch(/<button[^>]*class="stv-matbild"[^>]*aria-pressed="false"[^>]*>Mätbilden under<\/button>/);
    expect(off.match(/stroke="#bdb8ad"/g)?.length).toBe(3);
    const on = foto(under(true), () => undefined);
    expect(on).toMatch(/aria-pressed="true"[^>]*>Mätbilden under/);
    expect(on.match(/<image /g)?.length).toBe(2);
    expect(on).toContain('href="/api/tkl/1/matbilden/m1/1?bild=j1"');
    expect(on).toContain('transform="matrix(-10 0 0 -10 3020 520)"');
    expect(on).toContain('<clipPath id="foto-matbild-1" clipPathUnits="userSpaceOnUse"><polygon points="1500,0 3000,0 3000,500 1500,500"></polygon></clipPath>');
    expect(on).toContain('clip-path="url(#foto-matbild-0)"');
    // Under the tracks: the images come before the rails, and the photographed boards' tracks
    // have no vector ballast or sleepers; the track off the photos keeps them.
    expect(on.indexOf("<image ")).toBeLessThan(on.indexOf('class="ralar"'));
    expect(on.match(/stroke="#bdb8ad"/g)?.length).toBe(1);
    expect(on.match(/class="ral"/g)?.length).toBe(6);
    // The rails at H0's gauge, on the photo's: 8.25 mm each side of the track's centre; and the
    // view takes in the whole boards.
    expect(on).toContain('points="0,131.75 1500,131.75"');
    expect(on).toContain('points="0,148.25 1500,148.25"');
    expect(on).toMatch(/viewBox="-76\.74 0 [\d.]+ 500"/);
    expect(off).not.toContain("131.75");
    // The modules drawn as vectors are named in the button's title.
    expect(on).toContain("Ritas som vektorer: M-003 Bortom");
  });

  it("is grey with the reason without images, and without the choice there is no button", () => {
    const reason = "Mätbilden under kräver en station från TrainMeet CAD, med Från CAD under Rita i Studio. Foto ritar stationen som vektorer.";
    const grey = foto({ available: false, reason, on: false, images: [], missing: [], gauge: null, bytes: 0, limit: 0 }, () => undefined);
    expect(grey).toMatch(/<button[^>]*class="stv-matbild"[^>]*disabled=""[^>]*>Mätbilden under/);
    expect(grey).toContain(`role="note">${reason}</p>`);
    expect(grey).not.toContain("<image");
    // A station that chose it but has lost its images shows none.
    expect(imagesOf({ ...under(true), available: false, reason })).toEqual([]);
    expect(foto(null)).not.toContain("stv-matbild");
  });
});
