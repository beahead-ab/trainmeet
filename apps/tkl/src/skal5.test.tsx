// The last two skins and the turntable (#84 del d): Manöver, the owner's free panel (STV-46), Foto,
// the station from above in its real shape where the trains roll (STV-06), and the turntable in
// every skin. Nothing here names a real station (RS13): the made-up Provby, and a reference
// station picked by what its data has, read from TKL's model files.
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../../contracts/tkl";
import type { FunctionShown, Interlocking, InterlockingAnswer, Manover, Panel, TrackPlan } from "./api";
import { along, ease, fotoScene, gaugeOf, hasRealForm, placeTrain, rollOf, trainKind, trainLength, trainsOf, vehicles, type Pt } from "./foto";
import { Foto } from "./Foto";
import { cleaned } from "./ManoverInstallningar";
import { Panelen } from "./Panelen";
import { changeScreen, ownerChoices, skinOf, STANDARD, type Screen, type SkinId } from "./skal";
import { Stallverk12 } from "./Stallverk12";
import { drawing, filled, functionCall, lengthOf, NOTHING, routeEnds, tables, type Calls, type Filled } from "./stallverk";
import { text, type Say } from "./texter";

const say: Say = (key, vars) => text("sv", key, vars);

// Provby: the line from V, the entry signal In, switch 1 with track 1 straight on and track 2
// diverging, the exit signal Ut, a buffer stop S, and a turntable T off track 2 with two tracks.
const provby: Panel = {
  source: "engine",
  width: 30,
  height: 9,
  cell: [24, 24],
  angle: "45",
  rows: 2,
  shortened: false,
  fields: [],
  lines: [
    { piece: "a", track: null, cells: [[3, 2], [6, 2]], real: [], free: false },
    { piece: "a2", track: null, cells: [[6, 2], [10, 2]], real: [], free: false },
    { piece: "b", track: "1", cells: [[10, 2], [27, 2]], real: [], free: false },
    { piece: "c", track: "2", cells: [[10, 2], [13, 5], [20, 5]], real: [], free: false },
    { piece: "t1", track: null, cells: [[23, 5], [21, 5]], real: [], free: true },
    { piece: "t2", track: null, cells: [[24, 6], [24, 8]], real: [], free: true },
  ],
  nodes: [
    { id: "V", type: "line_exit", cell: [3, 2], real: null },
    { id: "1", type: "switch", cell: [10, 2], real: null },
    { id: "O", type: "line_exit", cell: [27, 2], real: null },
    { id: "S", type: "buffer_stop", cell: [20, 5], real: null },
    { id: "T", type: "turntable", cell: [24, 5], real: null },
  ],
  switches: [{ number: "1", type: "ordinary", node: "1", cell: [10, 2], real: null, trunk: "a2", straight: "b", diverging: "c", pieces: [], label: [10, 0.9], laid: true }],
  signals: [
    { name: "In", type: "hdvsi", node: "In", cell: [6, 2], toward: [1, 0], symbol: [6, 2], label: [6, 0.9], side: "over", planned: false, real: null, real_toward: null },
    { name: "Ut", type: "hsi", node: "Ut", cell: [24, 2], toward: [1, 0], symbol: [24, 2], label: [24, 0.9], side: "over", planned: false, real: null, real_toward: null },
  ],
  labels: [{ text: "V", kind: "exit", cell: [2.4, 2.35], anchor: "end", real: null }],
  track_names: [
    { name: "1", cell: [18, 1.4], train_number: [18.6, 0.6], real: null },
    { name: "2", cell: [18, 4.4], train_number: [18.6, 3.6], real: null },
  ],
  tables: [{ id: "T", node: "T", cell: [24, 5], radius: 1, real: null, real_radius: null }],
  platforms: [],
  building: null,
  real_box: null,
};

