import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Panel, Route, TrackPlan } from "./api";
import { ChecksView, PanelView, RoutesView, TrackPlanView } from "./Sparplan";
import { readModelFile, routeLines, routesByKind, viewBox } from "./sparplan";

// A made-up station on the grid: a line, a switch and a siding below, as TKL's server sends it.
const panel: Panel = {
  source: "engine",
  width: 30,
  height: 9,
  cell: [24, 24],
  angle: "45",
  rows: 2,
  shortened: false,
  fields: [],
  lines: [
    { piece: "a", track: null, cells: [[3, 2], [10, 2]], real: [[0, 100], [700, 100]], free: false },
    { piece: "b", track: "1", cells: [[10, 2], [27, 2]], real: [[700, 100], [2400, 100]], free: false },
    { piece: "c", track: "2", cells: [[10, 2], [13, 5], [20, 5]], real: [[700, 100], [900, 160], [1600, 160]], free: false },
  ],
  nodes: [
    { id: "V", type: "line_exit", cell: [3, 2], real: [0, 100] },
    { id: "1", type: "switch", cell: [10, 2], real: [700, 100] },
    { id: "O", type: "buffer_stop", cell: [27, 2], real: [2400, 100] },
    { id: "S", type: "buffer_stop", cell: [20, 5], real: [1600, 160] },
  ],
  switches: [{ number: "1", type: "ordinary", node: "1", cell: [10, 2], real: [700, 100], trunk: "a", straight: "b", diverging: "c", pieces: [], label: [10, 0.9], laid: true }],
  signals: [
    { name: "In", type: "hsi", node: "V", cell: [5, 2], toward: [1, 0], symbol: [5, 2], label: [5, 0.9], side: "over", planned: false, real: [200, 100], real_toward: [1, 0] },
    { name: "S2", type: "stop_lamp", node: "S", cell: [20, 5], toward: [1, 0], symbol: [20, 4.4], label: [20, 3.9], side: "over", planned: false, real: [1600, 160], real_toward: [1, 0] },
  ],
  labels: [{ text: "V", kind: "exit", cell: [2.4, 2.35], anchor: "end", real: [0, 100] }],
  track_names: [{ name: "1", cell: [18, 1.4], train_number: [18.6, 0.6], real: [1500, 100] }],
  tables: [],
  platforms: [],
  building: null,
  real_box: [0, 100, 2400, 60],
};

const routes: Route[] = [
  { kind: "train", start: "In", end: "O", pieces: ["a", "b"], positions: { "1": "+" }, turntable: null },
  { kind: "shunting", start: "In", end: "S", pieces: ["a", "c"], positions: { "1": "-" }, turntable: null },
];

const plan: TrackPlan = {
  summary: { station_id: "provby", name: "Provby", level: 2, pieces: 3, switches: 1, levers: 1, signals: 2, track_circuits: 0, station_tracks: ["Spår 1", "Spår 2"], line_exits: ["V"], turntables: 0, plan: false },
  checks: { problems: [], notes: ["Linjeutfarten V saknar grannstation."] },
  routes: { train: 1, shunting: 1 },
  route_list: routes,
  panel,
};

describe("Spårplan", () => {
  it("draws the panel on the grid, in pixels, with the signals in the track line", () => {
    const html = renderToStaticMarkup(<PanelView panel={panel} form="schematic" route={null} />);
    expect(html).toContain('aria-label="Stationen på rutnätet"');
    expect(html).toContain('points="240,48 312,120 480,120"');
    expect(html.match(/<polyline/g)?.length).toBe(3);
    expect(html).toContain("huvudsignal In");
    expect(html).toContain('class="signal stop_lamp"');
    expect(html).toContain(">V</text>");
    expect(html).toContain('class="tagnummer"');
  });

  it("toggles to the soft view, in the drawing's millimetres", () => {
    const html = renderToStaticMarkup(<PanelView panel={panel} form="soft" route={null} />);
    expect(html).toContain('aria-label="Stationen i verklig form"');
    expect(html).toContain('points="700,100 900,160 1600,160"');
    expect(html).not.toContain("240,48");
    const box = viewBox(panel, "soft", null);
    expect(box.width).toBeGreaterThan(2400);
  });

  it("highlights a route in its colour, read-only", () => {
    const shunting = routes[1] ?? null;
    expect(routeLines(panel, shunting).map((l) => l.piece)).toEqual(["a", "c"]);
    const html = renderToStaticMarkup(<PanelView panel={panel} form="schematic" route={shunting} />);
    expect(html).toContain('class="vag-linje vaxling"');
    expect(html.match(/<polyline/g)?.length).toBe(5);
    const train = renderToStaticMarkup(<PanelView panel={panel} form="schematic" route={routes[0] ?? null} />);
    expect(train).toContain('class="vag-linje tagvag"');
  });

  it("lists the routes by kind and marks the chosen one", () => {
    expect(routesByKind(routes).train.map((r) => r.end)).toEqual(["O"]);
    const html = renderToStaticMarkup(<RoutesView routes={routes} counts={{ train: 1, shunting: 1 }} chosen={routes[0] ?? null} onChoose={() => undefined} />);
    expect(html).toContain("Tågvägar (1)");
    expect(html).toContain("Växlingsvägar (1)");
    expect(html).toContain('aria-pressed="true">In → O</button>');
    expect(html).toContain('aria-pressed="false">In → S</button>');
  });

  it("lists the checks: problems stop the model, notes do not", () => {
    const fine = renderToStaticMarkup(<ChecksView checks={plan.checks} />);
    expect(fine).toContain("Inga problem: modellen får köras.");
    expect(fine).toContain("Linjeutfarten V saknar grannstation.");
    const broken = renderToStaticMarkup(<ChecksView checks={{ problems: ["Växel 1 saknar stam."], notes: [] }} />);
    expect(broken).toContain("Problem · stoppar körningen");
    expect(broken).toContain("Växel 1 saknar stam.");
    expect(broken).not.toContain("Inga problem");
  });

  it("shows a whole station: summary, panel, checks and routes", () => {
    const html = renderToStaticMarkup(<TrackPlanView plan={plan} reference={null} />);
    expect(html).toContain("Provby");
    expect(html).toContain("Nivå 2 · signaler och spårledningar");
    expect(html).toContain("Motorns förslag: 30 × 9 rutor, 2 rader, 45°.");
    expect(html).toContain("Schematisk");
    const soft = renderToStaticMarkup(<TrackPlanView plan={plan} reference={{ id: "provby", name: "Provby", level: 2, plan: false }} form="soft" route={routes[0] ?? null} />);
    expect(soft).toContain("Referensstation · bara att titta på");
    expect(soft).toContain("Stationen i verklig form");
    expect(soft).toContain("Tågväg In → O");
  });

  it("shows the fields of a station too wide for the screen, and the whole station", () => {
    const wide: Panel = { ...panel, width: 120, fields: [{ name: "Fält 1", start: 0, end: 70 }, { name: "Fält 2", start: 70, end: 120 }] };
    const html = renderToStaticMarkup(<TrackPlanView plan={{ ...plan, panel: wide }} reference={null} />);
    expect(html).toContain("Hela stationen");
    expect(html).toContain("Fält 2");
    expect(viewBox(wide, "schematic", 1)).toEqual({ x: 70 * 24, y: 0, width: 50 * 24, height: 9 * 24 });
  });

  it("reads a model file before it goes to TKL, and says what is wrong in Swedish", () => {
    const good = JSON.stringify({ format: "trainmeet.station-model/1", station_id: "provby", name: "Provby", level: 2, nodes: [], pieces: [] });
    expect(readModelFile(good)).toEqual({ text: good, name: "Provby" });
    expect(readModelFile("inte json")).toEqual({ error: "Filen är inte JSON. Välj en stationsmodell, <station>.tkl.json." });
    expect(readModelFile("[1, 2]")).toEqual({ error: "Filen är inte en stationsmodell." });
    expect(readModelFile(JSON.stringify({ format: "trainmeet.station-outside/1" }))).toEqual({
      error: "Filen är inte en stationsmodell: formatet ska vara trainmeet.station-model/1.",
    });
  });
});