const plan: TrackPlan = {
  summary: { station_id: "provby", name: "Provby", level: 2, pieces: 6, switches: 1, levers: 1, signals: 2, track_circuits: 3, station_tracks: ["Spår 1", "Spår 2"], line_exits: ["V", "O"], turntables: 1, plan: false },
  checks: { problems: [], notes: [] },
  routes: { train: 1, shunting: 0 },
  route_list: [{ kind: "train", start: "In", end: "Ut", pieces: ["a2", "b"], positions: { "1": "+" }, turntable: null }],
  panel: provby,
};

const fn = (name: string, type: FunctionShown["type"], extra: Partial<FunctionShown> = {}): FunctionShown => ({
  name,
  type,
  on: false,
  mode: null,
  modes: [],
  pieces: [],
  signals: [],
  blocked: [],
  switches: [],
  locked: {},
  at: null,
  codes: {},
  note: null,
  ...extra,
});

const turntable = fn("Vändskivan", "turntable", { at: "T", modes: [{ value: "t1", label: "Stall 1" }, { value: "t2", label: "Stall 2" }], codes: {} });
const quiet: Interlocking = {
  station_id: "provby",
  level: 2,
  model: "abc",
  revision: 1,
  problem: null,
  switches: { "1": { position: "+", control: "tkl", routes: [], protection: false, local: false, function: null } },
  levers: { "1": "+" },
  turntables: { T: null },
  routes: [],
  trains: [{ id: 3, number: "41", call: null, section: "Spår 1", exit: null }],
  signals: { In: { aspect: "stop", end: false, blocked: false }, Ut: { aspect: "stop", end: false, blocked: false } },
  pieces: { b: { state: "occupied", route: null } },
  numbers: [{ number: "41", train: 3, colour: "red", section: "Spår 1", exit: null, pieces: ["b"], track: null, route: null, estimated: true }],
  exits: [{ exit: "V", outside: "v", pieces: ["a"], aspect: "stop" }],
  tracks: { "Spår 1": "1", "Spår 2": "2" },
  sections: { "Linje V": ["a"], Vx1: ["a2"], "Spår 1": ["b"], "Spår 2": ["c"] },
  functions: [fn("Signalstopp", "signal_stop", { signals: ["In"] }), turntable],
  events: [],
  last_id: 3,
};
const ends = routeEnds(plan.route_list ?? []);
const page = {
  level: 2,
  view: null,
  hubNote: "TKL är inte ansluten till en träff.",
  outside: null,
  journal: [],
  sounds: { request: false, coming: false, alarm: false },
  busy: false,
  onSend: () => undefined,
  onExit: () => undefined,
  onState: () => undefined,
};
const owners = (extra: Partial<Manover> = {}): Manover => ({ symbols: "85", shown: { track_names: true, switch_numbers: true, signal_ids: true, train_numbers: true, functions: true }, labels: { tracks: {}, signals: {}, switches: {} }, ...extra });
const screen = (skin: SkinId): Screen => ({ view: "all", skin, proportion: 50 });

describe("Manöver: the owner's free panel (STV-46)", () => {
  it("draws with each of the three standard skins' symbols, their very entries", () => {
    for (const symbols of ["85", "95", "59"] as const) {
      const html = renderToStaticMarkup(<Stallverk12 {...page} plan={plan} panel={provby} state={quiet} initial={{ plan, state: quiet, screen: screen("manover"), manover: owners({ symbols }) }} />);
      expect(html).toContain(`class="stv-panel skal-${symbols} skal-manover" data-symbols="${symbols}"`);
      expect(skinOf("manover", symbols)).toBe(STANDARD[symbols]);
      // Everything shown and no labels: the same drawing as the standard skin, but for its class.
      const drawn = drawing(provby, filled(quiet), new Set(), ends);
      const standard = renderToStaticMarkup(<Panelen panel={provby} drawn={drawn} skin={STANDARD[symbols]} say={say} title="Provby" />);
      const manover = renderToStaticMarkup(<Panelen panel={provby} drawn={drawn} skin={skinOf("manover", symbols)} say={say} title="Provby" owner={ownerChoices(owners({ symbols }))} />);
      expect(manover.replaceAll(" skal-manover", "").replace(` data-symbols="${symbols}"`, "")).toBe(standard);
    }
    const in59 = renderToStaticMarkup(<Stallverk12 {...page} plan={plan} panel={provby} state={quiet} initial={{ plan, state: quiet, screen: screen("manover"), manover: owners({ symbols: "59" }) }} />);
    expect(in59).toContain("data-lamp=");
    expect(in59).toContain("Manöver · stationens egen panel med symboler och färger ur 59");
    expect(in59).toContain('title="Manöver · ägarens fria panel, symboler ur 59. Ändras i Studio › Spårplan."');
  });

  it("hides what the owner turned off", () => {
    const all = renderToStaticMarkup(<Stallverk12 {...page} plan={plan} panel={provby} state={quiet} initial={{ plan, state: quiet, screen: screen("manover"), manover: owners() }} />);
    for (const shown of ['data-track-name="2"', 'data-switch-number="1"', 'data-signal-id="In"', "Panelens knappar"]) expect(all).toContain(shown);
    expect(all).not.toContain('class="tagnummer" display="none"');
    const none = owners({ shown: { track_names: false, switch_numbers: false, signal_ids: false, train_numbers: false, functions: false } });
    const html = renderToStaticMarkup(<Stallverk12 {...page} plan={plan} panel={provby} state={quiet} initial={{ plan, state: quiet, screen: screen("manover"), manover: none }} />);
    for (const hidden of ["data-track-name=", "data-switch-number=", "data-signal-id=", "Panelens knappar"]) expect(html).not.toContain(hidden);
    expect(html).toContain('class="tagnummer" display="none"');
    // The symbols and the click targets stay: the panel still works.
    expect(html).toContain('data-signal="In"');
    expect(html).toContain('aria-label="Signal In"');
    // In 85 nothing is hidden: the owner's choices are Manöver's alone.
    const in85 = renderToStaticMarkup(<Stallverk12 {...page} plan={plan} panel={provby} state={quiet} initial={{ plan, state: quiet, screen: screen("85"), manover: none }} />);
    expect(in85).toContain('data-signal-id="In"');
    expect(in85).toContain("Panelens knappar");
  });

  it("shows the owner's labels while the ids stay as they are", () => {
    const labels = { tracks: { "2": "Godsspåret" }, signals: { In: "Infart" }, switches: { "1": "V1" } };
    const html = renderToStaticMarkup(<Stallverk12 {...page} plan={plan} panel={provby} state={quiet} initial={{ plan, state: quiet, screen: screen("manover"), manover: owners({ labels }) }} />);
    expect(html).toMatch(/data-signal-id="In"[^>]*>Infart</);
    expect(html).toMatch(/data-switch-number="1"[^>]*>V1</);
    expect(html).toMatch(/data-track-name="2"[^>]*>Godsspåret</);
    expect(html).toContain('data-signal="In"');
    expect(html).toContain('aria-label="Signal Infart"');
    expect(html).toContain('aria-label="Växel V1"');
    // The interlocking's names are untouched: the drawing in logical terms is the same.
    expect(drawing(provby, filled(quiet), new Set(), ends).signals.map((s) => s.name)).toEqual(["In", "Ut"]);
    // What the settings page sends: trimmed, without empty labels or labels that repeat the id.
    expect(cleaned(owners({ labels: { tracks: { "1": " ", "2": " Godsspåret " }, signals: { In: "In" }, switches: {} } })).labels).toEqual({ tracks: { "2": "Godsspåret" }, signals: {}, switches: {} });
  });
});

// --- Foto ----------------------------------------------------------------------------------------

type Model = components["schemas"]["trainmeet.station-model-1"];
const MODELS = import.meta.glob<Model>("../../../tkl/referens/*.tkl.json", { eager: true, import: "default" });

/** A panel for Foto from a model: its pieces in their real shape, the nodes, the signals and the
 * switches where the drawing has them. Foto reads only the real shape, so the grid is a stand-in. */
function realPanel(model: Model): Panel {
  const at = new Map<string, Pt>();
  for (const p of model.pieces) {
    const g = (p.geometry ?? []) as Pt[];
    if (g.length < 2) continue;
    at.set(p.start, g[0] as Pt);
    at.set(p.end, g[g.length - 1] as Pt);
  }
  const all = model.pieces.flatMap((p) => (p.geometry ?? []) as Pt[]);
  const xs = all.map((p) => p[0]);
  const ys = all.map((p) => p[1]);
  const box: [number, number, number, number] = [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
  const toward = (piece: string, node: string): [number, number] | null => {
    const p = model.pieces.find((x) => x.id === piece);
    const g = (p?.geometry ?? []) as Pt[];
    if (!p || g.length < 2) return null;
    const [a, b] = p.end === node ? [g[g.length - 2] as Pt, g[g.length - 1] as Pt] : [g[1] as Pt, g[0] as Pt];
    const n = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    return [(b[0] - a[0]) / n, (b[1] - a[1]) / n];
  };
  return {
    source: "engine",
    width: 10,
    height: 4,
    cell: [24, 24],
    angle: "45",
    rows: 1,
    shortened: false,
    fields: [],
    lines: model.pieces.map((p) => ({ piece: p.id, track: p.track ?? null, cells: [[0, 0], [1, 0]], real: (p.geometry ?? []) as Pt[], free: false })),
    nodes: model.nodes.map((n) => ({ id: n.id, type: n.type, cell: [0, 0], real: at.get(n.id) ?? null })),
    switches: (model.switches ?? []).map((s) => ({ number: s.number, type: s.type, node: s.node, cell: [0, 0], real: at.get(s.node) ?? null, trunk: s.trunk ?? null, straight: s.straight ?? null, diverging: s.diverging ?? null, pieces: [], label: [0, -1], laid: true })),
    signals: (model.signals ?? []).map((s) => ({ name: s.name, type: s.type, node: s.node, cell: [0, 0], toward: [1, 0], symbol: [0, 0], label: [0, -1], side: "over", planned: s.planned ?? false, real: at.get(s.node) ?? null, real_toward: toward(s.approach, s.node) })),
    labels: [],
    track_names: [],
    tables: [],
    platforms: [],
    building: null,
    real_box: box,
  };
}

/** The reference station drawn by the engine, with track circuits and the largest real shape. */
function referenceStation(): Model {
  const found = Object.values(MODELS).filter((m) => !m.panel && (m.track_circuits ?? []).length > 0 && m.pieces.every((p) => (p.geometry ?? []).length > 1));
  const width = (m: Model) => {
    const xs = m.pieces.flatMap((p) => (p.geometry ?? []).map((q) => q[0]));
    return Math.max(...xs) - Math.min(...xs);
  };
  const best = found.sort((a, b) => width(b) - width(a))[0];
  if (!best) throw new Error("no reference station drawn by the engine with track circuits");
  return best;
}

/** A track's pieces in the order they lie, from one end: by the nodes they share. */
function ordered(model: Model, ids: string[]): string[] {
  const pieces = model.pieces.filter((p) => ids.includes(p.id));
  const count = (node: string) => pieces.filter((p) => p.start === node || p.end === node).length;
  let here = pieces.find((p) => count(p.start) === 1 || count(p.end) === 1) ?? pieces[0];
  if (!here) return [];
  let node = count(here.start) === 1 ? here.end : here.start;
  const found = [here.id];
  for (;;) {
    const next = pieces.find((p) => !found.includes(p.id) && (p.start === node || p.end === node));
    if (!next) return found;
    found.push(next.id);
    node = next.start === node ? next.end : next.start;
    here = next;
  }
}

/** A train route over a station track's pieces, split in two sections, with train 41 in the
 * first and goods train 9103 on another track. */
function onTheRoute(model: Model, at: 0 | 1): Interlocking {
  const [track, other] = (model.station_tracks ?? []).filter((t) => (t.pieces ?? []).length >= 2) as [NonNullable<Model["station_tracks"]>[number], NonNullable<Model["station_tracks"]>[number]];
  const pieces = ordered(model, track.pieces ?? []);
  const half = Math.ceil(pieces.length / 2);
  const sections = [
    { section: "Först", pieces: pieces.slice(0, half), released: at > 0 },
    { section: "Sist", pieces: pieces.slice(half), released: false },
  ];
  const here = sections[at] as (typeof sections)[number];
  return {
    ...quiet,
    station_id: model.station_id,
    switches: {},
    turntables: {},
    routes: [{ id: 7, kind: "train", start: "A", end: "B", chain: null, sections, positions: {}, locked: {}, protection: [], crossings: [], turntable: null, train: 3, at, aspect: "proceed", held: null, passed: [], leaves: null, enters: null, set_at: "2026-11-18T12:00:00Z" }],
    trains: [
      { id: 3, number: "41", call: null, section: here.section, exit: null },
      { id: 4, number: "9103", call: null, section: "Gods", exit: null },
    ],
    signals: {},
    pieces: Object.fromEntries([...pieces.map((p) => [p, { state: "train", route: 7 }] as const), ...here.pieces.map((p) => [p, { state: "occupied", route: 7 }] as const)]),
    numbers: [
      { number: "41", train: 3, colour: "red", section: here.section, exit: null, pieces: here.pieces, track: null, route: 7, estimated: true },
      { number: "9103", train: 4, colour: "red", section: "Gods", exit: null, pieces: other.pieces ?? [], track: null, route: null, estimated: true },
    ],
    exits: [],
    functions: [],
  };
}

describe("Foto: the station from above in its real shape (STV-06, STV-18)", () => {
  const model = referenceStation();
  const panel = realPanel(model);

  it("draws rails, sleepers and ballast from the real geometry, at the station's own gauge", () => {
    expect(hasRealForm(panel)).toBe(true);
    // H0: parallel tracks about 56 mm apart give the 16.5 mm gauge (the reference pages' FOTO_G).
    expect(gaugeOf(panel)).toBeGreaterThan(15);
    expect(gaugeOf(panel)).toBeLessThan(18);
    const state = filled(onTheRoute(model, 0));
    const html = renderToStaticMarkup(<Foto panel={panel} drawn={drawing(panel, state, new Set(), new Set())} state={state} skin={skinOf("foto")} say={say} />);
    expect(html).toContain('class="stv-panel skal-foto"');
    expect(html.match(/class="ral"/g)?.length).toBe(2 * model.pieces.length);
    expect(html).toContain('stroke="#bdb8ad"');
    expect(html).toContain('fill="url(#foto-gras)"');
    // The glow and the band: green for the train route, red where the train is.
    expect(html).toMatch(/data-state="train"[^>]*stroke="#3ee07a"/);
    expect(html).toMatch(/data-state="occupied"[^>]*stroke="#ff4b3e"/);
    // The signals from above with their names on white signs; red at stop.
    expect(html).toContain(`data-signal-id="${model.signals?.[0]?.name}"`);
    expect(html).toContain('fill="#ff3b30"');
  });

  it("draws the trains on their sections, a passenger train short and rounded, a goods train longer and square, the number on the roof", () => {
    expect([trainKind("41"), trainKind("9103"), trainKind("3795"), trainKind(null)]).toEqual(["passenger", "goods", "passenger", "shunt"]);
    expect(vehicles("passenger")).toHaveLength(3);
    expect(vehicles("goods")).toHaveLength(6);
    expect(trainLength("goods")).toBeGreaterThan(trainLength("passenger"));
    const state = filled(onTheRoute(model, 0));
    const html = renderToStaticMarkup(<Foto panel={panel} drawn={drawing(panel, state, new Set(), new Set())} state={state} skin={skinOf("foto")} say={say} />);
    const train = html.slice(html.indexOf('data-train="41"'), html.indexOf('data-train="9103"'));
    expect(train).toContain(">41</text>");
    expect(train).toContain('fill="#ebeae5"');
    expect(train.match(/fill="#b3262b"/g)?.length).toBe(6);
    const goods = html.slice(html.indexOf('data-train="9103"'));
    expect(goods).toContain(">9103</text>");
    expect(goods).toContain('fill="#d0471f"');
    // On its section: the train's centre lies on the section's real geometry.
    const [shown] = trainsOf(panel, state);
    expect(shown?.number).toBe("41");
    const centre = along(shown?.path ?? [], shown?.at ?? 0).at;
    const first = onTheRoute(model, 0).numbers?.[0]?.pieces ?? [];
    const near = Math.min(...first.flatMap((p) => (panel.lines.find((l) => l.piece === p)?.real ?? []) as Pt[]).map((q) => Math.hypot(q[0] - centre[0], q[1] - centre[1])));
    expect(near).toBeLessThan(gaugeOf(panel) * 10);
  });

  it("rolls the train with Kör from the section it was on to the next, along the route's pieces", () => {
    const u = gaugeOf(panel) / 8.6;
    const before = trainsOf(panel, filled(onTheRoute(model, 0))).find((t) => t.number === "41");
    const after = trainsOf(panel, filled(onTheRoute(model, 1))).find((t) => t.number === "41");
    if (!before || !after) throw new Error("no train 41");
    const start = along(before.path, before.at).at;
    const end = along(after.path, after.at).at;
    expect(Math.hypot(end[0] - start[0], end[1] - start[1])).toBeGreaterThan(50);
    const roll = rollOf(before, after, u);
    if (!roll) throw new Error("no roll");
    expect(roll.to).toBeGreaterThan(roll.from);
    const from = along(roll.path, roll.from).at;
    const to = along(roll.path, roll.to).at;
    expect(Math.hypot(from[0] - start[0], from[1] - start[1])).toBeLessThan(1);
    expect(Math.hypot(to[0] - end[0], to[1] - end[1])).toBeLessThan(1);
    // Halfway in time, halfway along the way, on the route's pieces.
    const mid = roll.from + (roll.to - roll.from) * ease(0.5);
    expect(mid).toBeCloseTo((roll.from + roll.to) / 2);
    const cars = placeTrain("passenger", roll.path, mid, u);
    expect(cars).toHaveLength(3);
    expect(lengthOf(roll.path)).toBeGreaterThan(roll.to - roll.from);
    expect([ease(0), ease(1)]).toEqual([0, 1]);
  });

  it("greys Foto for a station without the real shape, with the reason, and sends nothing", () => {
    expect(hasRealForm(provby)).toBe(false);
    const html = renderToStaticMarkup(<Stallverk12 {...page} plan={plan} panel={provby} state={quiet} initial={{ plan, state: quiet, screen: screen("foto") }} />);
    expect(html).toContain("Foto kräver stationens verkliga form (från CAD)");
    expect(html).toContain('class="stv-ram skal-foto gratt"');
    expect(html).not.toContain("<svg class=\"stv-panel");
    expect(fotoScene(provby, drawing(provby, filled(quiet), new Set(), ends), filled(quiet))).toBeNull();
    // The rest of the page is there, as in every skin.
    expect(html).toContain('id="kol-klarering"');
    expect(html).toContain("Panelens knappar");
  });
});

describe("A skin change sends nothing (STV-18)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("changes only this screen's settings, in every skin, and the drawing stays the same", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const kept = new Map<string, string>();
    const storage = { setItem: (k: string, v: string) => void kept.set(k, v) };
    let settings: Screen = screen("85");
    const before = drawing(provby, filled(quiet), new Set(), ends);
    for (const skin of ["manover", "foto", "95", "59", "85"] as const) {
      settings = changeScreen(1, settings, { skin }, storage);
      expect(settings.skin).toBe(skin);
      expect(JSON.parse(kept.get("tkl.skarm.1") ?? "{}").skin).toBe(skin);
      renderToStaticMarkup(<Stallverk12 {...page} plan={plan} panel={provby} state={quiet} initial={{ plan, state: quiet, screen: settings, manover: owners() }} />);
      expect(drawing(provby, filled(quiet), new Set(), ends)).toEqual(before);
    }
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("The turntable in the panel (RS4, STV-04)", () => {
  const turned = (piece: string | null): Filled => filled({ ...quiet, turntables: { T: piece } });

  it("draws the pit and the bridge at the angle of the track it points at, in every skin", () => {
    const [toStall1] = tables(provby, turned("t1"));
    const [toStall2] = tables(provby, turned("t2"));
    const [unknown] = tables(provby, turned(null));
    expect(toStall1).toMatchObject({ id: "T", piece: "t1", known: true, toward: [-1, 0], function: "Vändskivan" });
    expect(toStall2).toMatchObject({ piece: "t2", known: true, toward: [0, 1] });
    expect(unknown).toMatchObject({ piece: null, known: false, toward: [-1, 0] });
    for (const id of ["85", "95", "59"] as const) {
      const html = renderToStaticMarkup(<Panelen panel={provby} drawn={drawing(provby, turned("t2"), new Set(), ends)} skin={skinOf(id)} say={say} onTable={() => undefined} />);
      expect(html).toContain('data-turntable="T" data-bridge="t2" data-angle="270"');
      expect(html).toMatch(/<circle cx="576" cy="120" r="24"/);
      expect(html).toContain('aria-label="Vrid Vändskivan mot Stall 1"');
      expect(html).toContain('aria-label="Vrid Vändskivan mot Stall 2"');
    }
    const first = renderToStaticMarkup(<Panelen panel={provby} drawn={drawing(provby, turned("t1"), new Set(), ends)} skin={skinOf("85")} say={say} />);
    expect(first).toContain('data-bridge="t1" data-angle="180"');
    const dashed = renderToStaticMarkup(<Panelen panel={provby} drawn={drawing(provby, turned(null), new Set(), ends)} skin={skinOf("85")} say={say} />);
    expect(dashed).toMatch(/class="brygga"[^>]*stroke-dasharray=/);
    // A set route over the turntable holds the bridge, in the route's colour.
    const held = filled({ ...quiet, turntables: { T: "t1" }, routes: [{ id: 9, kind: "shunting", start: "In", end: "S", chain: null, sections: [{ section: "Spår 2", pieces: ["c", "t1"], released: false }], positions: {}, locked: {}, protection: [], crossings: [], turntable: "t1", train: null, at: -1, aspect: "shunt", held: null, passed: [], leaves: null, enters: null, set_at: "2026-11-18T12:00:00Z" }] });
    expect(tables(provby, held)[0]?.held).toBe("shunting");
    expect(renderToStaticMarkup(<Panelen panel={provby} drawn={drawing(provby, held, new Set(), ends)} skin={skinOf("85")} say={say} />)).toMatch(/class="brygga"[^>]*stroke="#feff00"/);
  });

  it("turns the bridge through the turntable's function when a track at it is clicked", async () => {
    const asked: unknown[] = [];
    const state = turned("t2");
    const answer: InterlockingAnswer = { accepted: true, message: "Vändskivan vriden mot Stall 1.", route: null, state: { ...quiet, revision: 2, turntables: { T: "t1" } }, reports: [] };
    const calls = { panelFunction: (ask: unknown) => (asked.push(ask), Promise.resolve(answer)) } as unknown as Calls;
    // The page turns it the way a click on a track at the turntable asks (Stallverk12's turn).
    const [table] = tables(provby, state);
    const track = table?.tracks.find((k) => k.label === "Stall 1");
    const done = await functionCall(NOTHING, { function: table?.function ?? "", action: "set", value: track?.piece ?? "", confirm: false }, calls);
    expect(asked).toEqual([{ function: "Vändskivan", action: "set", value: "t1", confirm: false }]);
    expect(done.valet.said?.text).toBe("Vändskivan vriden mot Stall 1.");
    expect(tables(provby, filled(done.state ?? quiet))[0]).toMatchObject({ piece: "t1", toward: [-1, 0] });
  });
});
